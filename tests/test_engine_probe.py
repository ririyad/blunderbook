from collections.abc import Callable
from pathlib import Path

import pytest

from blunderbook.core.engine import EngineError, EngineInfo, probe

FakeEngine = Callable[..., list[str]]


def test_stockfish_17_is_fine(fake_engine: FakeEngine) -> None:
    info = probe(fake_engine("--name", "Stockfish 17.1"))
    assert info == EngineInfo(name="Stockfish 17.1", major=17, minor=1)
    assert not info.outdated
    assert not info.dev_build


def test_major_only_version(fake_engine: FakeEngine) -> None:
    info = probe(fake_engine("--name", "Stockfish 18"))
    assert (info.major, info.minor) == (18, None)


def test_old_stockfish_is_flagged_not_refused(fake_engine: FakeEngine) -> None:
    info = probe(fake_engine("--name", "Stockfish 16"))
    assert info.outdated


def test_dev_build_has_no_version(fake_engine: FakeEngine) -> None:
    info = probe(fake_engine("--name", "Stockfish dev-20260901-1a2b3c4d"))
    assert info.dev_build
    assert not info.outdated


@pytest.mark.parametrize("name", ["Lc0 v0.31", "Komodo Dragon 3.3"])
def test_other_engines_are_refused(fake_engine: FakeEngine, name: str) -> None:
    with pytest.raises(EngineError, match="not Stockfish"):
        probe(fake_engine("--name", name))


def test_program_that_isnt_an_engine(fake_engine: FakeEngine) -> None:
    with pytest.raises(EngineError, match="UCI"):
        probe(fake_engine("--exit"))


def test_engine_that_never_answers_times_out(fake_engine: FakeEngine) -> None:
    with pytest.raises(EngineError, match="didn't answer within 1 s"):
        probe(fake_engine("--silent"), timeout=1)


def test_missing_program(tmp_path: Path) -> None:
    with pytest.raises(EngineError, match="wasn't found"):
        probe([str(tmp_path / "no-such-stockfish")])


@pytest.mark.engine
def test_real_stockfish(stockfish_path: Path) -> None:
    info = probe([str(stockfish_path)])
    assert info.name.startswith("Stockfish")
