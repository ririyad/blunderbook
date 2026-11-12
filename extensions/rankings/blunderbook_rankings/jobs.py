"""The tab's Update button (ROADMAP 16.3): one update at a time, in a background thread with
its own connection to rankings.db and its own HTTP client, through the same
:func:`update.one` as ``blunderbook rankings update``. Its progress and outcome are read while
it runs. Jobs live in memory: the running one, or the last one, is kept for its report.

Stopping ``serve`` stops the job between steps (a download stops between chunks, a wait after
a 429 within a second): the source being updated keeps the lists it had.
"""

import sqlite3
import threading
import uuid
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, field
from datetime import date
from typing import Final, Literal

from blunderbook import host
from blunderbook_rankings import net, update

JobStatus = Literal["running", "done", "stopped", "failed"]

STOP_WAIT_S: Final = 10.0  # how long a shutdown waits for the job to reach a step's end
BUSY: Final = "An update is already running. Wait for it to finish."


class Busy(Exception):
    """An update is running."""


@dataclass(frozen=True, slots=True)
class JobView:
    id: str
    status: JobStatus
    percent: int  # of the whole update
    label: str  # what it's doing: "Downloading FIDE's rapid list"
    outcomes: tuple[update.Outcome, ...]  # one per source finished, in order
    notes: tuple[str, ...]  # the daily backup
    error: str | None  # why it stopped, when it did


@dataclass
class Job:
    id: str
    sources: tuple[str, ...]
    status: JobStatus = "running"
    fraction: float = 0.0
    label: str = "Starting…"
    outcomes: list[update.Outcome] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    error: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def step(self, index: int) -> update.Step:
        """Progress of the ``index``-th source, as part of the whole."""
        count = len(self.sources)

        def report(label: str, done: float) -> None:
            with self.lock:
                self.label = label
                self.fraction = (index + min(max(done, 0.0), 1.0)) / count

        return report

    def add(self, outcome: update.Outcome) -> None:
        with self.lock:
            self.outcomes.append(outcome)

    def finish(self, status: JobStatus, error: str | None = None) -> None:
        with self.lock:
            self.status, self.error = status, error
            if status == "done":
                self.fraction, self.label = 1.0, "Done"

    def view(self) -> JobView:
        with self.lock:
            return JobView(
                id=self.id,
                status=self.status,
                percent=min(100, int(100 * self.fraction)),
                label=self.label,
                outcomes=tuple(self.outcomes),
                notes=tuple(self.notes),
                error=self.error,
            )


OpenDb = Callable[[], sqlite3.Connection]


class Jobs:
    """The tab's updates: one at a time, the last one kept."""

    def __init__(self, open_db: OpenDb, today: Callable[[], date] = date.today) -> None:
        self._open_db = open_db
        self._today = today
        self._lock = threading.Lock()
        self._latest: Job | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            latest = self._latest
        return latest if latest is not None and latest.id == job_id else None

    def running(self) -> Job | None:
        with self._lock:
            latest = self._latest
        return latest if latest is not None and latest.view().status == "running" else None

    def start(self, source: str) -> Job:
        """Start updating ``source`` (one of update.SOURCES, or "all"). Raises Busy."""
        sources = update.SOURCES if source == "all" else (source,)
        with self._lock:
            if self._latest is not None and self._latest.view().status == "running":
                raise Busy(BUSY)
            job = Job(uuid.uuid4().hex[:12], tuple(sources))
            thread = threading.Thread(
                target=self._run, args=(job,), name="blunderbook-rankings-update", daemon=True
            )
            self._latest, self._thread = job, thread
        thread.start()
        return job

    def _run(self, job: Job) -> None:
        stop = self._stop.is_set
        name = job.sources[0]
        try:
            self._backup(job)
            contact = host.settings().chesscom_contact
            with closing(self._open_db()) as conn, net.client() as http:
                for i, name in enumerate(job.sources):
                    job.add(
                        update.one(
                            conn,
                            http,
                            name,
                            progress=job.step(i),
                            stop=stop,
                            wait=net.sleeper(stop),
                            today=self._today(),
                            contact=contact,
                        )
                    )
            job.finish("done")
        except net.Stopped:
            job.finish("stopped", f"Stopped. The {update.NAMES[name]} lists weren't changed.")
        except host.HostError as exc:
            job.finish("failed", str(exc))
        except (host.StorageError, sqlite3.Error) as exc:
            job.finish("failed", f"rankings.db can't be used: {exc}")
        except Exception as exc:  # never leave a job "running" forever
            job.finish("failed", f"The update stopped: {exc}")

    @staticmethod
    def _backup(job: Job) -> None:
        """The daily backups first, as ``rankings update`` takes them. A failure is a note."""
        try:
            done = host.daily_backup()
        except host.HostError as exc:
            notes = [f"The daily backup didn't run: {exc}"]
        else:
            notes = [f"Daily backup: {p.name}" for p in done.taken] + list(done.problems)
        with job.lock:
            job.notes.extend(notes)

    def stop(self) -> None:
        """Stop the running update between steps, and wait for it."""
        self._stop.set()
        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.join(STOP_WAIT_S)
