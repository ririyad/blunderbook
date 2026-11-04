from pathlib import Path

import chess.engine
import pytest
from typer.testing import CliRunner

from blunderbook import __version__
from blunderbook.cli import app

runner = CliRunner()


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"blunderbook {__version__}"


def test_no_args_shows_help() -> None:
    result = runner.invoke(app, [])
    assert "Usage" in result.output


@pytest.mark.engine
def test_stockfish_starts(stockfish_path: Path) -> None:
    with chess.engine.SimpleEngine.popen_uci(str(stockfish_path)) as engine:
        assert engine.id.get("name", "").startswith("Stockfish")
