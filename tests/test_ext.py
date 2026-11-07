"""Finding and loading extensions (CLAUDE.md §15), and the `ext` commands, with hand-made
entry points to the sample extensions in ext_samples.py. Nothing is installed."""

from collections.abc import Iterator
from importlib.metadata import EntryPoint
from pathlib import Path

import pytest
from typer.testing import CliRunner

from blunderbook import cli, config, ext
from blunderbook.config import Config, ExtensionsConfig

runner = CliRunner()


def point(name: str, value: str | None = None) -> EntryPoint:
    return EntryPoint(name, value or f"ext_samples:{name}", ext.GROUP)


POINTS = [
    point("sample"),
    point("other"),
    point("log", "ext_samples:reserved"),
    point("Bad1", "ext_samples:bad_name"),
    point("old", "ext_samples:old_api"),
    point("plain", "ext_samples:not_an_extension"),
    point("broken", "ext_samples_broken:extension"),
    point("gone", "ext_samples_no_such_module:extension"),
]


@pytest.fixture(autouse=True)
def installed(monkeypatch: pytest.MonkeyPatch) -> None:
    """These sample entry points stand in for installed packages."""
    monkeypatch.setattr(ext, "entry_points", lambda group: POINTS if group == ext.GROUP else [])


@pytest.fixture
def cfg_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "home" / "config.toml"
    monkeypatch.setattr(config, "config_path", lambda: path)
    monkeypatch.delenv(config.STOCKFISH_ENV, raising=False)
    monkeypatch.setattr("shutil.which", lambda _: None)
    return path


def turned_on(cfg_file: Path, *names: str) -> None:
    config.save(Config(extensions=ExtensionsConfig(enabled=names)), cfg_file)


# ---------------------------------------------------------------- loading


def test_load_in_the_order_given() -> None:
    loaded = ext.load(["other", "sample", "other"])
    assert [e.name for e in loaded.extensions] == ["other", "sample"]
    assert loaded.problems == ()


def test_nothing_on_loads_nothing() -> None:
    assert ext.load([]) == ext.Loaded()


@pytest.mark.parametrize(
    ("name", "problem"),
    [
        ("missing", "The missing extension is turned on but isn't installed. Install it, "
         "or run: blunderbook ext disable missing"),
        ("log", "'log' can't be an extension name: Blunderbook uses it already."),
        ("Bad1", "'Bad1' can't be an extension name: use lowercase letters only."),
        ("old", "The old extension was made for host API 2, and this Blunderbook has host "
         "API 1. Update the one that's older."),
        ("plain", "The plain extension doesn't point at a Blunderbook Extension."),
        ("broken", "The broken extension couldn't be loaded: RuntimeError: this extension "
         "is broken"),
        ("gone", "The gone extension couldn't be loaded: ModuleNotFoundError: "),
    ],
)  # fmt: skip
def test_a_bad_extension_is_left_out_with_a_reason(name: str, problem: str) -> None:
    loaded = ext.load(["sample", name])
    assert [e.name for e in loaded.extensions] == ["sample"]  # the others still load
    (found,) = loaded.problems
    assert found.startswith(problem), found


def test_names_must_match() -> None:
    mismatch = EntryPoint("alias", "ext_samples:sample", ext.GROUP)
    extension, problem = ext.load_one(mismatch)
    assert extension is None
    assert problem == "The alias extension calls itself 'sample'; the names must match."


def test_installed_and_find() -> None:
    names = [item.name for item in ext.installed()]
    assert names == sorted(p.name for p in POINTS)
    assert ext.find("sample") is not None
    assert ext.find("nothing") is None


# ---------------------------------------------------------------- config


def test_config_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    turned_on(path, "sample", "other")
    assert config.load(path).extensions.enabled == ("sample", "other")
    assert "[extensions]\nenabled = ['sample', 'other']" in path.read_text("utf-8")


def test_config_rejects_a_bad_name(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[extensions]\nenabled = ["Sample"]\n', "utf-8")
    with pytest.raises(config.ConfigError, match="'Sample' isn't an extension name"):
        config.load(path)


# ---------------------------------------------------------------- commands


def test_enable_then_disable(cfg_file: Path) -> None:
    result = runner.invoke(cli.app, ["ext", "enable", "sample"])
    assert result.exit_code == 0, result.output
    assert "Turned on sample (Sample)." in result.output
    assert "Restart blunderbook serve" in result.output
    assert config.load(cfg_file).extensions.enabled == ("sample",)

    again = runner.invoke(cli.app, ["ext", "enable", "sample"])
    assert "already on" in again.output

    result = runner.invoke(cli.app, ["ext", "disable", "sample"])
    assert result.exit_code == 0, result.output
    assert "Its data stays" in result.output
    assert config.load(cfg_file).extensions.enabled == ()


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("nothing", "No extension called nothing is installed."),
        ("broken", "The broken extension couldn't be loaded"),
        ("old", "was made for host API 2"),
    ],
)
def test_enable_refuses_what_cant_be_used(cfg_file: Path, name: str, message: str) -> None:
    result = runner.invoke(cli.app, ["ext", "enable", name])
    assert result.exit_code == 1
    assert message in result.output
    assert "Nothing was changed." in result.output
    assert not cfg_file.exists()


def test_list(cfg_file: Path) -> None:
    turned_on(cfg_file, "sample", "missing")
    result = runner.invoke(cli.app, ["ext", "list"])
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert any(line.startswith("sample") and " on " in line and "Sample" in line for line in lines)
    assert any(line.startswith("other") and " off " in line for line in lines)
    assert "Problem: The missing extension is turned on but isn't installed." in result.output


def test_list_with_none_installed(cfg_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ext, "entry_points", lambda group: [])
    assert runner.invoke(cli.app, ["ext", "list"]).output == "No extensions installed.\n"


def test_doctor_rows(cfg_file: Path) -> None:
    result = runner.invoke(cli.app, ["doctor"])
    assert "Extensions none on" in result.output
    turned_on(cfg_file, "sample", "broken")
    result = runner.invoke(cli.app, ["doctor"])
    assert "Extensions sample \N{MIDDLE DOT} Sample" in result.output
    assert "           Problem: The broken extension couldn't be loaded" in result.output
    assert "2 problems found." in result.output  # this, and no Stockfish


@pytest.fixture
def restore_commands() -> Iterator[None]:
    """add_extension_commands() changes the app itself: put it back afterwards."""
    groups = list(cli.app.registered_groups)
    yield
    cli.app.registered_groups[:] = groups


def test_extension_commands_are_added(cfg_file: Path, restore_commands: None) -> None:
    turned_on(cfg_file, "sample", "other")
    cli.add_extension_commands()
    result = runner.invoke(cli.app, ["sample", "hello"])
    assert result.exit_code == 0, result.output
    assert result.output == "Hello from the sample extension.\n"
    assert runner.invoke(cli.app, ["other"]).exit_code != 0  # no commands of its own


def test_a_broken_config_adds_no_commands(cfg_file: Path, restore_commands: None) -> None:
    cfg_file.parent.mkdir(parents=True)
    cfg_file.write_text("engine_depth = 0\n", "utf-8")
    before = len(cli.app.registered_groups)
    cli.add_extension_commands()
    assert len(cli.app.registered_groups) == before
