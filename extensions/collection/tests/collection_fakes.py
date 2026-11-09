"""The Collection's test setup: a scratch config.toml and databases with the extension on,
and a scripted engine, so no test touches your real files or needs Stockfish.

Not a conftest.py: core's tests import their own ``conftest`` by name, and a second one on
the path would shadow it. Each test module imports these fixtures instead."""

from collections.abc import Iterator
from pathlib import Path
from types import TracebackType

import chess
import pytest

from blunderbook import config, host
from blunderbook.core.engine import EngineError, EngineInfo, Line
from blunderbook.core.models import Eval

CLASSICS = Path(__file__).parent / "fixtures" / "classics.pgn"


@pytest.fixture(autouse=True)
def cfg_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """config.toml with the Collection on, and Blunderbook's database next to collection.db,
    both in tmp_path. Every test gets them, so none touches your real files."""
    path = tmp_path / "home" / "config.toml"
    monkeypatch.setattr(config, "config_path", lambda: path)
    monkeypatch.setattr(config, "db_path", lambda: tmp_path / "data" / "blunderbook.db")
    config.save(config.Config(extensions=config.ExtensionsConfig(enabled=("collection",))), path)
    return path


class FakeEngine:
    """Stands in for ``host.engine()``: every position scores +0.20 for White, with the
    first legal moves as its line. Fails on the ``fail_on``-th position when set, or raises
    ``interrupt`` there."""

    name = "Stockfish 17.1"
    info = EngineInfo("Stockfish 17.1", 17, 1)

    def __init__(self, fail_on: int = 0, interrupt: bool = False) -> None:
        self.fail_on = fail_on
        self.interrupt = interrupt
        self.calls: list[str] = []
        self.opened = 0
        self.closed = 0

    def lines(
        self, board: chess.Board, depth: int, multipv: int = 1, *, game: object = None
    ) -> list[Line]:
        self.calls.append(board.fen())
        if len(self.calls) == self.fail_on:
            if self.interrupt:
                raise KeyboardInterrupt
            raise EngineError("Stockfish stopped unexpectedly.")
        pv: list[chess.Move] = []
        b = board.copy()
        for _ in range(12):
            move = next(iter(b.legal_moves), None)
            if move is None:
                break
            pv.append(move)
            b.push(move)
        return [Line(Eval(cp=20), tuple(pv))]

    def __call__(self) -> FakeEngine:  # host.engine()
        self.opened += 1
        return self

    def __enter__(self) -> FakeEngine:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.closed += 1


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeEngine]:
    engine = FakeEngine()
    monkeypatch.setattr(host, "engine", engine)
    yield engine


@pytest.fixture
def no_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing() -> None:
        raise host.HostError("Can't analyse: Stockfish wasn't found.")

    monkeypatch.setattr(host, "engine", missing)
