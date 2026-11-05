"""`blunderbook backup` and `restore`, against a temp config and temp databases."""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import chess
import pytest
from typer.testing import CliRunner

from blunderbook import config
from blunderbook.cli import app
from blunderbook.core.models import NewGame
from blunderbook.db import backup, connection, repo

runner = CliRunner()
DOT = "\N{MIDDLE DOT}"


@pytest.fixture
def cfg_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "home" / "config.toml"
    monkeypatch.setattr(config, "config_path", lambda: path)
    return path


@pytest.fixture
def folder(tmp_path: Path, cfg_file: Path) -> Path:
    """The configured backup folder, keeping 3."""
    path = tmp_path / "cloud" / "Blunderbook"
    config.save(config.Config(backup=config.BackupConfig(dir=str(path), keep=3)), cfg_file)
    return path


def add_game(db: Path, fingerprint: str) -> None:
    game = NewGame(
        fingerprint=fingerprint,
        source="pgn",
        my_color="white",
        start_fen=chess.STARTING_FEN,
        pgn="1. e4 e5 *",
        engine_name="Stockfish 17.1",
        engine_depth=16,
    )
    with closing(connection.open_db(db, create=True)) as conn:
        repo.add_game(conn, game)


def fingerprints(db: Path) -> set[str]:
    with closing(connection.connect(db, mode="ro")) as conn:
        return repo.known_fingerprints(conn)


@pytest.fixture
def db(db_file: Path) -> Path:
    add_game(db_file, "first")
    return db_file


# ---------------------------------------------------------------- backup


def test_backup_to_the_configured_folder(db: Path, folder: Path) -> None:
    result = runner.invoke(app, ["backup"])
    assert result.exit_code == 0, result.output
    (made,) = backup.list_backups(folder)
    assert result.output == f"Backed up the database to\n  {made.path}\n"
    assert fingerprints(made.path) == {"first"}


def test_backup_default_folder_is_next_to_the_database(db: Path, cfg_file: Path) -> None:
    result = runner.invoke(app, ["backup"])
    assert result.exit_code == 0, result.output
    assert len(backup.list_backups(db.parent / "backups")) == 1


def test_backup_to_another_folder(db: Path, folder: Path, tmp_path: Path) -> None:
    usb = tmp_path / "usb"
    result = runner.invoke(app, ["backup", "--to", str(usb)])
    assert result.exit_code == 0, result.output
    assert len(backup.list_backups(usb)) == 1
    assert not folder.exists()


def test_backup_rotates(db: Path, folder: Path) -> None:
    folder.mkdir(parents=True)
    for day in ("01", "02", "03"):
        (folder / f"blunderbook-2026-11-{day}_090000Z.db").write_bytes(b"")
    (folder / "my notes.txt").write_bytes(b"")
    result = runner.invoke(app, ["backup"])
    assert result.exit_code == 0, result.output
    assert "Deleted 1 older backup, keeping the newest 3." in result.output
    assert not (folder / "blunderbook-2026-11-01_090000Z.db").exists()
    assert (folder / "my notes.txt").exists()


def test_backup_without_a_database(cfg_file: Path, db_file: Path) -> None:
    result = runner.invoke(app, ["backup"])
    assert result.exit_code == 1
    assert f"No database at {db_file} yet, so there's nothing to back up." in result.output


def test_backup_with_an_unset_variable(
    db: Path, cfg_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BB_MISSING", raising=False)
    config.save(config.Config(backup=config.BackupConfig(dir="$BB_MISSING/bk")), cfg_file)
    result = runner.invoke(app, ["backup"])
    assert result.exit_code == 1
    assert "backup.dir uses $BB_MISSING, which isn't set on this computer" in result.output


# ---------------------------------------------------------------- restore


@pytest.fixture
def saved(db: Path, folder: Path) -> Path:
    """A backup of the database with "first", and "second" added since."""
    path = backup.take(db, folder, keep=3).backup.path
    add_game(db, "second")
    return path


def test_restore_with_yes(db: Path, folder: Path, saved: Path) -> None:
    result = runner.invoke(app, ["restore", str(saved), "--yes"])
    assert result.exit_code == 0, result.output
    out = result.output
    assert f"Backup     {saved}\n           taken " in out
    assert f"(just now) {DOT} 1 game {DOT} 0 entries\n" in out
    assert f"Database   {db}\n           now holds 2 games {DOT} 0 entries\n" in out
    assert "Saved a copy of your database first:\n  " in out
    assert out.endswith(f"Restored {saved.name}: 1 game {DOT} 0 entries.\n")
    assert fingerprints(db) == {"first"}
    (safety,) = [b for b in backup.list_backups(folder) if b.reason == "pre-restore"]
    assert fingerprints(safety.path) == {"first", "second"}


def test_restore_asks_first(db: Path, folder: Path, saved: Path) -> None:
    result = runner.invoke(app, ["restore", str(saved)], input="n\n")
    assert result.exit_code == 1
    assert "Stop the web app (blunderbook serve) first if it's running." in result.output
    assert "Replace your database with this backup? [y/N]" in result.output
    assert result.output.endswith("Nothing was changed.\n")
    assert fingerprints(db) == {"first", "second"}
    assert len(backup.list_backups(folder)) == 1

    result = runner.invoke(app, ["restore", str(saved)], input="y\n")
    assert result.exit_code == 0, result.output
    assert fingerprints(db) == {"first"}


def test_restore_without_an_answer_changes_nothing(db: Path, saved: Path) -> None:
    result = runner.invoke(app, ["restore", str(saved)])  # no input at all
    assert result.exit_code == 1
    assert "Nothing was changed." in result.output
    assert fingerprints(db) == {"first", "second"}


def test_restore_a_name_from_the_backup_folder(
    db: Path, saved: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["restore", saved.name, "--yes"])
    assert result.exit_code == 0, result.output
    assert f"Backup     {saved}\n" in result.output
    assert fingerprints(db) == {"first"}


def test_restore_a_file_that_isnt_there(
    db: Path, folder: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["restore", "nope.db", "--yes"])
    assert result.exit_code == 1
    assert f"No file called nope.db, here or in the backup folder {folder}." in result.output
    result = runner.invoke(app, ["restore", str(tmp_path / "x" / "nope.db"), "--yes"])
    assert result.exit_code == 1
    assert f"No file called {tmp_path / 'x' / 'nope.db'}.\nNothing was changed." in result.output


def test_restore_refuses_a_newer_backup(db: Path, folder: Path, tmp_path: Path) -> None:
    newer = tmp_path / "newer.db"
    with closing(sqlite3.connect(newer, autocommit=True)) as conn:
        conn.execute("CREATE TABLE games (id INTEGER PRIMARY KEY)")
        conn.execute("PRAGMA user_version = 99")
    result = runner.invoke(app, ["restore", str(newer), "--yes"])
    assert result.exit_code == 1
    assert f"Can't restore {newer}: The database was made by a newer Blunderbook" in result.output
    assert result.output.endswith("Nothing was changed.\n")
    assert fingerprints(db) == {"first"}
    assert not folder.exists()


def test_restore_on_a_new_computer(db: Path, folder: Path, tmp_path: Path) -> None:
    """The database isn't there yet (or is empty): no safety copy, and it's created."""
    path = backup.take(db, folder, keep=3).backup.path
    for leftover in db.parent.iterdir():
        leftover.unlink()
    result = runner.invoke(app, ["restore", str(path), "--yes"])
    assert result.exit_code == 0, result.output
    assert f"Database   {db}\n           not created yet\n" in result.output
    assert "Saved a copy" not in result.output
    assert fingerprints(db) == {"first"}


def test_restore_names_an_older_backup_without_a_time(db: Path, tmp_path: Path) -> None:
    mine = tmp_path / "my copy.db"
    backup.take(
        db, tmp_path / "bk", keep=3, now=datetime(2026, 1, 1, tzinfo=UTC)
    ).backup.path.rename(mine)
    result = runner.invoke(app, ["restore", str(mine), "--yes"])
    assert result.exit_code == 0, result.output
    assert f"Backup     {mine}\n           1 game {DOT} 0 entries\n" in result.output
