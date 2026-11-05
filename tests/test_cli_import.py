"""`blunderbook init`, `doctor` and `import`, against a temp config, a stubbed probe and a
scripted engine (no Stockfish needed)."""

import sys
from pathlib import Path
from typing import Any

import chess
import pytest
from typer.testing import CliRunner

from blunderbook import config
from blunderbook.cli import app
from blunderbook.core import engine
from blunderbook.core.engine import EngineError, EngineInfo, Line
from blunderbook.core.models import Eval

runner = CliRunner()
WINDOWS = sys.platform == "win32"
FIXTURES = Path(__file__).parent / "fixtures" / "pgn"
DOT = "\N{MIDDLE DOT}"


@pytest.fixture
def cfg_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "home" / "config.toml"
    monkeypatch.setattr(config, "config_path", lambda: path)
    monkeypatch.delenv(config.STOCKFISH_ENV, raising=False)
    monkeypatch.setattr("shutil.which", lambda _: None)
    return path


@pytest.fixture
def probes(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
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


# ---------------------------------------------------------------- init


def test_init_saves_names_and_stockfish(tmp_path: Path, cfg_file: Path, probes: list) -> None:
    exe = program(tmp_path / "sf")
    result = runner.invoke(app, ["init"], input=f" Rashed, rashed_blitz ,Rashed\n{exe}\n")
    assert result.exit_code == 0, result.output
    assert f"Creating {cfg_file}." in result.output
    assert f"Found Stockfish 17.1 at\n  {exe}" in result.output
    assert f"Saved to {cfg_file}" in result.output
    saved = config.load(cfg_file)
    assert saved.my_names == ("Rashed", "rashed_blitz")
    assert saved.stockfish_path == str(exe)


def test_init_enter_means_path(cfg_file: Path, probes: list) -> None:
    result = runner.invoke(app, ["init"], input="Rashed\n\n")
    assert result.exit_code == 0, result.output
    assert "No Stockfish on PATH yet" in result.output
    assert config.load(cfg_file).stockfish_path == ""


def test_init_finds_stockfish_on_path(
    tmp_path: Path, cfg_file: Path, probes: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    exe = program(tmp_path / "bin")
    monkeypatch.setattr("shutil.which", lambda _: str(exe))
    result = runner.invoke(app, ["init"], input="Rashed\n\n")
    assert result.exit_code == 0, result.output
    assert f"Found Stockfish 17.1 on PATH at\n  {exe}" in result.output
    assert config.load(cfg_file).stockfish_path == ""


def test_init_asks_again_after_a_bad_path(tmp_path: Path, cfg_file: Path, probes: list) -> None:
    exe = program(tmp_path / "sf")
    missing = tmp_path / "nowhere" / "stockfish.exe"
    result = runner.invoke(app, ["init"], input=f"Rashed\n{missing}\n{exe}\n")
    assert result.exit_code == 0, result.output
    assert f"Nothing found at {missing}." in result.output
    assert "Try again, or press Enter to look on PATH." in result.output
    assert config.load(cfg_file).stockfish_path == str(exe)


def test_init_rejects_a_program_that_isnt_stockfish(
    tmp_path: Path, cfg_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exe = program(tmp_path / "lc0", "lc0")

    def refuse(command: list[str], timeout: float = 10.0) -> EngineInfo:
        raise EngineError("This is Lc0, not Stockfish. Blunderbook only uses Stockfish.")

    monkeypatch.setattr(engine, "probe", refuse)
    result = runner.invoke(app, ["init"], input=f"Rashed\n{exe}\n\n")
    assert result.exit_code == 0, result.output
    assert "not Stockfish" in result.output
    assert config.load(cfg_file).stockfish_path == ""


def test_init_keeps_existing_values_on_enter(tmp_path: Path, cfg_file: Path, probes: list) -> None:
    exe = program(tmp_path / "sf")
    config.save(
        config.Config(my_names=("Rashed",), stockfish_path=str(exe), engine_depth=20), cfg_file
    )
    result = runner.invoke(app, ["init"], input="\n\n")
    assert result.exit_code == 0, result.output
    assert f"Updating {cfg_file}." in result.output
    saved = config.load(cfg_file)
    assert (saved.my_names, saved.stockfish_path, saved.engine_depth) == (("Rashed",), str(exe), 20)


def test_init_without_names(cfg_file: Path, probes: list) -> None:
    result = runner.invoke(app, ["init"], input=" , \n\n")
    assert result.exit_code == 0, result.output
    assert "No names set. Every game will ask which side you played." in result.output
    assert config.load(cfg_file).my_names == ()


# ---------------------------------------------------------------- doctor


def test_doctor_all_good(tmp_path: Path, cfg_file: Path, probes: list) -> None:
    exe = program(tmp_path / "sf")
    config.save(config.Config(my_names=("Rashed",), stockfish_path=str(exe)), cfg_file)
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    out = result.output
    assert f"Config     {cfg_file}" in out
    assert "Names      Rashed" in out
    assert "Stockfish  Stockfish 17.1" in out
    assert f"           {exe}" in out
    assert "           from config.toml (stockfish_path)" in out
    assert f"Analysis   depth 16 {DOT} 2 threads {DOT} 128 MB hash" in out
    assert "Database   not used yet" in out
    assert out.rstrip().endswith("No problems found.")


def test_doctor_with_nothing_set_up(cfg_file: Path, probes: list) -> None:
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "Config     not created yet. Run blunderbook init." in result.output
    assert "Names      none set." in result.output
    assert "Stockfish  Problem: No Stockfish found." in result.output
    assert "1 problem found." in result.output
    assert probes == []


def test_doctor_reports_a_broken_config_and_carries_on(cfg_file: Path, probes: list) -> None:
    cfg_file.parent.mkdir(parents=True)
    cfg_file.write_text("engine_depth = 0\n", "utf-8")
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "Config     Problem in " in result.output
    assert "engine_depth" in result.output
    assert "2 problems found." in result.output  # the config, and no Stockfish


def test_doctor_stockfish_option(tmp_path: Path, cfg_file: Path, probes: list) -> None:
    exe = program(tmp_path / "other")
    result = runner.invoke(app, ["doctor", "--stockfish", str(exe)])
    assert result.exit_code == 0, result.output
    assert "from the --stockfish option" in result.output
    assert probes == [[str(exe)]]


def test_doctor_engine_that_fails_its_check(
    tmp_path: Path, cfg_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exe = program(tmp_path / "sf")

    def broken(command: list[str], timeout: float = 10.0) -> EngineInfo:
        raise EngineError("It didn't respond like a UCI chess engine.")

    monkeypatch.setattr(engine, "probe", broken)
    result = runner.invoke(app, ["doctor", "--stockfish", str(exe)])
    assert result.exit_code == 1
    assert f"Stockfish  Problem: Can't use {exe}: It didn't respond" in result.output


# ---------------------------------------------------------------- import


class StubEngine:
    """Stands in for engine.Engine: scripted scores keyed by FEN, cp 20 elsewhere."""

    name = "Stockfish 17.1"
    info = EngineInfo("Stockfish 17.1", 17, 1)

    def __init__(self, table: dict[str, Line] | None = None, fail: bool = False) -> None:
        self.table = table or {}
        self.fail = fail
        self.depths: set[int] = set()
        self.opened_with: dict[str, Any] = {}
        self.closed = False

    def lines(
        self, board: chess.Board, depth: int, multipv: int = 1, *, game: object = None
    ) -> list[Line]:
        if self.fail:
            raise EngineError("Stockfish stopped unexpectedly.")
        self.depths.add(depth)
        return [self.table.get(board.fen(), Line(Eval(cp=20)))]

    def __enter__(self) -> StubEngine:
        return self

    def __exit__(self, *exc: object) -> None:
        self.closed = True


@pytest.fixture
def stub(monkeypatch: pytest.MonkeyPatch) -> StubEngine:
    elephant = "r1bqkb1r/pppn1ppp/5n2/3p2B1/3P4/2N5/PP2PPPP/R2QKBNR w KQkq - 0 6"
    after = "r1bqkb1r/pppn1ppp/5n2/3N2B1/3P4/8/PP2PPPP/R2QKBNR b KQkq - 0 6"
    sf = StubEngine(
        {
            elephant: Line(Eval(cp=36), tuple(map(chess.Move.from_uci, ["e2e3", "f8e7"]))),
            after: Line(Eval(cp=-409), (chess.Move.from_uci("f6d5"),)),
        }
    )

    def fake_open(command: list[str], **settings: Any) -> StubEngine:
        sf.opened_with = {"command": command, **settings}
        return sf

    monkeypatch.setattr(engine.Engine, "open", staticmethod(fake_open))
    return sf


@pytest.fixture
def ready(tmp_path: Path, cfg_file: Path) -> Path:
    """A config with your name and a (fake) Stockfish program."""
    exe = program(tmp_path / "sf")
    config.save(config.Config(my_names=("Rashed",), stockfish_path=str(exe)), cfg_file)
    return exe


def test_import_prints_the_blunder(ready: Path, stub: StubEngine) -> None:
    result = runner.invoke(app, ["import", str(FIXTURES / "qgd_elephant.pgn")])
    assert result.exit_code == 0, result.output
    out = result.output
    assert "Analysing with Stockfish 17.1 at depth 16." in out
    assert (
        f"Game 1 {DOT} Rashed vs Karim S. {DOT} 2026-10-12 {DOT} PGN file {DOT} you played White"
        in out
    )
    assert "No clock times in this PGN." in out
    assert "6. Nxd5??  Best was e3: 6. e3 Be7" in out
    assert "Refutation: 6... Nxd5" in out
    assert f"1 game read {DOT} 1 blunder found" in out
    assert "Nothing was saved: storage arrives in M2." in out
    assert stub.closed
    assert stub.opened_with == {
        "command": [str(ready)],
        "threads": 2,
        "hash_mb": 128,
    }


def test_import_depth_option(ready: Path, stub: StubEngine) -> None:
    result = runner.invoke(app, ["import", str(FIXTURES / "qgd_elephant.pgn"), "--depth", "9"])
    assert result.exit_code == 0, result.output
    assert "at depth 9." in result.output
    assert stub.depths == {9}


def test_import_multi_game_report(ready: Path, stub: StubEngine) -> None:
    result = runner.invoke(app, ["import", str(FIXTURES / "multi_game.pgn")])
    assert result.exit_code == 0, result.output
    out = result.output
    assert "Illegal move 2. Ke3" in out
    assert "Which side were you? Run again with --side white or --side black," in out
    assert "No blunders found." in out
    assert f"4 games read {DOT} 1 needs side {DOT} 1 error {DOT} 0 blunders found" in out


def test_import_side_option(ready: Path, stub: StubEngine) -> None:
    path = FIXTURES / "chesscom_unmatched_name.pgn"
    result = runner.invoke(app, ["import", str(path), "--side", "black"])
    assert result.exit_code == 0, result.output
    assert "you played Black (from --side)" in result.output


def test_import_bad_side_value(ready: Path, stub: StubEngine) -> None:
    result = runner.invoke(app, ["import", str(FIXTURES / "qgd_elephant.pgn"), "--side", "red"])
    assert result.exit_code == 2


def test_import_doesnt_start_the_engine_without_ready_games(
    cfg_file: Path, stub: StubEngine
) -> None:
    result = runner.invoke(app, ["import", str(FIXTURES / "chesscom_unmatched_name.pgn")])
    assert result.exit_code == 0, result.output  # no Stockfish set up, and none needed
    assert f"1 game read {DOT} 1 needs side {DOT} 0 blunders found" in result.output
    assert stub.opened_with == {}
    assert "Nothing was saved" not in result.output


def test_import_without_stockfish(cfg_file: Path, stub: StubEngine) -> None:
    config.save(config.Config(my_names=("Rashed",)), cfg_file)
    result = runner.invoke(app, ["import", str(FIXTURES / "qgd_elephant.pgn")])
    assert result.exit_code == 1
    assert "Can't analyse: No Stockfish found." in result.output
    assert stub.opened_with == {}


def test_import_stockfish_option(tmp_path: Path, ready: Path, stub: StubEngine) -> None:
    other = program(tmp_path / "other")
    path = str(FIXTURES / "qgd_elephant.pgn")
    result = runner.invoke(app, ["import", path, "--stockfish", str(other)])
    assert result.exit_code == 0, result.output
    assert stub.opened_with["command"] == [str(other)]


def test_import_engine_failure_reports_and_stops(ready: Path, stub: StubEngine) -> None:
    stub.fail = True
    result = runner.invoke(app, ["import", str(FIXTURES / "qgd_elephant.pgn")])
    assert result.exit_code == 1
    assert "Not analysed." in result.output
    assert "Analysis stopped: Stockfish stopped unexpectedly." in result.output
    assert stub.closed


def test_import_windows_1252_file(tmp_path: Path, ready: Path, stub: StubEngine) -> None:
    path = tmp_path / "club.pgn"
    path.write_bytes(
        '[White "Rashed"]\n[Black "Jos\N{LATIN SMALL LETTER E WITH ACUTE}"]\n\n1. e4 e5 *\n'.encode(
            "cp1252"
        )
    )
    result = runner.invoke(app, ["import", str(path)])
    assert result.exit_code == 0, result.output
    assert "Read as Windows-1252 (the file isn't UTF-8)." in result.output
    assert "Rashed vs Jos\N{LATIN SMALL LETTER E WITH ACUTE}" in result.output


def test_import_missing_file(tmp_path: Path, cfg_file: Path) -> None:
    result = runner.invoke(app, ["import", str(tmp_path / "nope.pgn")])
    assert result.exit_code == 1
    assert "Can't read" in result.output


def test_import_file_with_no_games(tmp_path: Path, cfg_file: Path) -> None:
    path = tmp_path / "empty.pgn"
    path.write_text("\n", "utf-8")
    result = runner.invoke(app, ["import", str(path)])
    assert result.exit_code == 1
    assert f"No games found in {path}." in result.output
