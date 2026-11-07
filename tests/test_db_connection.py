"""db/connection.py: opening, PRAGMAs, the migration runner and the read-only check."""

import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import pytest

from blunderbook.db import connection
from blunderbook.db.connection import StorageError

CLAUDE_MD = Path(__file__).parent.parent / "CLAUDE.md"
TABLES = {"games", "blunders", "retest_attempts", "sync_state", "explanations", "imports"}


def tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_schema WHERE type = 'table'").fetchall()
    return {row[0] for row in rows}


def schema(path: Path) -> list[tuple[str, str]]:
    with closing(sqlite3.connect(path)) as conn:
        return conn.execute("SELECT name, sql FROM sqlite_schema ORDER BY name").fetchall()


def raw_db(path: Path, *sql: str) -> None:
    """A SQLite file made without Blunderbook."""
    with closing(sqlite3.connect(path, autocommit=True)) as conn:
        for statement in sql:
            conn.execute(statement)


def write_migrations(folder: Path, files: dict[str, str]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for name, sql in files.items():
        (folder / name).write_text(sql, "utf-8")
    return folder


# ---------------------------------------------------------------- the real schema


def test_migrations_shipped_with_the_app() -> None:
    migrations = connection.load_migrations()
    assert [(m.number, m.name) for m in migrations] == [
        (1, "0001_init.sql"),
        (2, "0002_explanations.sql"),
        (3, "0003_imports.sql"),
    ]
    assert connection.latest_version() == 3
    for migration in migrations:
        assert not re.search(r"^\s*(BEGIN|COMMIT)\b", migration.sql, re.I | re.M)


def test_open_db_creates_the_schema(tmp_path: Path) -> None:
    path = tmp_path / "new folder" / "blunderbook.db"
    with closing(connection.open_db(path, create=True)) as conn:
        assert tables(conn) == TABLES  # no settings table (CLAUDE.md §5)
        assert connection.user_version(conn) == connection.latest_version()
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert not conn.in_transaction
        row = conn.execute("SELECT 1 AS one").fetchone()
        assert row["one"] == 1  # sqlite3.Row


def test_schema_matches_claude_md() -> None:
    """CLAUDE.md §5 describes the current schema: same tables, same columns."""
    text = CLAUDE_MD.read_text("utf-8")
    section = text[text.index("## 5. Data model") : text.index("## 6. Configuration")]
    spec_sql = re.search(r"```sql\n(.*?)```", section, re.S)
    assert spec_sql is not None
    with (
        closing(sqlite3.connect(":memory:")) as spec,
        closing(sqlite3.connect(":memory:", autocommit=True)) as app,
    ):
        spec.executescript(spec_sql[1])
        connection.migrate(app)
        assert tables(spec) == tables(app) == TABLES
        for table in TABLES:
            info = f"PRAGMA table_info({table})"
            assert spec.execute(info).fetchall() == app.execute(info).fetchall(), table
        indexes = "SELECT name FROM sqlite_schema WHERE type = 'index' AND sql IS NOT NULL"
        assert spec.execute(indexes).fetchall() == app.execute(indexes).fetchall()


def test_migrating_twice_is_a_no_op(tmp_path: Path) -> None:
    path = tmp_path / "blunderbook.db"
    with closing(connection.open_db(path, create=True)):
        pass
    before = schema(path)
    with closing(connection.open_db(path)) as conn:
        assert connection.migrate(conn) == []
        assert connection.user_version(conn) == connection.latest_version()
    assert schema(path) == before


def test_foreign_keys_and_checks_are_enforced(tmp_path: Path) -> None:
    with closing(connection.open_db(tmp_path / "b.db", create=True)) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            conn.execute(
                "INSERT INTO retest_attempts (blunder_id, attempted_at, solved) "
                "VALUES (99, '2026-11-05T00:00:00Z', 0)"
            )
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            conn.execute(
                "INSERT INTO games (fingerprint, source, my_color, start_fen, pgn, imported_at) "
                "VALUES ('x', 'chess24', 'white', 'fen', 'pgn', 'now')"
            )


def test_deleting_a_game_deletes_its_blunders(tmp_path: Path) -> None:
    with closing(connection.open_db(tmp_path / "b.db", create=True)) as conn:
        conn.execute(
            "INSERT INTO games (id, fingerprint, source, my_color, start_fen, pgn, imported_at) "
            "VALUES (1, 'x', 'pgn', 'white', 'fen', 'pgn', 'now')"
        )
        conn.execute(
            "INSERT INTO blunders (id, game_id, ply, move_no, fen_before, played_uci, "
            "played_san, best_uci, best_san, best_line_san, accept_uci, eval_before, "
            "eval_after, swing, judgment, due_on, created_at, updated_at) VALUES (1, 1, 10, 6, "
            "'fen', 'c3d5', 'Nxd5', 'e2e3', 'e3', '6. e3', '[]', '{}', '{}', 0.3, 'blunder', "
            "'2026-11-05', 'now', 'now')"
        )
        conn.execute(
            "INSERT INTO retest_attempts (blunder_id, attempted_at, solved) VALUES (1, 'now', 1)"
        )
        conn.execute("DELETE FROM games WHERE id = 1")
        assert conn.execute("SELECT count(*) FROM blunders").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM retest_attempts").fetchone()[0] == 0


# ---------------------------------------------------------------- refusing to open


def test_missing_database_is_never_created_without_asking(tmp_path: Path) -> None:
    path = tmp_path / "missing" / "blunderbook.db"
    with pytest.raises(StorageError, match="Run: blunderbook init"):
        connection.open_db(path)
    assert not path.parent.exists()


def test_newer_database_is_refused_and_left_alone(tmp_path: Path) -> None:
    path = tmp_path / "blunderbook.db"
    raw_db(path, "CREATE TABLE future (x)", "PRAGMA user_version = 7")
    before = schema(path)
    with pytest.raises(StorageError, match=r"newer Blunderbook \(schema 7; this version knows up"):
        connection.open_db(path)
    assert schema(path) == before
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"  # not switched to WAL
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 7


def test_sqlite_file_from_another_app_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "notes.db"
    raw_db(path, "CREATE TABLE notes (body TEXT)")
    with pytest.raises(StorageError, match="isn't a Blunderbook database"):
        connection.open_db(path, create=True)
    assert [name for name, _ in schema(path)] == ["notes"]


def test_file_that_isnt_sqlite(tmp_path: Path) -> None:
    path = tmp_path / "blunderbook.db"
    path.write_bytes(b"not a database " * 100)
    with pytest.raises(StorageError, match="isn't a SQLite database"):
        connection.open_db(path)
    assert path.read_bytes() == b"not a database " * 100


def test_empty_file_is_set_up(tmp_path: Path) -> None:
    path = tmp_path / "blunderbook.db"
    path.write_bytes(b"")
    with closing(connection.open_db(path)) as conn:
        assert tables(conn) == TABLES


# ---------------------------------------------------------------- the runner


def test_upgrade_applies_only_the_newer_migrations(tmp_path: Path) -> None:
    folder = write_migrations(tmp_path / "m", {"0001_a.sql": "CREATE TABLE a (x);"})
    with closing(connection.connect(tmp_path / "x.db", mode="rwc")) as conn:
        assert connection.migrate(conn, connection.load_migrations(folder)) == [1]
        write_migrations(folder, {"0002_b.sql": "CREATE TABLE b (x);\nINSERT INTO a VALUES (1);"})
        assert connection.migrate(conn, connection.load_migrations(folder)) == [2]
        assert connection.migrate(conn, connection.load_migrations(folder)) == []
        assert connection.user_version(conn) == 2
        assert conn.execute("SELECT count(*) FROM a").fetchone()[0] == 1


def test_a_failed_migration_changes_nothing(tmp_path: Path) -> None:
    folder = write_migrations(
        tmp_path / "m",
        {
            "0001_a.sql": "CREATE TABLE a (x);",
            "0002_b.sql": "CREATE TABLE b (x);\nINSERT INTO a VALUES (1);\n"
            "INSERT INTO nope VALUES (1);",
        },
    )
    with closing(connection.connect(tmp_path / "x.db", mode="rwc")) as conn:
        with pytest.raises(StorageError, match=r"Couldn't upgrade the database \(0002_b\.sql\)"):
            connection.migrate(conn, connection.load_migrations(folder))
        assert connection.user_version(conn) == 1
        assert tables(conn) == {"a"}
        assert conn.execute("SELECT count(*) FROM a").fetchone()[0] == 0
        assert not conn.in_transaction


@pytest.mark.parametrize(
    "names",
    [
        ["0001_a.sql", "0003_c.sql"],  # gap
        ["0002_b.sql"],  # doesn't start at 1
        ["0001_a.sql", "0001_b.sql"],  # same number twice
    ],
)
def test_migration_numbers_must_run_1_2_3(tmp_path: Path, names: list[str]) -> None:
    folder = write_migrations(tmp_path / "m", dict.fromkeys(names, "SELECT 1;"))
    with pytest.raises(RuntimeError, match="no gaps"):
        connection.load_migrations(folder)


@pytest.mark.parametrize("name", ["1_a.sql", "0001-a.sql", "0001_Init.sql", "0001.sql"])
def test_migration_names_are_checked(tmp_path: Path, name: str) -> None:
    folder = write_migrations(tmp_path / "m", {name: "SELECT 1;"})
    with pytest.raises(RuntimeError, match=r"look like 0001_name\.sql"):
        connection.load_migrations(folder)


def test_other_files_in_the_folder_are_ignored(tmp_path: Path) -> None:
    folder = write_migrations(tmp_path / "m", {"0001_a.sql": "SELECT 1;", "notes.txt": "hi"})
    assert [m.name for m in connection.load_migrations(folder)] == ["0001_a.sql"]


def test_transaction_commits_or_rolls_back(tmp_path: Path) -> None:
    with closing(connection.open_db(tmp_path / "b.db", create=True)) as conn:
        insert = "INSERT INTO sync_state (source, username) VALUES (?, ?)"
        with connection.transaction(conn):
            conn.execute(insert, ("lichess", "rashed"))
        with pytest.raises(ZeroDivisionError), connection.transaction(conn):
            conn.execute(insert, ("chesscom", "rashed"))
            _ = 1 / 0
        rows = conn.execute("SELECT source FROM sync_state").fetchall()
        assert [row["source"] for row in rows] == ["lichess"]
        assert not conn.in_transaction


# ---------------------------------------------------------------- check (doctor)


def test_check_a_healthy_database(tmp_path: Path) -> None:
    path = tmp_path / "blunderbook.db"
    with closing(connection.open_db(path, create=True)):
        pass
    latest = connection.latest_version()
    assert connection.check(path) == connection.DbCheck(latest, latest, ())


def test_check_changes_nothing(tmp_path: Path) -> None:
    path = tmp_path / "blunderbook.db"
    path.write_bytes(b"")
    result = connection.check(path)
    assert (result.version, result.problems) == (0, ())
    assert path.read_bytes() == b""
    with pytest.raises(StorageError, match="No database at"):
        connection.check(tmp_path / "missing.db")
    assert not (tmp_path / "missing.db").exists()


def test_check_reports_a_newer_or_foreign_database(tmp_path: Path) -> None:
    newer, foreign = tmp_path / "newer.db", tmp_path / "foreign.db"
    raw_db(newer, "PRAGMA user_version = 9")
    raw_db(foreign, "CREATE TABLE notes (body TEXT)")
    (problem,) = connection.check(newer).problems
    assert "newer Blunderbook (schema 9;" in problem
    (problem,) = connection.check(foreign).problems
    assert "isn't a Blunderbook database" in problem


def test_check_reports_damage(tmp_path: Path) -> None:
    """Rewrite an index's definition behind SQLite's back: the stored entries no longer match
    it, which integrity_check reports while the file still opens."""
    path = tmp_path / "blunderbook.db"
    raw_db(
        path,
        "CREATE TABLE t (x INTEGER)",
        "CREATE INDEX t_x ON t (x)",
        "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 2000) "
        "INSERT INTO t SELECT i FROM n",
        "PRAGMA writable_schema = ON",
        "UPDATE sqlite_schema SET sql = 'CREATE INDEX t_x ON t (x DESC)' WHERE name = 't_x'",
        "PRAGMA user_version = 1",
    )
    (problem,) = connection.check(path).problems
    assert problem.startswith("The integrity check found damage: ")


def test_transaction_needs_autocommit() -> None:
    legacy = sqlite3.connect(":memory:")  # Python's legacy transaction mode
    with closing(legacy), pytest.raises(ValueError, match="autocommit"):
        connection.migrate(legacy)


def test_any_thread_lets_another_thread_use_the_connection(db_file: Path) -> None:
    """The API needs it: FastAPI may open, use and close a request's connection on
    different worker threads."""
    with closing(connection.open_db(db_file, create=True)):
        pass
    query = "SELECT count(*) FROM games"
    with (
        closing(connection.connect(db_file, any_thread=True)) as shared,
        closing(connection.connect(db_file)) as plain,
        ThreadPoolExecutor(1) as pool,
    ):
        assert pool.submit(lambda: shared.execute(query).fetchone()[0]).result() == 0
        with pytest.raises(sqlite3.ProgrammingError):
            pool.submit(lambda: plain.execute(query)).result()


def test_a_v1_database_with_data_is_upgraded_after_a_safety_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 0002 upgrade a v1 user gets: the hook (the -pre-migrate backup) runs first, the
    explanations table arrives, and the data stays."""
    path = tmp_path / "blunderbook.db"
    first = connection.load_migrations()[:1]
    with monkeypatch.context() as patch:
        patch.setattr(connection, "load_migrations", lambda *_: first)
        with closing(connection.open_db(path, create=True)) as conn:
            assert connection.user_version(conn) == 1
            conn.execute("INSERT INTO sync_state (source, username) VALUES ('lichess', 'rashed')")

    calls: list[int] = []
    with closing(connection.open_db(path, before_migrate=lambda: calls.append(1))) as conn:
        assert calls == [1]
        assert connection.user_version(conn) == connection.latest_version()
        assert "explanations" in tables(conn)
        assert conn.execute("SELECT username FROM sync_state").fetchone()[0] == "rashed"


def test_a_v2_database_keeps_its_games_with_no_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 0003 upgrade: imports arrive, games already saved have none (the Games tab groups
    them by the day they were imported), and the -pre-migrate hook runs first."""
    path = tmp_path / "blunderbook.db"
    first_two = connection.load_migrations()[:2]
    with monkeypatch.context() as patch:
        patch.setattr(connection, "load_migrations", lambda *_: first_two)
        with closing(connection.open_db(path, create=True)) as conn:
            conn.execute(
                "INSERT INTO games (fingerprint, source, my_color, start_fen, pgn, imported_at) "
                "VALUES ('fp', 'pgn', 'white', 'x', '1. e4 *', '2026-11-05T09:30:00+00:00')"
            )
    calls: list[int] = []
    with closing(connection.open_db(path, before_migrate=lambda: calls.append(1))) as conn:
        assert calls == [1]
        assert connection.user_version(conn) == 3
        assert "imports" in tables(conn)
        row = conn.execute("SELECT fingerprint, import_id FROM games").fetchone()
        assert tuple(row) == ("fp", None)
