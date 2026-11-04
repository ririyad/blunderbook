"""`blunderbook engine show|set|clear`, against a temp config and a stubbed probe."""

import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from blunderbook import config
from blunderbook.cli import app
from blunderbook.core import engine
from blunderbook.core.engine import EngineError, EngineInfo

runner = CliRunner()
WINDOWS = sys.platform == "win32"


@pytest.fixture
def cfg_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "home" / "config.toml"
    monkeypatch.setattr(config, "config_path", lambda: path)
    monkeypatch.delenv(config.STOCKFISH_ENV, raising=False)
    monkeypatch.setattr("shutil.which", lambda _: None)
    return path


@pytest.fixture
def good_probe(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake(command: list[str], timeout: float = 10.0) -> EngineInfo:
        calls.append(command)
        return EngineInfo("Stockfish 17.1", 17, 1)

    monkeypatch.setattr(engine, "probe", fake)
    return calls


def program(folder: Path, stem: str = "stockfish") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (stem + ".exe" if WINDOWS else stem)
    path.write_bytes(b"")
    path.chmod(0o755)
    return path


def test_set_folder_saves_program_path(
    tmp_path: Path, cfg_file: Path, good_probe: list[list[str]]
) -> None:
    exe = program(tmp_path / "Downloads" / "stockfish", "stockfish-windows-x86-64-avx2")
    result = runner.invoke(app, ["engine", "set", f'"{tmp_path / "Downloads"}"'])
    assert result.exit_code == 0, result.output
    assert f"Found Stockfish 17.1 at\n  {exe}" in result.output
    assert f"Saved to {cfg_file}" in result.output
    assert config.load(cfg_file).stockfish_path == str(exe)
    assert good_probe == [[str(exe)]]


def test_set_keeps_other_settings(
    tmp_path: Path, cfg_file: Path, good_probe: list[list[str]]
) -> None:
    config.save(config.Config(my_names=("Rashed",), engine_depth=20), cfg_file)
    exe = program(tmp_path)
    assert runner.invoke(app, ["engine", "set", str(exe)]).exit_code == 0
    saved = config.load(cfg_file)
    assert (saved.my_names, saved.engine_depth, saved.stockfish_path) == (
        ("Rashed",),
        20,
        str(exe),
    )


def test_set_bad_path_saves_nothing(tmp_path: Path, cfg_file: Path) -> None:
    result = runner.invoke(app, ["engine", "set", str(tmp_path / "nope")])
    assert result.exit_code == 1
    assert "Nothing found" in result.output
    assert "Nothing was saved." in result.output
    assert not cfg_file.exists()


def test_set_engine_that_fails_check_saves_nothing(
    tmp_path: Path, cfg_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(command: list[str], timeout: float = 10.0) -> EngineInfo:
        raise EngineError("This is Lc0 v0.31, not Stockfish. Blunderbook only uses Stockfish.")

    monkeypatch.setattr(engine, "probe", refuse)
    result = runner.invoke(app, ["engine", "set", str(program(tmp_path))])
    assert result.exit_code == 1
    assert "not Stockfish" in result.output
    assert not cfg_file.exists()


def test_set_warns_about_old_version(
    tmp_path: Path, cfg_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(engine, "probe", lambda *a, **k: EngineInfo("Stockfish 16", 16, None))
    result = runner.invoke(app, ["engine", "set", str(program(tmp_path))])
    assert result.exit_code == 0
    assert "expects Stockfish 17 or newer" in result.output


def test_set_mentions_env_override(
    tmp_path: Path, cfg_file: Path, good_probe: list[list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(config.STOCKFISH_ENV, "/elsewhere/stockfish")
    result = runner.invoke(app, ["engine", "set", str(program(tmp_path))])
    assert result.exit_code == 0
    assert f"{config.STOCKFISH_ENV} is set" in result.output


def test_show_reports_path_and_origin(
    tmp_path: Path, cfg_file: Path, good_probe: list[list[str]]
) -> None:
    exe = program(tmp_path)
    config.save(config.Config(stockfish_path=str(exe)), cfg_file)
    result = runner.invoke(app, ["engine", "show"])
    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[:3] == [
        "Stockfish 17.1",
        f"Path  {exe}",
        "From  config.toml (stockfish_path)",
    ]


def test_show_when_nothing_found(cfg_file: Path) -> None:
    result = runner.invoke(app, ["engine", "show"])
    assert result.exit_code == 1
    assert "No Stockfish found" in result.output
    assert "blunderbook engine set PATH" in result.output


def test_show_broken_saved_path(tmp_path: Path, cfg_file: Path) -> None:
    config.save(config.Config(stockfish_path=str(tmp_path / "gone.exe")), cfg_file)
    result = runner.invoke(app, ["engine", "show"])
    assert result.exit_code == 1
    assert "Nothing found" in result.output
    assert "config.toml" in result.output


def test_show_reports_bad_config(cfg_file: Path) -> None:
    cfg_file.parent.mkdir(parents=True)
    cfg_file.write_text("engine_depth = 0\n", "utf-8")
    result = runner.invoke(app, ["engine", "show"])
    assert result.exit_code == 1
    assert "engine_depth" in result.output


def test_clear(tmp_path: Path, cfg_file: Path) -> None:
    config.save(config.Config(my_names=("Rashed",), stockfish_path=str(tmp_path)), cfg_file)
    result = runner.invoke(app, ["engine", "clear"])
    assert result.exit_code == 0
    assert "Cleared" in result.output
    saved = config.load(cfg_file)
    assert (saved.stockfish_path, saved.my_names) == ("", ("Rashed",))


def test_clear_when_nothing_saved(cfg_file: Path) -> None:
    result = runner.invoke(app, ["engine", "clear"])
    assert result.exit_code == 0
    assert "No path was saved" in result.output
    assert not cfg_file.exists()
