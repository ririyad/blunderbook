"""Adding games to a collection on the page (ROADMAP 12.4), as core's web import does
(CLAUDE.md §10): one import at a time, in a background thread with its own connection to
collection.db and one Stockfish, through the same :func:`collect.add` as ``blunderbook
collection import``. Its progress and report are read while it runs. Jobs live in memory:
the running one, or the last one, is kept for its report.

Stopping ``serve`` stops the job between positions: the games added so far stay, and the
game being analysed isn't saved, so adding the same text again finishes the rest.

The Collection's import and core's are separate: each runs one at a time, but one of each
can run together (two Stockfish processes).
"""

import sqlite3
import threading
import uuid
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, field
from typing import Final, Literal

from blunderbook import host
from blunderbook.core import engine, pgn
from blunderbook_collection import collect, games, store

JobStatus = Literal["running", "done", "stopped", "failed"]
GameStatus = Literal[
    "waiting",  # to be analysed
    "analysing",
    "added",  # analysed and added (or, when the import stopped, added before it did)
    "added_known",  # already analysed for another collection: added without the engine
    "member",  # already in this collection
    "duplicate",  # earlier in the same text
    "error",
    "not_analysed",  # the import stopped before it
]

STOP_WAIT_S: Final = 30.0  # how long a shutdown waits for the job to reach a position's end
READ_AS_CP1252: Final = "Read as Windows-1252 (the file isn't UTF-8)."
NO_GAMES: Final = "No games found in this PGN."
BUSY: Final = "Games are already being added to a collection. Wait for it to finish."
AGAIN: Final = "Add the same games again to analyse the rest. Games already added are skipped."


class Busy(Exception):
    """An import into a collection is running."""


class CantStart(Exception):
    """An import that can't run, with the HTTP status and a message to show."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True, slots=True)
class GameView:
    number: int
    players: str  # "Paul Morphy vs Duke Karl / Count Isouard"
    status: GameStatus
    reason: str | None
    warnings: tuple[str, ...]
    game_id: int | None  # in the collection: #collection/game/<id>


@dataclass(frozen=True, slots=True)
class JobView:
    id: str
    status: JobStatus
    collection: str  # its name
    collection_id: int | None  # None until a game is in it
    created: bool  # this import made the collection
    percent: int  # of the whole import
    game_index: int  # 1-based among the games to analyse; 0 before the first
    games_to_analyse: int
    engine_name: str | None
    games: tuple[GameView, ...]
    summary: str
    notes: tuple[str, ...]
    error: str | None


@dataclass
class Job:
    id: str
    name: str
    queue: tuple[games.Queued, ...]
    notes: list[str]
    status: JobStatus = "running"
    result: collect.Result | None = None  # when it's finished
    game: int | None = None  # the number of the game being analysed
    game_index: int = 0
    done: int = 0
    total: int = 0
    engine_name: str | None = None
    error: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def progress_for(self, queued: games.Queued, k: int, n: int) -> engine.Progress:
        with self.lock:
            self.game, self.game_index = queued.number, k
            self.done = self.total = 0

        def report(done: int, total: int) -> None:
            with self.lock:
                self.done, self.total = done, total

        return report

    def finish(self, status: JobStatus, result: collect.Result, error: str | None = None) -> None:
        with self.lock:
            self.status, self.result, self.error, self.game = status, result, error, None

    def view(self) -> JobView:
        with self.lock:
            ready = [q for q in self.queue if q.status == "ready"]
            result = self.result
            added = result.added if result is not None else {}
            return JobView(
                id=self.id,
                status=self.status,
                collection=self.name,
                collection_id=result.collection_id if result is not None else None,
                created=result.created if result is not None else False,
                percent=self._percent(len(ready)),
                game_index=self.game_index,
                games_to_analyse=len(ready),
                engine_name=self.engine_name,
                games=tuple(self._row(q, ready, added) for q in self.queue),
                summary=collect.summary(result) if result is not None else "",
                notes=tuple(self.notes),
                error=self.error,
            )

    def _percent(self, ready: int) -> int:
        if self.status == "done":
            return 100
        if not ready or not self.game_index:
            return 0
        part = self.done / self.total if self.total else 0.0
        return min(100, int(100 * (self.game_index - 1 + part) / ready))

    def _row(self, q: games.Queued, ready: list[games.Queued], added: dict[int, int]) -> GameView:
        status: GameStatus
        numbers = [r.number for r in ready]
        if q.number in added:
            status = "added_known" if q.status == "known" else "added"
        elif q.status in ("member", "duplicate", "error"):
            status = q.status
        elif self.status != "running":
            status = "not_analysed"
        elif q.status == "known":  # added first, before Stockfish starts
            status = "added_known"
        elif q.number == self.game:
            status = "analysing"
        else:
            # Games before the current one are added; their ids come with the report.
            current = numbers.index(self.game) if self.game in numbers else -1
            status = "added" if numbers.index(q.number) < current else "waiting"
        return GameView(q.number, q.players, status, q.reason, q.warnings, added.get(q.number))


OpenDb = Callable[[], sqlite3.Connection]


class Jobs:
    """The page's imports into collections: one at a time, the last one kept."""

    def __init__(self, open_db: OpenDb) -> None:
        self._open_db = open_db
        self._lock = threading.Lock()
        self._busy = False
        self._latest: Job | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            latest = self._latest
        return latest if latest is not None and latest.id == job_id else None

    def start(self, conn: sqlite3.Connection, data: bytes, into: str) -> Job:
        """Queue the games of ``data`` for the collection ``into`` and start adding them.
        Raises Busy, CantStart, games.BadName or host.HostError, with nothing started."""
        name = games.collection_name(into)
        depth = host.settings().engine_depth
        decoded = pgn.decode(data)
        notes = [READ_AS_CP1252] if decoded.encoding == "cp1252" else []
        with self._lock:
            if self._busy:
                raise Busy(BUSY)
            self._busy = True
        started = False
        try:
            queue = collect.queue(conn, decoded.text, name)
            if not queue:
                raise CantStart(422, NO_GAMES)
            found = store.find(conn, name)
            job = Job(uuid.uuid4().hex[:12], found.name if found else name, queue, notes)
            thread = threading.Thread(
                target=self._run, args=(job, depth), name="blunderbook-collection-import"
            )
            with self._lock:
                self._latest, self._thread = job, thread
            thread.start()
            started = True
            return job
        finally:
            if not started:
                self._release()

    def _run(self, job: Job, depth: int) -> None:
        result = collect.Result(job.queue)
        try:
            self._backup(job)
            with closing(self._open_db()) as conn:
                result = collect.add(
                    conn,
                    job.name,
                    job.queue,
                    host.engine,
                    depth=depth,
                    progress_for=job.progress_for,
                    on_engine=lambda sf: self._engine(job, sf),
                    should_stop=self._stop.is_set,
                )
            if result.error is not None:
                job.finish("failed", result, f"Analysis stopped: {result.error} {AGAIN}")
            elif result.stopped:
                job.finish("stopped", result, f"The import was stopped. {AGAIN}")
            else:
                job.finish("done", result)
        except (host.StorageError, sqlite3.Error) as exc:
            job.finish("failed", result, f"collection.db can't be used: {exc}")
        except Exception as exc:  # never leave a job "running" forever
            job.finish("failed", result, f"The import stopped: {exc}")
        finally:
            self._release()

    @staticmethod
    def _backup(job: Job) -> None:
        """The daily backups first, as ``collection import`` takes them. A failure is a note."""
        try:
            done = host.daily_backup()
        except host.HostError as exc:
            notes = [f"The daily backup didn't run: {exc}"]
        else:
            notes = [f"Daily backup: {p.name}" for p in done.taken] + list(done.problems)
        with job.lock:
            job.notes.extend(notes)

    @staticmethod
    def _engine(job: Job, sf: engine.Engine) -> None:
        with job.lock:
            job.engine_name = sf.name

    def _release(self) -> None:
        with self._lock:
            self._busy = False

    def stop(self) -> None:
        """Stop the running import between positions, and wait for its engine to close."""
        self._stop.set()
        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.join(STOP_WAIT_S)
