"""Imports started on the page (CLAUDE.md §10, "Web import").

One engine at a time: an import job or a FEN entry holds the engine slot, and anything else
asking for it is told to wait (409). An import runs in a background thread with its own
database connection and one Stockfish process, through the same code as
`blunderbook import` (``importer.run``). Its progress and report are read while it runs.
Jobs live in memory: the running one, or the last one, is kept for its report.
"""

import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Final, Literal

from blunderbook import config, ext, importer
from blunderbook.core import engine, pgn
from blunderbook.db import backup, connection, repo
from blunderbook.db.connection import StorageError

JobStatus = Literal["running", "done", "stopped", "failed"]
GameStatus = Literal[
    "waiting",
    "analysing",
    "analysed",
    "imported",
    "not_analysed",
    "needs_side",
    "duplicate",
    "error",
]

STOP_WAIT_S: Final = 30.0  # how long a shutdown waits for the job to reach a position's end
READ_AS_CP1252: Final = "Read as Windows-1252 (the file isn't UTF-8)."
NEEDS_SIDE: Final = (
    "None of your names matched a player. Add yours to my_names in config.toml, or save the "
    "game to a file and run blunderbook import FILE --side white (or black)."
)
NO_GAMES: Final = "No games found in this PGN."
BUSY: Final = "An import is already running. Wait for it to finish."
AGAIN: Final = "Import the same games again to analyse the rest. Games already saved are skipped."


class Busy(Exception):
    """The engine slot is taken: an import or a FEN entry is running."""


class CantStart(Exception):
    """An import or FEN entry that can't run, with the HTTP status and a message to show."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True, slots=True)
class EntryRef:
    id: int
    label: str  # "6. Nxd5"
    judgment: str


@dataclass(frozen=True, slots=True)
class GameRow:
    """One game of the text, as the report shows it."""

    number: int
    players: str
    date: str | None
    site_label: str | None
    my_color: str | None
    status: GameStatus
    reason: str | None
    warnings: tuple[str, ...]
    entries: tuple[EntryRef, ...]


@dataclass(frozen=True, slots=True)
class JobView:
    """A job as it is now: what the page draws."""

    id: str
    status: JobStatus
    percent: int  # of the whole import
    game: int | None  # the game being analysed (its number in the text)
    game_index: int  # its place among the games to analyse, 1-based (0 before the first)
    games_to_analyse: int
    done: int  # positions of that game done / total (CLAUDE.md §7.6)
    total: int
    engine_name: str | None
    games: tuple[GameRow, ...]
    summary: str
    notes: tuple[str, ...]
    error: str | None


@dataclass
class Job:
    id: str
    queue: list[importer.QueuedGame]
    notes: list[str]
    status: JobStatus = "running"
    saved: dict[int, importer.SavedGame] = field(default_factory=dict)
    game: int | None = None
    game_index: int = 0
    games_to_analyse: int = 0
    done: int = 0
    total: int = 0
    engine_name: str | None = None
    error: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @contextmanager
    def progress_for(
        self, queued: importer.QueuedGame, k: int, n: int
    ) -> Iterator[engine.Progress]:
        """``importer.run``'s per-game progress: kept here for the page to read."""
        with self.lock:
            self.game, self.game_index, self.games_to_analyse = queued.number, k, n
            self.done = self.total = 0

        def report(done: int, total: int) -> None:
            with self.lock:
                self.done, self.total = done, total

        yield report

    def finish(
        self, status: JobStatus, result: importer.RunResult | None = None, error: str | None = None
    ) -> None:
        with self.lock:
            if result is not None:
                self.queue, self.saved = list(result.queue), result.saved
            self.status, self.error, self.game = status, error, None

    def view(self) -> JobView:
        with self.lock:
            ready = [q for q in self.queue if q.status == "ready"]
            return JobView(
                id=self.id,
                status=self.status,
                percent=self._percent(len(ready)),
                game=self.game,
                game_index=self.game_index,
                games_to_analyse=self.games_to_analyse or len(ready),
                done=self.done,
                total=self.total,
                engine_name=self.engine_name,
                games=tuple(self._row(q) for q in self.queue),
                summary=importer.summary(self.queue, self.saved.values()),
                notes=tuple(self.notes),
                error=self.error,
            )

    def _percent(self, ready: int) -> int:
        """Of the whole import: finished games, plus the share of the current one."""
        if self.status == "done":
            return 100
        if not ready or not self.game_index:
            return 0
        part = self.done / self.total if self.total else 0.0
        return min(100, int(100 * (self.game_index - 1 + part) / ready))

    def _row(self, q: importer.QueuedGame) -> GameRow:
        saved = self.saved.get(q.number)
        entries: tuple[EntryRef, ...] = ()
        reason = q.reason
        status: GameStatus
        if saved is not None:
            status = "imported"
            entries = tuple(
                EntryRef(entry_id, b.finding.ply.label, b.finding.judgment)
                for b, entry_id in zip(saved.analysed.blunders, saved.blunder_ids, strict=True)
            )
        elif q.status == "needs_side":
            status, reason = "needs_side", NEEDS_SIDE
        elif q.status in ("duplicate", "error"):
            status = q.status
        elif self.status != "running":
            status = "not_analysed"
        elif self.game == q.number:
            status = "analysing"
        else:
            # Games before the current one are saved; their entries come with the report.
            ready = [r.number for r in self.queue if r.status == "ready"]
            before = self.game is not None and ready.index(q.number) < ready.index(self.game)
            status = "analysed" if before else "waiting"
        return GameRow(
            number=q.number,
            players=q.players,
            date=q.date,
            site_label=q.source.label if q.source else None,
            my_color=q.side,
            status=status,
            reason=reason,
            warnings=q.warnings,
            entries=entries,
        )


class ImportJobs:
    """The app's import jobs and its one engine slot."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._busy = False
        self._latest: Job | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # ------------------------------------------------------------ the engine slot

    def _claim(self) -> None:
        with self._lock:
            if self._busy or self._stop.is_set():
                raise Busy(BUSY)
            self._busy = True

    def _release(self) -> None:
        with self._lock:
            self._busy = False

    @contextmanager
    def engine_slot(self) -> Iterator[None]:
        """Hold the engine for one FEN entry. Raises Busy while an import runs."""
        self._claim()
        try:
            yield
        finally:
            self._release()

    # ------------------------------------------------------------ imports

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            latest = self._latest
        return latest if latest is not None and latest.id == job_id else None

    def start(self, data: bytes) -> Job:
        """Read the text, queue its games and start analysing the ready ones. Raises Busy,
        CantStart, config.ConfigError or StorageError, with nothing started."""
        cfg = config.load()
        decoded = pgn.decode(data)
        notes = [READ_AS_CP1252] if decoded.encoding == "cp1252" else []
        self._claim()
        started = False
        try:
            with closing(connection.connect(self.db_path, any_thread=True)) as conn:
                known = repo.known_fingerprints(conn)
            queue = list(importer.prepare(decoded.text, config.all_names(cfg), known=known))
            if not queue:
                raise CantStart(422, NO_GAMES)
            job = Job(uuid.uuid4().hex[:12], queue, notes)
            if not any(q.status == "ready" for q in queue):
                job.status = "done"  # nothing to analyse: duplicates, errors, needs side
            else:
                program = _stockfish(cfg)
                thread = threading.Thread(
                    target=self._run, args=(job, cfg, program), name="blunderbook-import"
                )
                with self._lock:
                    self._thread = thread
                thread.start()
                started = True
            with self._lock:
                self._latest = job
            return job
        finally:
            if not started:
                self._release()

    def _run(self, job: Job, cfg: config.Config, program: Path) -> None:
        try:
            backup_notes = _daily_backup(cfg, self.db_path)
            with job.lock:
                job.notes.extend(backup_notes)
            with (
                closing(connection.connect(self.db_path, any_thread=True)) as conn,
                engine.Engine.open(
                    [str(program)], threads=cfg.engine_threads, hash_mb=cfg.engine_hash_mb
                ) as sf,
            ):
                with job.lock:
                    job.engine_name = sf.name
                    note = engine.version_note(sf.info)
                    if note:
                        job.notes.append(note)
                result = importer.run(
                    conn,
                    job.queue,
                    sf,
                    depth=cfg.engine_depth,
                    thresholds=cfg.thresholds,
                    progress_for=job.progress_for,
                    should_stop=self._stop.is_set,
                )
            if result.error is not None:
                job.finish("failed", result, f"Analysis stopped: {result.error} {AGAIN}")
            elif result.stopped:
                job.finish("stopped", result, f"The import was stopped. {AGAIN}")
            else:
                job.finish("done", result)
        except engine.EngineError as exc:
            job.finish("failed", error=f"Analysis stopped: {exc} {AGAIN}")
        except (StorageError, sqlite3.Error) as exc:
            job.finish("failed", error=f"The database can't be used: {exc}")
        except Exception as exc:  # never leave a job "running" forever
            job.finish("failed", error=f"The import stopped: {exc}")
        finally:
            self._release()

    def stop(self) -> None:
        """Stop the running import between positions, and wait for its engine to close."""
        self._stop.set()
        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.join(STOP_WAIT_S)

    # ------------------------------------------------------------ FEN entries

    def log_fen(
        self, conn: sqlite3.Connection, fen: str, move: str, opponent: str | None, on: date
    ) -> tuple[importer.FenOutcome, list[str]]:
        """A FEN quick entry, as `blunderbook fen` logs it. Raises Busy, CantStart or
        config.ConfigError."""
        cfg = config.load()
        try:
            queued = importer.prepare_fen(
                fen,
                move,
                me=cfg.my_names[0] if cfg.my_names else None,
                opponent=opponent,
                played_on=on,
            )
        except importer.FenError as exc:
            raise CantStart(422, str(exc)) from None
        earlier = importer.find_logged(conn, queued)
        if earlier is not None:
            return earlier, []
        with self.engine_slot():
            program = _stockfish(cfg)
            notes = _daily_backup(cfg, self.db_path)
            try:
                with engine.Engine.open(
                    [str(program)], threads=cfg.engine_threads, hash_mb=cfg.engine_hash_mb
                ) as sf:
                    note = engine.version_note(sf.info)
                    outcome = importer.log_fen(
                        conn, queued, sf, depth=cfg.engine_depth, thresholds=cfg.thresholds
                    )
            except engine.EngineError as exc:
                raise CantStart(503, f"Analysis stopped: {exc} Nothing was logged.") from None
        return outcome, [*notes, *([note] if note else [])]


def _stockfish(cfg: config.Config) -> Path:
    location = config.locate_stockfish(None, cfg, config_dir=config.config_path().parent)
    if location.path is None:
        raise CantStart(503, f"Can't analyse: {location.problem or config.NOT_FOUND}")
    return location.path


def _daily_backup(cfg: config.Config, db: Path) -> list[str]:
    """The automatic backups before a change (CLAUDE.md §6): Blunderbook's database and those
    of extensions that are on. They never stop the import; a failure is a note."""
    if not cfg.backup.auto:
        return []
    return list(ext.daily_backups(cfg, db).problems)
    try:
        backup.auto(db, config.backup_folder(cfg), keep=cfg.backup.keep)
    except (config.ConfigError, backup.BackupError) as exc:
        return [f"The daily backup didn't work: {exc}"]
    return []
