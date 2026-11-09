"""Extension databases (CLAUDE.md §15, §6 Backups): each extension's own SQLite file and
migrations, its pre-migrate backup, and the backups, daily backup and restore that cover
it. The sample "notes" extension is in ext_samples.py."""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from importlib.metadata import EntryPoint
from pathlib import Path

import pytest
from ext_samples import NOTES_MIGRATIONS, notes
from typer.testing import CliRunner

from blunderbook import cli, config, ext, host
from blunderbook.config import BackupConfig, Config, ExtensionsConfig
from blunderbook.db import backup, connection

runner = CliRunner()
NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
NOTES = ext.store(notes)
assert NOTES is not None


@pytest.fixture(autouse=True)
def installed(monkeypatch: pytest.MonkeyPatch) -> None:
    points = [
        EntryPoint("notes", "ext_samples:notes", ext.GROUP),
        EntryPoint("sample", "ext_samples:sample", ext.GROUP),
        EntryPoint("broken", "ext_samples_broken:extension", ext.GROUP),
    ]
    monkeypatch.setattr(ext, "entry_points", lambda group: points)


@pytest.fixture
def cfg_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "home" / "config.toml"
    monkeypatch.setattr(config, "config_path", lambda: path)
    monkeypatch.delenv(config.STOCKFISH_ENV, raising=False)
    monkeypatch.setattr("shutil.which", lambda _: None)
    monkeypatch.delenv("ONEDRIVE", raising=False)
    return path


def settings(cfg_file: Path, *enabled: str, keep: int = 14, auto: bool = True) -> Config:
    cfg = Config(
        extensions=ExtensionsConfig(enabled=enabled), backup=BackupConfig(keep=keep, auto=auto)
    )
    config.save(cfg, cfg_file)
    return cfg


def folder(db_file: Path) -> Path:
    return db_file.parent / "backups"


def core_with_data(db_file: Path) -> None:
    with closing(connection.open_db(db_file, create=True)) as conn:
        conn.execute("INSERT INTO sync_state (source, username) VALUES ('lichess', 'rashed')")


def note(cfg: Config, text: str) -> None:
    with closing(ext.open_db(notes, cfg)) as conn:
        conn.execute("INSERT INTO notes (text) VALUES (?)", (text,))


def texts(db: Path) -> list[str]:
    with closing(connection.connect(db, mode="ro")) as conn:
        return [row[0] for row in conn.execute("SELECT text FROM notes ORDER BY id")]


def names(where: Path) -> list[str]:
    return sorted(p.name for p in where.iterdir()) if where.exists() else []


# ---------------------------------------------------------------- its own database


def test_store_and_path(db_file: Path) -> None:
    assert connection.Store("notes", "the notes extension", NOTES_MIGRATIONS) == NOTES
    assert ext.db_path(notes) == db_file.parent / "notes.db"
    assert ext.store(ext.Extension(name="plain", title="P", host_api=ext.HOST_API)) is None


def test_open_db_creates_and_migrates(cfg_file: Path, db_file: Path) -> None:
    cfg = settings(cfg_file, "notes")
    with closing(ext.open_db(notes, cfg)) as conn:
        assert connection.user_version(conn) == 1
        assert connection.table_names(conn) == {"notes"}
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert (db_file.parent / "notes.db").is_file()
    assert not db_file.exists()  # Blunderbook's own database isn't touched


def test_any_thread_connection(cfg_file: Path) -> None:
    cfg = settings(cfg_file, "notes")
    with closing(ext.open_db(notes, cfg, any_thread=True)) as conn:
        assert connection.table_names(conn) == {"notes"}


def upgraded_notes(tmp_path: Path) -> ext.Extension:
    """The notes extension, a version later: a second migration."""
    folder = tmp_path / "notes-v2"
    folder.mkdir()
    (folder / "0001_init.sql").write_text((NOTES_MIGRATIONS / "0001_init.sql").read_text())
    (folder / "0002_tags.sql").write_text("ALTER TABLE notes ADD COLUMN tag TEXT;")
    return ext.Extension(name="notes", title="Notes", host_api=ext.HOST_API, migrations=folder)


def test_upgrade_is_backed_up_first(tmp_path: Path, cfg_file: Path, db_file: Path) -> None:
    cfg = settings(cfg_file, "notes", auto=False)
    note(cfg, "first")
    heard: list[Path] = []
    with closing(ext.open_db(upgraded_notes(tmp_path), cfg, on_backup=heard.append)) as conn:
        assert connection.user_version(conn) == 2
    (made,) = backup.list_backups(folder(db_file), NOTES)
    assert (made.reason, made.store) == ("pre-migrate", "notes")
    assert heard == [made.path]
    assert texts(made.path) == ["first"]
    assert backup.list_backups(folder(db_file)) == []  # none of Blunderbook's own


def test_no_upgrade_without_the_backup(tmp_path: Path, cfg_file: Path, db_file: Path) -> None:
    cfg = settings(cfg_file, "notes", auto=False)
    note(cfg, "first")
    blocker = tmp_path / "a file"
    blocker.write_bytes(b"")
    cfg = Config(
        extensions=cfg.extensions, backup=BackupConfig(dir=str(blocker / "bk"), auto=False)
    )
    with pytest.raises(connection.StorageError, match="Can't back up the notes extension's"):
        ext.open_db(upgraded_notes(tmp_path), cfg)
    with closing(connection.connect(ext.db_path(notes), mode="ro")) as conn:
        assert connection.user_version(conn) == 1


def test_a_newer_database_names_the_extension(cfg_file: Path, db_file: Path) -> None:
    cfg = settings(cfg_file, "notes")
    path = ext.db_path(notes)
    path.parent.mkdir(parents=True)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("PRAGMA user_version = 5")
    with pytest.raises(connection.StorageError) as caught:
        ext.open_db(notes, cfg)
    assert str(caught.value) == (
        "The database was made by a newer version of the notes extension (schema 5; this one "
        "knows up to 1). Update the extension to use it."
    )


def test_databases_lists_blunderbook_first(cfg_file: Path, db_file: Path) -> None:
    cfg = settings(cfg_file, "sample", "notes", "broken")
    assert ext.databases(cfg) == [
        (connection.CORE, db_file),
        (NOTES, db_file.parent / "notes.db"),
    ]  # sample has no database; broken can't be loaded


# ---------------------------------------------------------------- backups


def test_names_carry_the_database() -> None:
    name = backup.file_name(NOW, "pre-migrate", store=NOTES)
    assert name == "notes-2026-11-07_120000Z-pre-migrate.db"
    parsed = backup.parse_name(Path(name))
    assert parsed is not None and (parsed.store, parsed.reason) == ("notes", "pre-migrate")
    core = backup.parse_name(Path("blunderbook-2026-11-07_120000Z.db"))
    assert core is not None and core.store == "blunderbook"


def test_rotation_keeps_each_databases_own(cfg_file: Path, db_file: Path) -> None:
    cfg = settings(cfg_file, "notes")
    core_with_data(db_file)
    note(cfg, "first")
    where = folder(db_file)
    for minutes in range(3):
        backup.take(db_file, where, keep=2, now=NOW + timedelta(minutes=minutes))
    backup.take(ext.db_path(notes), where, keep=1, now=NOW, store=NOTES)
    backup.take(ext.db_path(notes), where, keep=1, now=NOW + timedelta(hours=1), store=NOTES)
    assert names(where) == [
        "blunderbook-2026-11-07_120100Z.db",
        "blunderbook-2026-11-07_120200Z.db",
        "notes-2026-11-07_130000Z.db",
    ]


def test_backup_command_covers_extensions(cfg_file: Path, db_file: Path) -> None:
    cfg = settings(cfg_file, "notes")
    core_with_data(db_file)
    result = runner.invoke(cli.app, ["backup"])
    assert result.exit_code == 0, result.output
    assert "notes" not in result.output  # no notes.db yet: nothing to back up
    note(cfg, "first")
    result = runner.invoke(cli.app, ["backup"])
    assert result.exit_code == 0, result.output
    assert "Backed up the database to" in result.output
    assert "Backed up the notes extension's database to" in result.output
    (made,) = backup.list_backups(folder(db_file), NOTES)
    assert texts(made.path) == ["first"]


def test_daily_backups_cover_extensions(cfg_file: Path, db_file: Path) -> None:
    cfg = settings(cfg_file, "notes")
    core_with_data(db_file)
    note(cfg, "first")
    done = ext.daily_backups(cfg)
    assert done.problems == ()
    assert sorted(p.name.split("-")[0] for p in done.taken) == ["blunderbook", "notes"]
    assert ext.daily_backups(cfg) == ext.DailyBackups()  # not due again today


def test_a_failed_extension_backup_is_only_a_warning(
    cfg_file: Path, db_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = settings(cfg_file, "notes")
    core_with_data(db_file)
    note(cfg, "first")
    real = backup.auto

    def fail_for_notes(db: Path, folder: Path, **kw: object) -> backup.Snapshot | None:
        if kw.get("store") == NOTES:
            raise backup.BackupError("disk full")
        return real(db, folder, **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(backup, "auto", fail_for_notes)
    done = ext.daily_backups(cfg)
    assert [p.name.split("-")[0] for p in done.taken] == ["blunderbook"]
    assert done.problems == (
        "The daily backup of the notes extension's database didn't work: disk full",
    )


def test_the_host_daily_backup(
    cfg_file: Path, db_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "db_path", lambda: db_file)
    cfg = settings(cfg_file, "notes", auto=False)
    core_with_data(db_file)
    note(cfg, "first")
    assert host.daily_backup() == ext.DailyBackups()  # auto = false: none
    settings(cfg_file, "notes")
    done = host.daily_backup()
    assert sorted(p.name.split("-")[0] for p in done.taken) == ["blunderbook", "notes"]
    assert host.daily_backup() == ext.DailyBackups()


# ---------------------------------------------------------------- restore


def test_restore_an_extension_backup(cfg_file: Path, db_file: Path) -> None:
    cfg = settings(cfg_file, "notes")
    core_with_data(db_file)
    note(cfg, "before")
    taken = backup.take(ext.db_path(notes), folder(db_file), keep=14, store=NOTES)
    note(cfg, "after")
    result = runner.invoke(cli.app, ["restore", taken.backup.path.name, "--yes"])
    assert result.exit_code == 0, result.output
    assert texts(ext.db_path(notes)) == ["before"]
    (safety,) = [b for b in backup.list_backups(folder(db_file), NOTES) if b.reason]
    assert safety.reason == "pre-restore"
    assert texts(safety.path) == ["before", "after"]
    with closing(connection.connect(db_file, mode="ro")) as conn:  # Blunderbook's untouched
        assert conn.execute("SELECT count(*) FROM sync_state").fetchone()[0] == 1


def test_restore_needs_the_extension_on(cfg_file: Path, db_file: Path) -> None:
    cfg = settings(cfg_file, "notes")
    note(cfg, "first")
    taken = backup.take(ext.db_path(notes), folder(db_file), keep=14, store=NOTES)
    settings(cfg_file)  # turned off
    result = runner.invoke(cli.app, ["restore", str(taken.backup.path), "--yes"])
    assert result.exit_code == 1
    assert "is a backup of the notes extension's database, and that extension isn't on." in (
        result.output
    )


def test_a_backup_of_another_database_is_refused(cfg_file: Path, db_file: Path) -> None:
    """A renamed file can't put one database's backup in another's place."""
    cfg = settings(cfg_file, "notes")
    core_with_data(db_file)
    note(cfg, "first")
    where = folder(db_file)
    core_backup = backup.take(db_file, where, keep=14).backup.path
    notes_backup = backup.take(ext.db_path(notes), where, keep=14, store=NOTES).backup.path

    as_notes = where / "notes-2026-01-01_000000Z.db"
    as_notes.write_bytes(core_backup.read_bytes())
    with pytest.raises(
        backup.BackupError, match="isn't a backup of the notes extension's database"
    ):
        backup.check_file(as_notes, NOTES)

    renamed = where / "my copy.db"  # no generated name: taken as Blunderbook's
    renamed.write_bytes(notes_backup.read_bytes())
    result = runner.invoke(cli.app, ["restore", str(renamed), "--yes"])
    assert result.exit_code == 1
    assert "isn't a backup of the Blunderbook database." in result.output
