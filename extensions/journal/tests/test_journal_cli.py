"""The Journal's commands (ROADMAP 19.1): `blunderbook journal new`, `list`, `show` and
`export`, on their own and through `blunderbook` with the extension turned on."""

import os
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import blunderbook_journal
import pytest
from blunderbook_journal import commands, extension, store
from journal_fakes import ELEPHANT, cfg_file  # noqa: F401  (fixtures)
from typer.testing import CliRunner

from blunderbook import cli, config, ext, host
from blunderbook.db import connection

runner = CliRunner()
DOT = "\N{MIDDLE DOT}"


@pytest.fixture
def restore_commands() -> Iterator[None]:
    groups = list(cli.app.registered_groups)
    yield
    cli.app.registered_groups[:] = groups


def call(*args: str, stdin: str | None = None) -> tuple[int, list[str]]:
    """The exit code and the output's lines, without the daily backup's line."""
    result = runner.invoke(commands, list(args), input=stdin)
    lines = [x for x in result.output.splitlines() if not x.startswith("Daily backup: ")]
    return result.exit_code, lines


def add(body: str, *, at: datetime | None = None, pinned: bool = False) -> store.Note:
    with closing(host.open_db(extension)) as conn:
        note = store.create(conn, body, at=at)
        if pinned:
            store.set_pinned(conn, note.id, True)
    return note


def day(moment: datetime) -> str:
    local = moment.astimezone()
    return f"{local.day} {local:%b %Y}"


# ---------------------------------------------------------------- new


def test_new_from_the_text() -> None:
    code, lines = call("new", ELEPHANT)
    assert (code, lines) == (0, [f"Note #1: The Elephant trap {DOT} #qgd #traps"])
    with closing(host.open_db(extension)) as conn:
        note = store.get(conn, 1)
    assert note is not None and note.body == ELEPHANT


def test_new_from_a_file(tmp_path: Path) -> None:
    path = tmp_path / "note.md"
    path.write_text("﻿# From a file\nBody", encoding="utf-8")
    assert call("new", "--file", str(path)) == (0, ["Note #1: From a file"])


def test_new_from_what_is_piped_in() -> None:
    assert call("new", stdin="Piped in\n") == (0, ["Note #1: Piped in"])


def test_new_untitled() -> None:
    assert call("new", "```fen\n8/8/8/8/8/8/8/8 w - - 0 1\n```") == (0, ["Note #1: Untitled"])


@pytest.mark.parametrize(
    ("args", "said"),
    [
        (["new", "   \n"], "The note is empty."),
        (["new", "x", "--file", "a.md"], "Give the text or --file, not both."),
        (["new", "--file", "missing.md"], "Can't read missing.md"),
    ],
)
def test_new_refuses(args: list[str], said: str) -> None:
    code, lines = call(*args)
    assert code == 1
    assert lines[0].startswith(said)
    assert not ext.db_path(extension).exists()  # nothing was touched


def test_new_refuses_a_file_that_isnt_text(tmp_path: Path) -> None:
    path = tmp_path / "board.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe")
    assert call("new", "--file", str(path)) == (1, [f"{path} isn't UTF-8 text."])


def test_new_takes_the_daily_backup() -> None:
    with closing(connection.open_db(config.db_path(), create=True)) as conn:
        conn.execute(
            "INSERT INTO imports (label, kind, started_at) VALUES ('x', 'file', '2026-01-01')"
        )
    result = runner.invoke(commands, ["new", "Hello"])
    assert result.exit_code == 0, result.output
    assert result.output.startswith("Daily backup: ")


# ---------------------------------------------------------------- list


def test_list_with_no_notes() -> None:
    assert call("list") == (0, ['No notes yet. Write one: blunderbook journal new "# Title"'])


def test_list() -> None:
    noon = datetime(2026, 11, 20, 12, tzinfo=UTC)
    add("# Old one", at=noon - timedelta(days=30))
    add(ELEPHANT, at=noon)
    add("# Rules\nchecks, captures, threats #habits", at=noon - timedelta(days=60), pinned=True)
    code, lines = call("list")
    assert code == 0
    assert lines == [
        f"#3  Rules {DOT} pinned {DOT} #habits {DOT} {day(noon - timedelta(days=60))}",
        f"#2  The Elephant trap {DOT} #qgd #traps {DOT} {day(noon)}",
        f"#1  Old one {DOT} {day(noon - timedelta(days=30))}",
        "3 notes",
    ]


def test_list_one_note() -> None:
    add("Only")
    assert call("list")[1][-1] == "1 note"


def test_list_search_and_tag() -> None:
    add(ELEPHANT)
    add("# Lucena\nthe bridge #endgame")
    add("# Philidor\nthird rank #endgame")
    assert call("list", "--search", "petrova")[1][0].startswith("#1  The Elephant trap")
    code, lines = call("list", "--tag", "endgame")
    assert code == 0
    assert [x.split(f" {DOT} ")[0] for x in lines] == ["#3  Philidor", "#2  Lucena", "2 of 3 notes"]
    assert call("list", "-s", "bridge", "-t", "endgame")[1][-1] == "1 of 3 notes"
    assert call("list", "--search", "zebra") == (0, ["No notes match."])


# ---------------------------------------------------------------- show


def test_show_prints_the_text_as_written() -> None:
    add(ELEPHANT)
    result = runner.invoke(commands, ["show", "1"])
    assert result.exit_code == 0
    assert result.output == ELEPHANT


def test_show_adds_a_last_newline_only_when_missing() -> None:
    add("No newline")
    assert runner.invoke(commands, ["show", "1"]).output == "No newline\n"


def test_show_a_note_that_isnt_there() -> None:
    assert call("show", "7") == (1, ["No note #7. See them with: blunderbook journal list"])


# ---------------------------------------------------------------- export


def test_export(tmp_path: Path) -> None:
    noon = datetime(2026, 11, 20, 12, tzinfo=UTC)
    add(ELEPHANT, at=noon)
    add("```fen\n8/8/8/8/8/8/8/8 w - - 0 1\n```\n", at=noon)
    add("# Windows\r\nline endings\r\n", at=noon)
    folder = tmp_path / "out" / "journal"
    assert call("export", str(folder)) == (0, [f"Exported 3 notes to {folder}"])
    files = sorted(p.name for p in folder.iterdir())
    assert files == ["1-the-elephant-trap.md", "2-note.md", "3-windows.md"]
    assert (folder / "1-the-elephant-trap.md").read_text(encoding="utf-8") == ELEPHANT
    assert (folder / "3-windows.md").read_bytes() == b"# Windows\r\nline endings\r\n"
    assert os.path.getmtime(folder / "1-the-elephant-trap.md") == noon.timestamp()


def test_export_again_replaces_its_own_files_only(tmp_path: Path) -> None:
    note = add("# First")
    mine = tmp_path / "keep-me.md"
    mine.write_text("mine")
    call("export", str(tmp_path))
    with closing(host.open_db(extension)) as conn:
        store.update(conn, note.id, "# First\nmore")
    assert call("export", str(tmp_path))[0] == 0
    assert (tmp_path / "1-first.md").read_text() == "# First\nmore"
    assert mine.read_text() == "mine"


def test_export_with_no_notes(tmp_path: Path) -> None:
    assert call("export", str(tmp_path / "x")) == (0, ["No notes yet: nothing to export."])
    assert not (tmp_path / "x").exists()


def test_export_to_a_file_is_a_plain_message(tmp_path: Path) -> None:
    add("A")
    blocker = tmp_path / "file"
    blocker.write_text("")
    code, lines = call("export", str(blocker))
    assert code == 1
    assert lines[0].startswith(f"Can't write to {blocker}")


def test_a_broken_config_is_a_plain_message(cfg_file: Path) -> None:
    cfg_file.write_text("engine_depth = 'deep'\n")
    for args in (["new", "x"], ["list"], ["show", "1"]):
        result = runner.invoke(commands, args)
        assert result.exit_code == 1
        assert "engine_depth" in result.output


# ---------------------------------------------------------------- with Blunderbook


def test_through_blunderbook(cfg_file: Path, restore_commands: None) -> None:
    config.save(config.Config(), cfg_file)
    on = runner.invoke(cli.app, ["ext", "enable", "journal"])
    assert on.exit_code == 0, on.output
    assert on.output.startswith("Turned on journal (Journal).\n")
    cli.add_extension_commands()
    result = runner.invoke(cli.app, ["journal", "new", "# Through Blunderbook"])
    assert result.exit_code == 0, result.output
    assert result.output.endswith("Note #1: Through Blunderbook\n")
    assert ext.db_path(extension).exists()


def test_journal_db_is_in_the_backups(cfg_file: Path) -> None:
    with closing(connection.open_db(config.db_path(), create=True)):
        pass
    add("Backed up")
    done = runner.invoke(cli.app, ["backup"])
    assert done.exit_code == 0, done.output
    folder = config.backup_folder(config.load(cfg_file))
    backups = [p for p in folder.iterdir() if p.name.startswith("journal-")]
    assert len(backups) == 1
    assert extension.backups_kept is None  # your writing can't be downloaded again


def test_a_backup_restores(cfg_file: Path) -> None:
    with closing(connection.open_db(config.db_path(), create=True)):
        pass
    add("# Kept")
    assert runner.invoke(cli.app, ["backup"]).exit_code == 0
    add("# Added after")
    folder = config.backup_folder(config.load(cfg_file))
    [backup] = [p for p in folder.iterdir() if p.name.startswith("journal-")]
    done = runner.invoke(cli.app, ["restore", str(backup), "--yes"])
    assert done.exit_code == 0, done.output
    assert call("list")[1][-1] == "1 note"
    assert call("list", "-s", "kept")[1][0].startswith("#1  Kept")


def test_only_the_host_api_is_used() -> None:
    package = Path(blunderbook_journal.__file__).parent
    assert ext.boundary_problems(package) == []
