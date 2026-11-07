"""SQLite connections, PRAGMAs and the forward-only migration runner (CLAUDE.md §5).

Each database Blunderbook looks after is a :class:`Store`: the core one (``CORE``), or an
extension's own (CLAUDE.md §15), with its own migrations. Everything defaults to ``CORE``.

Connections use SQLite's own autocommit mode (``autocommit=True``). Python never opens a
transaction behind your back, so PRAGMAs such as ``foreign_keys`` take effect (SQLite
ignores them inside a transaction). Writes that belong together go in ``transaction()``.

Maintenance SQL only. Data SQL lives in repo.py.
"""

import re
import sqlite3
from collections.abc import Callable, Iterator, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Literal

MIGRATIONS: Traversable = files("blunderbook.db") / "migrations"
_MIGRATION_NAME = re.compile(r"(\d{4})_[a-z0-9_]+\.sql")

Mode = Literal["ro", "rw", "rwc"]  # read only · read and write · read, write and create


class StorageError(Exception):
    """A database problem, with a message ready to show."""


@dataclass(frozen=True, slots=True)
class Store:
    """A database: the core one, or an extension's own."""

    name: str  # "blunderbook", or the extension's name; also its backups' prefix
    label: str  # for messages: "Blunderbook", "the library extension"
    migrations: Traversable


CORE = Store("blunderbook", "Blunderbook", MIGRATIONS)


@dataclass(frozen=True, slots=True)
class Migration:
    number: int
    name: str
    sql: str


@dataclass(frozen=True, slots=True)
class DbCheck:
    """What ``check()`` found. ``problems`` are full sentences; empty means healthy."""

    version: int
    latest: int
    problems: tuple[str, ...]


# ---------------------------------------------------------------- migrations


def load_migrations(folder: Traversable = MIGRATIONS) -> tuple[Migration, ...]:
    """The ``NNNN_name.sql`` files in ``folder``, numbered 1, 2, 3... with no gaps."""
    found: list[Migration] = []
    for item in folder.iterdir():
        if not item.name.endswith(".sql"):
            continue
        match = _MIGRATION_NAME.fullmatch(item.name)
        if match is None:
            raise RuntimeError(f"Migration names look like 0001_name.sql, not {item.name}.")
        found.append(Migration(int(match[1]), item.name, item.read_text("utf-8")))
    found.sort(key=lambda m: (m.number, m.name))
    if [m.number for m in found] != list(range(1, len(found) + 1)):
        names = ", ".join(m.name for m in found)
        raise RuntimeError(f"Migrations must be numbered 1, 2, 3... with no gaps: {names}.")
    return tuple(found)


def store_migrations(store: Store = CORE) -> tuple[Migration, ...]:
    """The migrations of ``store``."""
    return load_migrations() if store is CORE else load_migrations(store.migrations)


def latest_version(store: Store = CORE) -> int:
    """The schema version this app brings a database up to."""
    return len(store_migrations(store))


def schema_tables(store: Store, version: int) -> set[str]:
    """The tables a ``store`` database has at schema ``version``: its first ``version``
    migrations, run on an empty database in memory."""
    with closing(sqlite3.connect(":memory:", autocommit=True)) as conn:
        migrate(conn, store_migrations(store)[:version], store=store)
        return table_names(conn)


def table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_schema WHERE type = 'table' "
        "AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\'"
    ).fetchall()
    return {str(row[0]) for row in rows}


def migrate(
    conn: sqlite3.Connection,
    migrations: Sequence[Migration] | None = None,
    *,
    store: Store = CORE,
) -> list[int]:
    """Apply the migrations newer than the database's ``user_version``, each in its own
    transaction together with the version bump. Returns the numbers applied (none when the
    database is up to date). Refuses a database from a newer Blunderbook, and a SQLite file
    that has tables but was never set up by Blunderbook."""
    known = store_migrations(store) if migrations is None else tuple(migrations)
    latest = len(known)
    current = user_version(conn)
    _check_ours(conn, current, latest, store)
    applied: list[int] = []
    for migration in known[current:]:
        try:
            with transaction(conn):
                if user_version(conn) >= migration.number:
                    continue  # another process got there first
                conn.executescript(migration.sql)
                # PRAGMA takes no parameters; the number comes from our own file name.
                conn.execute(f"PRAGMA user_version = {migration.number:d}")
        except sqlite3.Error as exc:
            raise StorageError(
                f"Couldn't upgrade the database ({migration.name}): {exc}. Nothing was changed "
                "by this step."
            ) from exc
        applied.append(migration.number)
    return applied


def _check_ours(conn: sqlite3.Connection, version: int, latest: int, store: Store) -> None:
    problem = _version_problem(conn, version, latest, store)
    if problem is not None:
        raise StorageError(problem)


def _version_problem(
    conn: sqlite3.Connection, version: int, latest: int, store: Store = CORE
) -> str | None:
    if version > latest:
        if store is CORE:
            return (
                f"The database was made by a newer Blunderbook (schema {version}; this "
                f"version knows up to {latest}). Update Blunderbook to use it."
            )
        return (
            f"The database was made by a newer version of {store.label} (schema {version}; "
            f"this one knows up to {latest}). Update the extension to use it."
        )
    if version == 0 and _has_tables(conn):
        what = "a Blunderbook database" if store is CORE else f"a database of {store.label}"
        return f"This SQLite file isn't {what}: it has tables but no schema version."
    return None


def _has_tables(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_schema WHERE name NOT LIKE 'sqlite\\_%' ESCAPE '\\' LIMIT 1"
    ).fetchone()
    return row is not None


def has_rows(conn: sqlite3.Connection) -> bool:
    """Whether any table holds a row, whatever the schema version."""
    tables = conn.execute(
        "SELECT name FROM sqlite_schema WHERE type = 'table' "
        "AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\'"
    ).fetchall()
    for (name,) in tables:
        quoted = '"' + str(name).replace('"', '""') + '"'  # a name from the schema itself
        if conn.execute(f"SELECT 1 FROM {quoted} LIMIT 1").fetchone() is not None:
            return True
    return False


# ---------------------------------------------------------------- connections


def connect(path: Path, *, mode: Mode = "rw", any_thread: bool = False) -> sqlite3.Connection:
    """Open ``path`` with foreign keys on and rows as ``sqlite3.Row``. Never creates the file
    unless ``mode`` is ``"rwc"``. Doesn't migrate: see ``open_db``.

    ``any_thread`` lets another thread use the connection, one thread at a time. The API
    needs it: FastAPI may open, use and close a request's connection on different worker
    threads."""
    uri = f"{path.resolve().as_uri()}?mode={mode}"
    try:
        conn = sqlite3.connect(uri, uri=True, autocommit=True, check_same_thread=not any_thread)
    except sqlite3.Error as exc:
        raise _open_error(path, exc) from exc
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA schema_version").fetchone()  # reads the file: fails if it isn't SQLite
    except sqlite3.Error as exc:
        conn.close()
        raise _open_error(path, exc) from exc
    return conn


def open_db(
    path: Path,
    *,
    create: bool = False,
    before_migrate: Callable[[], object] | None = None,
    store: Store = CORE,
) -> sqlite3.Connection:
    """Open the database for use: check it's ours and not from a newer Blunderbook, switch it
    to WAL, and bring it up to date. With ``create``, a missing file (and folder) is made.

    ``before_migrate`` runs when the database has data and needs upgrading, before anything
    changes (the CLI takes a ``-pre-migrate`` backup there). If it raises, nothing is
    migrated. Close the connection with ``contextlib.closing``."""
    if not path.exists():
        if not create:
            raise StorageError(f"No database at {path} yet. Run: blunderbook init")
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path, mode="rwc" if create else "rw")
    try:
        version, latest = user_version(conn), latest_version(store)
        _check_ours(conn, version, latest, store)
        conn.execute("PRAGMA journal_mode = WAL")
        if before_migrate is not None and version < latest and has_rows(conn):
            before_migrate()
        migrate(conn, store=store)
    except sqlite3.Error as exc:
        conn.close()
        raise _open_error(path, exc) from exc
    except BaseException:
        conn.close()
        raise
    return conn


def check(path: Path, store: Store = CORE) -> DbCheck:
    """Look at the database without changing it: its schema version and
    ``PRAGMA integrity_check``. Raises ``StorageError`` if it can't be opened."""
    if not path.exists():
        raise StorageError(f"No database at {path} yet. Run: blunderbook init")
    latest = latest_version(store)
    with closing(connect(path, mode="ro")) as conn:
        try:
            version = user_version(conn)
            problems: list[str] = []
            if (problem := _version_problem(conn, version, latest, store)) is not None:
                problems.append(problem)
            errors = [str(row[0]) for row in conn.execute("PRAGMA integrity_check")]
        except sqlite3.Error as exc:
            raise _open_error(path, exc) from exc
    if errors != ["ok"]:
        problems.append("The integrity check found damage: " + "; ".join(errors[:3]))
    return DbCheck(version, latest, tuple(problems))


def user_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """``BEGIN IMMEDIATE`` ... ``COMMIT``, or ``ROLLBACK`` if the block raises.

    Needs a connection in SQLite's autocommit mode, as ``connect()`` makes. In Python's
    legacy mode, ``executescript`` would commit half a migration on its own."""
    if conn.autocommit is not True:
        raise ValueError("transaction() needs a connection opened with autocommit=True.")
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        if conn.in_transaction:  # some errors make SQLite roll back by itself
            conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def _open_error(path: Path, exc: sqlite3.Error) -> StorageError:
    if getattr(exc, "sqlite_errorname", None) == "SQLITE_NOTADB":
        return StorageError(f"{path} isn't a SQLite database.")
    return StorageError(f"Can't open {path}: {exc}.")
