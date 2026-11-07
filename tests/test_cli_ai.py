"""`blunderbook ai show|set-key|model|on|off` and doctor's AI row, against a temp config.
Nothing here calls OpenRouter."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from blunderbook import config
from blunderbook.cli import app
from blunderbook.config import AiConfig, Config

runner = CliRunner()
KEY = "sk-or-v1-0123456789abcdef"
DOT = "\N{MIDDLE DOT}"


@pytest.fixture
def cfg_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "home" / "config.toml"
    monkeypatch.setattr(config, "config_path", lambda: path)
    monkeypatch.delenv(config.STOCKFISH_ENV, raising=False)
    monkeypatch.setattr("shutil.which", lambda _: None)
    return path


def saved(cfg_file: Path) -> AiConfig:
    return config.load(cfg_file).ai


def test_show_never_prints_the_key(cfg_file: Path) -> None:
    config.save(Config(ai=AiConfig(enabled=True, model="deepseek/deepseek-chat", key=KEY)))
    result = runner.invoke(app, ["ai", "show"])
    assert result.exit_code == 0, result.output
    assert "AI explanations  on" in result.output
    assert "Model            deepseek/deepseek-chat" in result.output
    assert "OpenRouter key   set" in result.output
    assert KEY not in result.output


def test_show_with_nothing_set(cfg_file: Path) -> None:
    result = runner.invoke(app, ["ai", "show"])
    assert result.exit_code == 0, result.output
    assert "AI explanations  off" in result.output
    assert "Model            not set" in result.output
    assert "OpenRouter key   not set" in result.output


def test_set_key_is_hidden_and_kept(cfg_file: Path) -> None:
    config.save(Config(my_names=("Rashed",)))
    result = runner.invoke(app, ["ai", "set-key"], input=f"  {KEY}  \n")
    assert result.exit_code == 0, result.output
    assert KEY not in result.output  # hidden input isn't echoed
    assert saved(cfg_file).key == KEY
    assert config.load(cfg_file).my_names == ("Rashed",)
    assert "Next: blunderbook ai model NAME" in result.output


def test_empty_key_removes_it(cfg_file: Path) -> None:
    config.save(Config(ai=AiConfig(model="m", key=KEY)))
    result = runner.invoke(app, ["ai", "set-key"], input="\n")
    assert result.exit_code == 0, result.output
    assert "Key removed" in result.output
    assert saved(cfg_file).key == ""


def test_model_is_saved(cfg_file: Path) -> None:
    config.save(Config(ai=AiConfig(key=KEY)))
    result = runner.invoke(app, ["ai", "model", " anthropic/claude-haiku "])
    assert result.exit_code == 0, result.output
    assert saved(cfg_file) == AiConfig(model="anthropic/claude-haiku", key=KEY)
    assert "Next: blunderbook ai on" in result.output


def test_empty_model_saves_nothing(cfg_file: Path) -> None:
    result = runner.invoke(app, ["ai", "model", "  "])
    assert result.exit_code == 1
    assert "Nothing was saved." in result.output
    assert not cfg_file.exists()


@pytest.mark.parametrize(
    ("ai", "message"),
    [
        (AiConfig(model="m"), "No OpenRouter key is set."),
        (AiConfig(key=KEY), "No model is set."),
    ],
)
def test_on_refuses_without_key_or_model(cfg_file: Path, ai: AiConfig, message: str) -> None:
    config.save(Config(ai=ai))
    result = runner.invoke(app, ["ai", "on"])
    assert result.exit_code == 1
    assert message in result.output
    assert "AI explanations stay off." in result.output
    assert saved(cfg_file).enabled is False


def test_on_then_off_keeps_the_key(cfg_file: Path) -> None:
    config.save(Config(ai=AiConfig(model="m", key=KEY)))
    result = runner.invoke(app, ["ai", "on"])
    assert result.exit_code == 0, result.output
    assert "AI explanations are on, with m." in result.output
    assert saved(cfg_file).enabled is True
    result = runner.invoke(app, ["ai", "off"])
    assert result.exit_code == 0, result.output
    assert saved(cfg_file) == AiConfig(enabled=False, model="m", key=KEY)


def test_doctor_ai_off(cfg_file: Path) -> None:
    result = runner.invoke(app, ["doctor"])
    assert "AI         off" in result.output


def test_doctor_ai_on(cfg_file: Path) -> None:
    config.save(Config(ai=AiConfig(enabled=True, model="m", key=KEY)))
    result = runner.invoke(app, ["doctor"])
    assert f"AI         on {DOT} m {DOT} OpenRouter key set" in result.output
    assert KEY not in result.output


def test_doctor_ai_on_without_a_key_is_a_problem(cfg_file: Path) -> None:
    config.save(Config(ai=AiConfig(enabled=True, model="m")))
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "AI         Problem: No OpenRouter key is set." in result.output
    assert "2 problems found." in result.output  # this, and no Stockfish
