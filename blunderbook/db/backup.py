"""Database backups and restore (CLAUDE.md §6 Backups).

A backup is a ``VACUUM INTO`` snapshot, never a file copy: with WAL, recent changes can
still sit in the ``-wal`` file. The snapshot is written to a temp file next to the
database and must pass ``PRAGMA integrity_check``. Then it's copied into the backup folder
as ``….db.partial`` and renamed, so the folder (often one a cloud drive syncs) only ever
gets whole, checked files.

Backups are named ``blunderbook-YYYY-MM-DD_HHMMSSZ[-reason].db`` (UTC). An extension's
database (CLAUDE.md §15) is backed up the same way, named after it: ``library-…db``. Rotation
and the daily check read only files with that name and that database's prefix. Anything
else in the folder is never touched.

Maintenance SQL only. Data SQL lives in repo.py.
"""

import os
import re
import shutil
import sqlite3
import tempfile
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from blunderbook.db import connection
from blunderbook.db.connection import CORE, StorageError, Store

AUTO_EVERY = timedelta(hours=24)  # the daily backup runs when the newest is older than this
STALE_AFTER = timedelta(days=7)  # doctor warns when the newest is older than this

_STAMP = "%Y-%m-%d_%H%M%S"
_NAME = re.compile(r"([a-z]+)-(\d{4}-\d{2}-\d{2}_\d{6})Z(?:-([a-z]+(?:-[a-z]+)*))?\.db")
_REASON = re.compile(r"[a-z]+(?:-[a-z]+)*")


class BackupError(Exception):
    """A backup or restore that didn't happen, with a message ready to show."""


@dataclass(frozen=True, slots=True)
class Backup:
    """A file in the backup folder with a generated name."""

    path: Path
    taken_at: datetime  # UTC, read from the name
    reason: str | None  # "pre-migrate", "pre-restore", or None
    store: str = CORE.name  # whose database: "blunderbook", or an extension's name


@dataclass(frozen=True, slots=True)
class Snapshot:
    """What ``take()`` did: the new backup, and the old ones rotation deleted."""

    backup: Backup
    removed: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class Restored:
    safety: Backup | None  # the -pre-restore copy; None when there was nothing to keep
    version: int  # the restored file's schema
    upgraded: tuple[int, ...]  # migrations applied after copying it in


# ---------------------------------------------------------------- names


def file_name(moment: datetime, reason: str | None = None, *, store: Store = CORE) -> str:
    if reason is not None and _REASON.fullmatch(reason) is None:
        raise ValueError(f"A backup reason is lowercase words joined by '-', not {reason!r}.")
    suffix = f"-{reason}" if reason else ""
    return f"{store.name}-{_utc(moment):{_STAMP}}Z{suffix}.db"


def parse_name(path: Path) -> Backup | None:
    """The backup ``path`` names, or None when it isn't a generated name."""
    match = _NAME.fullmatch(path.name)
    if match is None:
        return None
    try:
        taken_at = datetime.strptime(match[2], _STAMP).replace(tzinfo=UTC)
    except ValueError:  # the right shape but not a real time, such as month 13
        return None
    return Backup(path, taken_at, match[3], match[1])


def list_backups(folder: Path, store: Store = CORE) -> list[Backup]:
    """``store``'s backups in ``folder``, oldest first. A missing folder has none."""
    try:
        paths = list(folder.iterdir())
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise BackupError(f"Can't read the backup folder {folder}: {_why(exc)}") from None
    found = [
        b
        for p in paths
        if (b := parse_name(p)) is not None and b.store == store.name and p.is_file()
    ]
    return sorted(found, key=lambda b: (b.taken_at, b.path.name))


def newest(folder: Path, store: Store = CORE) -> Backup | None:
    found = list_backups(folder, store)
    return found[-1] if found else None


# ---------------------------------------------------------------- backup


def take(
    db: Path,
    folder: Path,
    *,
    keep: int | None,
    reason: str | None = None,
    now: datetime | None = None,
    store: Store = CORE,
) -> Snapshot:
    """Back up ``db`` into ``folder``, then keep only the newest ``keep`` of ``store``'s
    backups there. ``keep=None`` skips rotation (a restore must not rotate away the file it
    reads)."""
    if keep is not None and keep < 1:
        raise ValueError("keep must be 1 or more.")
    moment = _utc(now)
    file_name(moment, reason, store=store)  # check the reason before doing any work
    if not db.is_file():
        raise BackupError(f"No database at {db} yet, so there's nothing to back up.")
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BackupError(f"Can't create the backup folder {folder}: {_why(exc)}") from None
    try:
        handle, name = tempfile.mkstemp(prefix=".snapshot-", suffix=".tmp", dir=db.parent)
    except OSError as exc:
        raise BackupError(f"Can't write a snapshot in {db.parent}: {_why(exc)}") from None
    os.close(handle)
    snapshot = Path(name)
    partial: Path | None = None
    try:
        _snapshot(db, snapshot)
        target = _free_name(folder, moment, reason, store)
        partial = target.with_name(target.name + ".partial")
        shutil.copyfile(snapshot, partial)
        os.replace(partial, target)
        partial = None
    except OSError as exc:
        raise BackupError(f"Can't write the backup to {folder}: {_why(exc)}") from None
    finally:
        snapshot.unlink(missing_ok=True)
        if partial is not None:
            partial.unlink(missing_ok=True)
    backup = parse_name(target)
    assert backup is not None
    removed = rotate(folder, keep, store) if keep is not None else ()
    return Snapshot(backup, removed)


def _snapshot(db: Path, out: Path) -> None:
    """``VACUUM INTO`` a checked copy of ``db`` at ``out`` (an empty file)."""
    try:
        with closing(connection.connect(db, mode="ro")) as conn:
            conn.execute("VACUUM INTO ?", (str(out),))
        with closing(connection.connect(out, mode="ro")) as conn:
            result = [str(row[0]) for row in conn.execute("PRAGMA integrity_check")]
    except StorageError as exc:
        raise BackupError(str(exc)) from exc
    except sqlite3.Error as exc:
        raise BackupError(f"Can't snapshot {db}: {exc}.") from exc
    if result != ["ok"]:
        raise BackupError(
            "The snapshot failed its integrity check, so it wasn't saved: "
            + "; ".join(result[:3])
            + ". Run blunderbook doctor."
        )


def _free_name(folder: Path, moment: datetime, reason: str | None, store: Store) -> Path:
    """The backup's path. Two backups in the same second get the next second, so neither
    replaces the other and the names still sort in the order they were taken."""
    while True:
        target = folder / file_name(moment, reason, store=store)
        if not target.exists() and not target.with_name(target.name + ".partial").exists():
            return target
        moment += timedelta(seconds=1)


def rotate(folder: Path, keep: int, store: Store = CORE) -> tuple[Path, ...]:
    """Delete ``store``'s oldest backups beyond the newest ``keep``. Only files with its
    generated names count. A file that can't be deleted is left for next time."""
    if keep < 1:
        raise ValueError("keep must be 1 or more.")
    found = list_backups(folder, store)
    removed: list[Path] = []
    for old in found[: max(0, len(found) - keep)]:
        try:
            old.path.unlink()
        except OSError:
            continue
        removed.append(old.path)
    return tuple(removed)


def due(folder: Path, *, now: datetime | None = None, store: Store = CORE) -> bool:
    """Whether the daily backup is due: no backup yet, or the newest is over 24 hours old."""
    last = newest(folder, store)
    return last is None or _utc(now) - last.taken_at > AUTO_EVERY


def auto(
    db: Path, folder: Path, *, keep: int, now: datetime | None = None, store: Store = CORE
) -> Snapshot | None:
    """The daily backup, taken before commands that change data. None when it isn't due,
    or when there's nothing to back up yet (no database, or one with no rows)."""
    if not db.is_file() or not due(folder, now=now, store=store) or not _has_rows(db):
        return None
    return take(db, folder, keep=keep, now=now, store=store)


def _has_rows(db: Path) -> bool:
    try:
        with closing(connection.connect(db, mode="ro")) as conn:
            return connection.has_rows(conn)
    except StorageError as exc:
        raise BackupError(str(exc)) from exc
    except sqlite3.Error as exc:
        raise BackupError(f"Can't read {db}: {exc}.") from exc


# ---------------------------------------------------------------- restore


def check_file(path: Path, store: Store = CORE) -> int:
    """Check a file before restoring it: it's a SQLite file that passes its integrity
    check, holds a ``store`` database (its tables are the ones that store's migrations make,
    so another database's backup is refused), and isn't from a newer version. Returns its
    schema version."""
    if not path.is_file():
        raise BackupError(f"No file at {path}.")
    try:
        result = connection.check(path, store)
    except StorageError as exc:
        raise BackupError(str(exc)) from exc
    database = "the Blunderbook database" if store is CORE else f"{store.label}'s database"
    not_ours = f"{path} isn't a backup of {database}."
    tables = _tables(path)
    if result.problems:
        # Another database's backup with a higher schema number would read as "newer":
        # one that shares no table with this database is simply not its backup.
        latest = connection.latest_version(store)
        ours = connection.schema_tables(store, latest)
        foreign = tables is not None and bool(tables) and not tables & ours
        if result.version > latest and foreign:
            raise BackupError(not_ours)
        raise BackupError(" ".join(result.problems))
    if result.version == 0:
        what = "Blunderbook data" if store is CORE else f"data of {store.label}"
        raise BackupError(f"{path} has no {what} in it.")
    if tables is None:
        raise BackupError(f"Can't read {path}.")
    if tables != connection.schema_tables(store, result.version):
        raise BackupError(not_ours)
    return result.version


def _tables(path: Path) -> set[str] | None:
    """The tables in the file at ``path``, or None when it can't be read."""
    try:
        with closing(connection.connect(path, mode="ro")) as conn:
            return connection.table_names(conn)
    except StorageError, sqlite3.Error:
        return None


def restore(
    file: Path, db: Path, folder: Path, *, now: datetime | None = None, store: Store = CORE
) -> Restored:
    """Replace the database with the backup ``file``.

    The file is checked first. The current database, when it has data, is backed up to
    ``folder`` with the reason ``pre-restore`` (without rotation). Then the file is copied
    in with SQLite's backup API, never by replacing the file (a stale ``-wal`` would
    corrupt it), and migrated. If any step before the copy fails, nothing is changed."""
    version = check_file(file, store)
    if db.exists() and os.path.samefile(file, db):
        raise BackupError(f"{file} is the database itself. Pick a backup file.")
    safety: Backup | None = None
    if db.exists():
        try:
            if _has_rows(db):
                safety = take(
                    db, folder, keep=None, reason="pre-restore", now=now, store=store
                ).backup
        except BackupError as exc:
            raise BackupError(
                f"Can't back up your current database first, so nothing was changed: {exc}\n"
                f"If it's damaged, move {db} out of the way, with any -wal and -shm files "
                "next to it, then restore again."
            ) from exc
    try:
        db.parent.mkdir(parents=True, exist_ok=True)
        with (
            closing(connection.connect(file, mode="ro")) as source,
            closing(connection.connect(db, mode="rwc")) as target,
        ):
            source.backup(target)
            upgraded = connection.migrate(target, store=store)
    except StorageError as exc:
        raise BackupError(str(exc)) from exc
    except sqlite3.Error as exc:
        raise BackupError(f"Can't copy {file} in: {exc}. Your database wasn't changed.") from exc
    except OSError as exc:
        raise BackupError(f"Can't create {db.parent}: {_why(exc)}") from None
    return Restored(safety, version, tuple(upgraded))


# ---------------------------------------------------------------- helpers


def _utc(moment: datetime | None) -> datetime:
    if moment is None:
        return datetime.now(UTC)
    if moment.tzinfo is None:
        raise ValueError("Backup times need a timezone.")
    return moment.astimezone(UTC)


def _why(exc: OSError) -> str:
    return exc.strerror or str(exc)
