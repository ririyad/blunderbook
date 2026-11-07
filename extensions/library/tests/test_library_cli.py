"""The Library's commands: `blunderbook library check` and `list`, on their own and through
`blunderbook` with the extension turned on."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from blunderbook_library import commands, content
from typer.testing import CliRunner

from blunderbook import cli, config

runner = CliRunner()
DOT = "\N{MIDDLE DOT}"


@pytest.fixture
def cfg_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "home" / "config.toml"
    monkeypatch.setattr(config, "config_path", lambda: path)
    monkeypatch.setattr(config, "db_path", lambda: tmp_path / "data" / "blunderbook.db")
    return path


@pytest.fixture
def restore_commands() -> Iterator[None]:
    groups = list(cli.app.registered_groups)
    yield
    cli.app.registered_groups[:] = groups


def test_check() -> None:
    result = runner.invoke(commands, ["check"])
    assert result.exit_code == 0, result.output
    assert result.output == (
        f"Checked 15 entries: 5 openings {DOT} 6 traps {DOT} 4 tactics\n"
        "Every line is legal, and every practise answer is a legal move.\n"
    )


def test_check_a_folder_with_a_problem(tmp_path: Path) -> None:
    root = tmp_path / "content"
    (root / "traps").mkdir(parents=True)
    good = (content.FOLDER / "traps" / "legal-trap.toml").read_text("utf-8")
    (root / "traps" / "legal-trap.toml").write_text(good, "utf-8")
    bad = good.replace("7. Nd5#", "7. Nd6#").replace("Légal's trap", "Légal again")
    (root / "traps" / "broken.toml").write_text(bad, "utf-8")
    result = runner.invoke(commands, ["check", str(root)])
    assert result.exit_code == 1
    assert result.output == (
        "traps/broken.toml: next 1: 7. Nd6# isn't legal after 6... Ke7.\n"
        f"1 entry fine {DOT} 1 problem\n"
    )


def test_list() -> None:
    result = runner.invoke(commands, ["list"])
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert len(lines) == 15
    assert lines[0].startswith("openings/")
    legal = next(line for line in lines if line.startswith("traps/legal-trap.toml"))
    assert legal.split(maxsplit=1)[1] == (
        f"Légal's trap {DOT} Black {DOT} Philidor Defence {DOT} C41"
    )
    smothered = next(line for line in lines if line.startswith("tactics/smothered-mate"))
    assert smothered.endswith(f"Smothered mate {DOT} White")


def test_through_blunderbook(cfg_file: Path, restore_commands: None) -> None:
    config.save(config.Config(my_names=("Rashed",)), cfg_file)
    on = runner.invoke(cli.app, ["ext", "enable", "library"])
    assert on.exit_code == 0, on.output
    assert on.output.startswith("Turned on library (Library).\n")
    cli.add_extension_commands()
    result = runner.invoke(cli.app, ["library", "check"])
    assert result.exit_code == 0, result.output
    assert result.output.startswith("Checked 15 entries")
    listed = runner.invoke(cli.app, ["ext", "list"]).output
    assert "library" in listed and "Library" in listed
