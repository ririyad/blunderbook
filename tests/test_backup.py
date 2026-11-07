"""db/backup.py: snapshots, names, rotation, the daily backup and restore, plus the
pre-migrate hook in connection.open_db. Real temp databases, no engine."""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import chess
import pytest
from conftest import LATEST, with_next_migration

from blunderbook.core.models import NewGame
from blunderbook.db import backup, connection, repo
from blunderbook.db.backup import BackupError

NOW = datetime(2026, 11, 5, 10, 15, 0, tzinfo=UTC)
NAME = "blunderbook-2026-11-05_101500Z.db"


def new_game(fingerprint: str) -> NewGame:
    return NewGame(
        fingerprint=fingerprint,
        source="pgn",
        my_color="white",
        start_fen=chess.STARTING_FEN,
        pgn="1. e4 e5 *",
        engine_name="Stockfish 17.1",
        engine_depth=16,
    )


def add_game(db: Path, fingerprint: str) -> None:
    with closing(connection.open_db(db, create=True)) as conn:
        repo.add_game(conn, new_game(fingerprint), now=NOW)


def fingerprints(db: Path) -> set[str]:
    with closing(connection.connect(db, mode="ro")) as conn:
        return repo.known_fingerprints(conn)


@pytest.fixture
def db(db_file: Path) -> Path:
    """The live database, with one game in it."""
    add_game(db_file, "first")
    return db_file


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    return tmp_path / "backups"


def touch(folder: Path, *names: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_bytes(b"")


def names(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir())


# ---------------------------------------------------------------- names


def test_file_names() -> None:
    assert backup.file_name(NOW) == NAME
    assert backup.file_name(NOW, "pre-restore") == "blunderbook-2026-11-05_101500Z-pre-restore.db"
    dhaka = NOW.astimezone(datetime.now().astimezone().tzinfo)
    assert backup.file_name(dhaka) == NAME  # always UTC
    with pytest.raises(ValueError, match="reason"):
        backup.file_name(NOW, "Pre Restore")
    with pytest.raises(ValueError, match="timezone"):
        backup.file_name(datetime(2026, 11, 5, 10, 15))


@pytest.mark.parametrize(
    ("name", "reason"),
    [(NAME, None), ("blunderbook-2026-11-05_101500Z-pre-migrate.db", "pre-migrate")],
)
def test_parse_name(name: str, reason: str | None) -> None:
    found = backup.parse_name(Path(name))
    assert found is not None
    assert (found.taken_at, found.reason) == (NOW, reason)


@pytest.mark.parametrize(
    "name",
    [
        "blunderbook.db",
        "blunderbook-2026-11-05.db",
        "blunderbook-2026-11-05_101500Z.db.partial",
        "blunderbook-2026-13-05_101500Z.db",  # month 13
        "blunderbook-2026-11-05_101500Z-Mine.db",
        "my-blunderbook-2026-11-05_101500Z.db",
        "blunderbook-2026-11-05_101500Z.db.bak",
    ],
)
def test_other_names_arent_backups(name: str) -> None:
    assert backup.parse_name(Path(name)) is None


def test_list_backups_oldest_first_and_ignores_other_files(folder: Path) -> None:
    touch(
        folder,
        "blunderbook-2026-11-05_101500Z.db",
        "blunderbook-2026-11-04_230000Z-pre-migrate.db",
        "blunderbook-2026-11-06_000000Z.db.partial",
        "notes.txt",
        "blunderbook.db",
    )
    (folder / "blunderbook-2026-01-01_000000Z.db").mkdir()  # a folder, not a backup
    found = backup.list_backups(folder)
    assert [b.path.name for b in found] == [
        "blunderbook-2026-11-04_230000Z-pre-migrate.db",
        "blunderbook-2026-11-05_101500Z.db",
    ]
    assert backup.newest(folder) == found[-1]
    assert backup.list_backups(folder / "missing") == []
    assert backup.newest(folder / "missing") is None


# ---------------------------------------------------------------- take


def test_take_writes_a_checked_snapshot(db: Path, folder: Path) -> None:
    snapshot = backup.take(db, folder, keep=14, now=NOW)
    assert snapshot.backup.path == folder / NAME
    assert snapshot.backup.taken_at == NOW
    assert snapshot.removed == ()
    assert names(folder) == [NAME]  # no .partial left behind
    assert fingerprints(folder / NAME) == {"first"}
    assert connection.check(folder / NAME).problems == ()
    leftovers = [p.name for p in db.parent.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []  # the temp snapshot next to the database is gone


def test_take_includes_changes_still_in_the_wal(db: Path, folder: Path) -> None:
    """A file copy would miss them; VACUUM INTO doesn't."""
    with closing(connection.open_db(db)) as conn:
        conn.execute("PRAGMA wal_autocheckpoint = 0")
        repo.add_game(conn, new_game("in-wal"), now=NOW)
        assert Path(f"{db}-wal").stat().st_size > 0
        backup.take(db, folder, keep=14, now=NOW)  # while this connection is still open
    assert fingerprints(folder / NAME) == {"first", "in-wal"}


def test_take_with_a_reason(db: Path, folder: Path) -> None:
    snapshot = backup.take(db, folder, keep=None, reason="pre-migrate", now=NOW)
    assert snapshot.backup.path.name == "blunderbook-2026-11-05_101500Z-pre-migrate.db"
    assert snapshot.backup.reason == "pre-migrate"


def test_two_backups_in_the_same_second_both_stay(db: Path, folder: Path) -> None:
    first = backup.take(db, folder, keep=14, now=NOW)
    second = backup.take(db, folder, keep=14, now=NOW)
    assert first.backup.path.name == NAME
    assert second.backup.path.name == "blunderbook-2026-11-05_101501Z.db"


def test_take_without_a_database(tmp_path: Path, folder: Path) -> None:
    with pytest.raises(BackupError, match=r"No database at .* nothing to back up"):
        backup.take(tmp_path / "missing.db", folder, keep=14, now=NOW)
    assert not folder.exists()


def test_take_refuses_a_file_that_isnt_a_database(db_file: Path, folder: Path) -> None:
    db_file.parent.mkdir(parents=True)
    db_file.write_bytes(b"x" * 4096)
    touch(folder, NAME)
    with pytest.raises(BackupError, match="isn't a SQLite database"):
        backup.take(db_file, folder, keep=1, now=NOW + timedelta(days=1))
    assert names(folder) == [NAME]  # no rotation after a failed backup
    assert [p.name for p in db_file.parent.iterdir()] == ["blunderbook.db"]


def test_take_when_the_folder_cant_be_made(db: Path, tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_bytes(b"")
    with pytest.raises(BackupError, match="Can't create the backup folder"):
        backup.take(db, blocker / "backups", keep=14, now=NOW)


# ---------------------------------------------------------------- rotation


def test_rotation_keeps_the_newest_and_never_touches_other_files(db: Path, folder: Path) -> None:
    others = [
        "notes.txt",
        "blunderbook.db",
        "blunderbook-mine.db",
        "blunderbook-2020-01-01_000000Z.db.partial",
        "blunderbook-2020-01-01_000000Z-Mine.db",
    ]
    touch(
        folder,
        *others,
        "blunderbook-2026-11-01_090000Z.db",
        "blunderbook-2026-11-02_090000Z-pre-migrate.db",
        "blunderbook-2026-11-03_090000Z.db",
    )
    snapshot = backup.take(db, folder, keep=2, now=NOW)
    assert [p.name for p in snapshot.removed] == [
        "blunderbook-2026-11-01_090000Z.db",
        "blunderbook-2026-11-02_090000Z-pre-migrate.db",
    ]
    assert names(folder) == sorted([*others, "blunderbook-2026-11-03_090000Z.db", NAME])


def test_keep_none_skips_rotation(db: Path, folder: Path) -> None:
    touch(folder, "blunderbook-2026-11-01_090000Z.db", "blunderbook-2026-11-02_090000Z.db")
    assert backup.take(db, folder, keep=None, now=NOW).removed == ()
    assert len(backup.list_backups(folder)) == 3


def test_keep_must_be_one_or_more(db: Path, folder: Path) -> None:
    with pytest.raises(ValueError, match="keep"):
        backup.take(db, folder, keep=0, now=NOW)
    with pytest.raises(ValueError, match="keep"):
        backup.rotate(folder, 0)


# ---------------------------------------------------------------- daily backup


def test_due_reads_the_age_from_the_names(folder: Path) -> None:
    assert backup.due(folder, now=NOW)  # no folder, no backups
    touch(folder, "notes.txt")
    assert backup.due(folder, now=NOW)
    touch(folder, NAME)
    assert not backup.due(folder, now=NOW + timedelta(hours=24))
    assert backup.due(folder, now=NOW + timedelta(hours=24, seconds=1))


def test_auto_backs_up_once_a_day(db: Path, folder: Path) -> None:
    first = backup.auto(db, folder, keep=14, now=NOW)
    assert first is not None and first.backup.path.name == NAME
    assert backup.auto(db, folder, keep=14, now=NOW + timedelta(hours=23)) is None
    later = backup.auto(db, folder, keep=14, now=NOW + timedelta(hours=25))
    assert later is not None
    assert len(backup.list_backups(folder)) == 2


def test_auto_skips_a_missing_or_empty_database(db_file: Path, folder: Path) -> None:
    assert backup.auto(db_file, folder, keep=14, now=NOW) is None
    with closing(connection.open_db(db_file, create=True)):
        pass
    assert backup.auto(db_file, folder, keep=14, now=NOW) is None
    assert not folder.exists()


def test_auto_rotates(db: Path, folder: Path) -> None:
    touch(folder, "blunderbook-2026-11-01_090000Z.db", "blunderbook-2026-11-02_090000Z.db")
    snapshot = backup.auto(db, folder, keep=2, now=NOW)
    assert snapshot is not None
    assert [p.name for p in snapshot.removed] == ["blunderbook-2026-11-01_090000Z.db"]


# ---------------------------------------------------------------- restore


def test_backup_change_restore_gives_back_the_old_data(db: Path, folder: Path) -> None:
    saved = backup.take(db, folder, keep=14, now=NOW).backup.path
    add_game(db, "second")
    assert fingerprints(db) == {"first", "second"}

    result = backup.restore(saved, db, folder, now=NOW + timedelta(hours=1))

    assert fingerprints(db) == {"first"}
    assert result.version == connection.latest_version()
    assert result.upgraded == ()
    assert result.safety is not None
    assert result.safety.path.name == "blunderbook-2026-11-05_111500Z-pre-restore.db"
    assert fingerprints(result.safety.path) == {"first", "second"}
    assert connection.check(db).problems == ()
    with closing(connection.open_db(db)) as conn:  # still usable, still WAL
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_restore_doesnt_rotate_away_the_file_it_reads(db: Path, folder: Path) -> None:
    oldest = backup.take(db, folder, keep=1, now=NOW).backup.path
    add_game(db, "second")
    backup.restore(oldest, db, folder, now=NOW + timedelta(hours=1))
    assert oldest.exists()
    assert fingerprints(db) == {"first"}


def test_restore_while_the_app_is_reading(db: Path, folder: Path) -> None:
    saved = backup.take(db, folder, keep=14, now=NOW).backup.path
    add_game(db, "second")
    with closing(connection.open_db(db)) as reader:
        reader.execute("BEGIN")
        reader.execute("SELECT count(*) FROM games").fetchone()
        backup.restore(saved, db, folder, now=NOW + timedelta(hours=1))
        reader.execute("COMMIT")
        assert {r[0] for r in reader.execute("SELECT fingerprint FROM games")} == {"first"}


def test_restore_into_a_new_computer(db: Path, folder: Path, tmp_path: Path) -> None:
    """init, then restore: an empty or missing database needs no safety copy."""
    saved = backup.take(db, folder, keep=14, now=NOW).backup.path
    fresh = tmp_path / "new" / "blunderbook.db"
    result = backup.restore(saved, fresh, folder, now=NOW)
    assert result.safety is None
    assert fingerprints(fresh) == {"first"}

    empty = tmp_path / "empty" / "blunderbook.db"
    with closing(connection.open_db(empty, create=True)):
        pass
    assert backup.restore(saved, empty, folder, now=NOW).safety is None
    assert fingerprints(empty) == {"first"}
    assert len(backup.list_backups(folder)) == 1


def raw_db(path: Path, *statements: str) -> Path:
    with closing(sqlite3.connect(path, autocommit=True)) as conn:
        for sql in statements:
            conn.execute(sql)
    return path


def damaged(path: Path) -> Path:
    """Opens fine, fails integrity_check (an index that no longer matches its table)."""
    return raw_db(
        path,
        "CREATE TABLE t (x INTEGER)",
        "CREATE INDEX t_x ON t (x)",
        "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 2000) "
        "INSERT INTO t SELECT i FROM n",
        "PRAGMA writable_schema = ON",
        "UPDATE sqlite_schema SET sql = 'CREATE INDEX t_x ON t (x DESC)' WHERE name = 't_x'",
        "PRAGMA user_version = 1",
    )


@pytest.mark.parametrize(
    ("make", "message"),
    [
        (lambda p: p, "No file at"),
        (lambda p: p.write_bytes(b"x" * 4096) and p, "isn't a SQLite database"),
        (damaged, "The integrity check found damage"),
        (lambda p: raw_db(p, "PRAGMA user_version = 99"), "newer Blunderbook"),
        (lambda p: raw_db(p, "CREATE TABLE notes (body TEXT)"), "isn't a Blunderbook database"),
        (lambda p: raw_db(p, "VACUUM"), "has no Blunderbook data"),
    ],
    ids=["missing", "not-sqlite", "damaged", "newer", "foreign", "empty"],
)
def test_restore_refuses_a_bad_file(
    db: Path, folder: Path, tmp_path: Path, make: object, message: str
) -> None:
    bad = tmp_path / "bad.db"
    make(bad)  # type: ignore[operator]
    before = db.read_bytes()
    with pytest.raises(BackupError, match=message):
        backup.restore(bad, db, folder, now=NOW)
    assert fingerprints(db) == {"first"}
    assert db.read_bytes() == before
    assert not folder.exists()  # no safety copy either: nothing was started


def test_restore_refuses_the_database_itself(db: Path, folder: Path) -> None:
    with pytest.raises(BackupError, match="is the database itself"):
        backup.restore(db, db, folder, now=NOW)


def test_restore_stops_when_the_safety_copy_fails(db: Path, tmp_path: Path) -> None:
    saved = backup.take(db, tmp_path / "ok", keep=14, now=NOW).backup.path
    add_game(db, "second")
    blocker = tmp_path / "file"
    blocker.write_bytes(b"")
    with pytest.raises(BackupError, match="Can't back up your current database first") as err:
        backup.restore(saved, db, blocker / "backups", now=NOW)
    assert "move" in str(err.value) and "-wal" in str(err.value)
    assert fingerprints(db) == {"first", "second"}


def test_restore_upgrades_an_older_backup(
    db: Path, folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    saved = backup.take(db, folder, keep=14, now=NOW).backup.path  # the current schema
    monkeypatch.setattr(connection, "load_migrations", with_next_migration)
    result = backup.restore(saved, db, folder, now=NOW + timedelta(hours=1))
    assert (result.version, result.upgraded) == (LATEST, (LATEST + 1,))
    with closing(connection.connect(db, mode="ro")) as conn:
        assert connection.user_version(conn) == LATEST + 1


# ---------------------------------------------------------------- before_migrate


def test_has_rows(db_file: Path) -> None:
    with closing(connection.open_db(db_file, create=True)) as conn:
        assert not connection.has_rows(conn)
        conn.execute("INSERT INTO sync_state (source, username) VALUES ('lichess', 'me')")
        assert connection.has_rows(conn)


def test_open_db_calls_before_migrate_only_for_data_that_needs_upgrading(
    db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []

    def hook() -> None:
        calls.append(1)

    with closing(connection.open_db(db, before_migrate=hook)):
        pass
    assert calls == []  # up to date

    empty = tmp_path / "empty.db"
    with closing(connection.open_db(empty, create=True)):
        pass
    monkeypatch.setattr(connection, "load_migrations", with_next_migration)
    with closing(connection.open_db(empty, before_migrate=hook)):
        pass
    assert calls == []  # nothing to lose

    with closing(connection.open_db(db, before_migrate=hook)) as conn:
        assert connection.user_version(conn) == LATEST + 1
    assert calls == [1]


def test_a_failing_before_migrate_stops_the_upgrade(
    db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(connection, "load_migrations", with_next_migration)

    def hook() -> None:
        raise connection.StorageError("no backup")

    with pytest.raises(connection.StorageError, match="no backup"):
        connection.open_db(db, before_migrate=hook)
    with closing(connection.connect(db, mode="ro")) as conn:
        assert connection.user_version(conn) == LATEST
