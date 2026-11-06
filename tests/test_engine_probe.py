import shlex
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from blunderbook.core import engine
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


def test_a_blocked_download_on_a_mac_says_how_to_fix_it(
    fake_engine: FakeEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[str] = []
    monkeypatch.setattr(engine, "quarantined", lambda p: asked.append(p) or True)
    command = fake_engine("--silent")
    with pytest.raises(EngineError) as caught:
        probe(command, timeout=1)
    assert asked == [command[0]]
    message = str(caught.value)
    assert message.startswith("macOS blocked it")
    assert "brew install stockfish" in message
    assert "blunderbook engine clear" in message
    assert f"xattr -d com.apple.quarantine {shlex.quote(command[0])}" in message
    assert "Open Anyway" in message


def test_the_fix_quotes_a_path_with_spaces() -> None:
    message = engine.macos_blocked("/Users/me/My Stockfish/stockfish")
    assert "xattr -d com.apple.quarantine '/Users/me/My Stockfish/stockfish'" in message


def test_a_program_that_isnt_marked_gets_the_usual_reason(
    fake_engine: FakeEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(engine, "quarantined", lambda p: False)
    with pytest.raises(EngineError, match="UCI"):
        probe(fake_engine("--exit"))


def test_a_missing_program_isnt_checked_for_the_mark(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(engine, "quarantined", lambda p: pytest.fail("checked"))
    with pytest.raises(EngineError, match="wasn't found"):
        probe([str(tmp_path / "no-such-stockfish")])


def test_only_macos_has_the_mark(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine.sys, "platform", "linux")
    assert not engine.quarantined(str(tmp_path))


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
def test_reads_the_mark_on_macos(tmp_path: Path) -> None:
    program = tmp_path / "stockfish"
    program.write_text("")
    assert not engine.quarantined(str(program))
    mark = "0081;00000000;Chrome;"
    subprocess.run(["/usr/bin/xattr", "-w", "com.apple.quarantine", mark, program], check=True)
    assert engine.quarantined(str(program))
    assert not engine.quarantined(str(tmp_path / "missing"))


@pytest.mark.engine
def test_real_stockfish(stockfish_path: Path) -> None:
    info = probe([str(stockfish_path)])
    assert info.name.startswith("Stockfish")
