"""`blunderbook init`, `doctor`, `import` and `fen`, against a temp config, a stubbed probe
and a scripted engine (no Stockfish needed). Includes their backup steps: the init prompt,
doctor's Backups row, the daily backup and the backup before an upgrade."""

import re
import sqlite3
import sys
from contextlib import closing
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import chess
import pytest
from conftest import LATEST, with_next_migration
from typer.testing import CliRunner

from blunderbook import config
from blunderbook.cli import app
from blunderbook.core import engine, pgn
from blunderbook.core.engine import EngineError, EngineInfo, Line
from blunderbook.core.models import Eval
from blunderbook.db import backup, connection, repo

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
    monkeypatch.delenv("ONEDRIVE", raising=False)
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


def newer_db(path: Path) -> None:
    """A database from a future Blunderbook (schema 99)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, autocommit=True)) as conn:
        conn.execute("CREATE TABLE games (id INTEGER PRIMARY KEY)")
        conn.execute("PRAGMA user_version = 99")


# ---------------------------------------------------------------- init


def test_init_saves_names_and_stockfish(tmp_path: Path, cfg_file: Path, probes: list) -> None:
    exe = program(tmp_path / "sf")
    result = runner.invoke(app, ["init"], input=f" Rashed, rashed_blitz ,Rashed\n{exe}\n\n\n\n")
    assert result.exit_code == 0, result.output
    assert f"Creating {cfg_file}." in result.output
    assert f"Found Stockfish 17.1 at\n  {exe}" in result.output
    assert f"Saved to {cfg_file}" in result.output
    saved = config.load(cfg_file)
    assert saved.my_names == ("Rashed", "rashed_blitz")
    assert saved.stockfish_path == str(exe)


def test_init_enter_means_path(cfg_file: Path, probes: list) -> None:
    result = runner.invoke(app, ["init"], input="Rashed\n\n\n\n\n")
    assert result.exit_code == 0, result.output
    assert "No Stockfish on PATH yet" in result.output
    assert config.load(cfg_file).stockfish_path == ""


def test_init_finds_stockfish_on_path(
    tmp_path: Path, cfg_file: Path, probes: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    exe = program(tmp_path / "bin")
    monkeypatch.setattr("shutil.which", lambda _: str(exe))
    result = runner.invoke(app, ["init"], input="Rashed\n\n\n\n\n")
    assert result.exit_code == 0, result.output
    assert f"Found Stockfish 17.1 on PATH at\n  {exe}" in result.output
    assert config.load(cfg_file).stockfish_path == ""


def test_init_asks_again_after_a_bad_path(tmp_path: Path, cfg_file: Path, probes: list) -> None:
    exe = program(tmp_path / "sf")
    missing = tmp_path / "nowhere" / "stockfish.exe"
    result = runner.invoke(app, ["init"], input=f"Rashed\n{missing}\n{exe}\n\n\n\n")
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
    result = runner.invoke(app, ["init"], input=f"Rashed\n{exe}\n\n\n\n\n")
    assert result.exit_code == 0, result.output
    assert "not Stockfish" in result.output
    assert config.load(cfg_file).stockfish_path == ""


def test_init_keeps_existing_values_on_enter(tmp_path: Path, cfg_file: Path, probes: list) -> None:
    exe = program(tmp_path / "sf")
    config.save(
        config.Config(my_names=("Rashed",), stockfish_path=str(exe), engine_depth=20), cfg_file
    )
    result = runner.invoke(app, ["init"], input="\n\n\n\n\n")
    assert result.exit_code == 0, result.output
    assert f"Updating {cfg_file}." in result.output
    saved = config.load(cfg_file)
    assert (saved.my_names, saved.stockfish_path, saved.engine_depth) == (("Rashed",), str(exe), 20)


def test_init_without_names(cfg_file: Path, probes: list) -> None:
    result = runner.invoke(app, ["init"], input=" , \n\n\n\n\n")
    assert result.exit_code == 0, result.output
    assert "No names set. Every game will ask which side you played." in result.output
    assert config.load(cfg_file).my_names == ()


def test_init_creates_the_database(cfg_file: Path, db_file: Path, probes: list) -> None:
    result = runner.invoke(app, ["init"], input="Rashed\n\n\n\n\n")
    assert result.exit_code == 0, result.output
    assert f"Created the database {db_file}\nNext: blunderbook import FILE.pgn" in result.output
    with closing(connection.connect(db_file, mode="ro")) as conn:
        assert connection.user_version(conn) == connection.latest_version()


def test_init_again_keeps_the_data(cfg_file: Path, db_file: Path, probes: list) -> None:
    assert runner.invoke(app, ["init"], input="Rashed\n\n\n\n\n").exit_code == 0
    with closing(connection.open_db(db_file)) as conn:
        conn.execute("INSERT INTO sync_state (source, username) VALUES ('lichess', 'rashed')")
    result = runner.invoke(app, ["init"], input="\n\n\n\n\n")
    assert result.exit_code == 0, result.output
    assert f"Database {db_file}\n" in result.output
    with closing(connection.open_db(db_file)) as conn:
        assert conn.execute("SELECT username FROM sync_state").fetchone()[0] == "rashed"


def test_init_with_a_database_from_a_newer_app(cfg_file: Path, db_file: Path, probes: list) -> None:
    newer_db(db_file)
    result = runner.invoke(app, ["init"], input="Rashed\n\n\n\n\n")
    assert result.exit_code == 1
    assert "Your settings are saved, but the database isn't ready." in result.output
    assert "made by a newer Blunderbook (schema 99;" in result.output
    assert config.load(cfg_file).my_names == ("Rashed",)


# ---------------------------------------------------------------- doctor


def test_doctor_all_good(tmp_path: Path, cfg_file: Path, db_file: Path, probes: list) -> None:
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
    assert f"Database   {db_file}\n           not created yet. Run blunderbook init." in out
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


def test_doctor_checks_the_database(
    tmp_path: Path, cfg_file: Path, db_file: Path, probes: list
) -> None:
    with closing(connection.open_db(db_file, create=True)):
        pass
    result = runner.invoke(app, ["doctor", "--stockfish", str(program(tmp_path / "sf"))])
    assert result.exit_code == 0, result.output
    latest = connection.latest_version()
    assert f"Database   {db_file}\n           schema {latest} {DOT} integrity ok\n" in result.output


def test_doctor_doesnt_create_or_upgrade_the_database(
    tmp_path: Path, cfg_file: Path, db_file: Path, probes: list
) -> None:
    exe = str(program(tmp_path / "sf"))
    assert runner.invoke(app, ["doctor", "--stockfish", exe]).exit_code == 0
    assert not db_file.parent.exists()
    db_file.parent.mkdir()
    db_file.write_bytes(b"")  # an empty file is a database at schema 0
    result = runner.invoke(app, ["doctor", "--stockfish", exe])
    assert result.exit_code == 0, result.output
    assert f"schema 0 {DOT} integrity ok" in result.output
    assert "Note: run blunderbook init to upgrade it to schema" in result.output
    assert db_file.read_bytes() == b""


def test_doctor_database_from_a_newer_app(
    tmp_path: Path, cfg_file: Path, db_file: Path, probes: list
) -> None:
    newer_db(db_file)
    result = runner.invoke(app, ["doctor", "--stockfish", str(program(tmp_path / "sf"))])
    assert result.exit_code == 1
    assert "           Problem: The database was made by a newer Blunderbook" in result.output
    assert "1 problem found." in result.output


def test_doctor_file_that_isnt_a_database(
    tmp_path: Path, cfg_file: Path, db_file: Path, probes: list
) -> None:
    db_file.parent.mkdir()
    db_file.write_bytes(b"x" * 4096)
    result = runner.invoke(app, ["doctor", "--stockfish", str(program(tmp_path / "sf"))])
    assert result.exit_code == 1
    assert f"           Problem: {db_file} isn't a SQLite database." in result.output


# ---------------------------------------------------------------- import


class StubEngine:
    """Stands in for engine.Engine: scripted scores keyed by FEN, cp 20 elsewhere."""

    name = "Stockfish 17.1"
    info = EngineInfo("Stockfish 17.1", 17, 1)

    def __init__(self, table: dict[str, Line] | None = None, fail: bool = False) -> None:
        self.table = table or {}
        self.fail = fail
        self.fail_after: int | None = None  # positions analysed before it stops
        self.positions = 0
        self.depths: set[int] = set()
        self.opened_with: dict[str, Any] = {}
        self.closed = False

    def lines(
        self, board: chess.Board, depth: int, multipv: int = 1, *, game: object = None
    ) -> list[Line]:
        self.positions += 1
        if self.fail or (self.fail_after is not None and self.positions > self.fail_after):
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
    assert f"{DOT} entry #1\n" in out
    assert f"1 game read {DOT} 1 blunder added" in out
    assert import_labels() == [("qgd_elephant.pgn", "file")]  # for the Games tab
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
    assert f"4 games read {DOT} 1 needs side {DOT} 1 error {DOT} 0 blunders added" in out


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
    assert f"1 game read {DOT} 1 needs side {DOT} 0 blunders added" in result.output
    assert stub.opened_with == {}


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


def entries(db_file: Path) -> list[tuple[str, str]]:
    """(players, move played) for every saved entry, oldest first."""
    with closing(connection.open_db(db_file)) as conn:
        return [
            (f"{e.game.white} vs {e.game.black}", e.blunder.played_san)
            for e in reversed(repo.list_entries(conn))
        ]


def saved_games(db_file: Path) -> int:
    with closing(connection.open_db(db_file)) as conn:
        return len(repo.known_fingerprints(conn))


def test_import_saves_and_a_second_import_adds_nothing(
    ready: Path, stub: StubEngine, db_file: Path
) -> None:
    path = str(FIXTURES / "qgd_elephant.pgn")
    first = runner.invoke(app, ["import", path])
    assert first.exit_code == 0, first.output
    assert f"Created the database {db_file}" in first.output
    assert entries(db_file) == [("Rashed vs Karim S.", "Nxd5")]

    stub.opened_with = {}
    again = runner.invoke(app, ["import", path])
    assert again.exit_code == 0, again.output
    assert "Created the database" not in again.output
    assert "  Already imported \N{EM DASH} skipped" in again.output
    assert f"1 game read {DOT} 1 skipped (duplicate) {DOT} 0 blunders added" in again.output
    assert stub.opened_with == {}  # nothing left to analyse
    assert entries(db_file) == [("Rashed vs Karim S.", "Nxd5")]


def test_games_without_blunders_are_saved_too(ready: Path, stub: StubEngine, db_file: Path) -> None:
    path = str(FIXTURES / "multi_game.pgn")
    assert runner.invoke(app, ["import", path]).exit_code == 0
    assert saved_games(db_file) == 2  # the two games your name matched; no blunders in either
    again = runner.invoke(app, ["import", path])
    assert f"4 games read {DOT} 2 skipped (duplicate) {DOT} 1 needs side" in again.output


def test_a_game_that_needs_a_side_is_saved_once_you_give_it(
    ready: Path, stub: StubEngine, db_file: Path
) -> None:
    path = str(FIXTURES / "chesscom_unmatched_name.pgn")
    assert runner.invoke(app, ["import", path]).exit_code == 0
    assert saved_games(db_file) == 0
    result = runner.invoke(app, ["import", path, "--side", "black"])
    assert result.exit_code == 0, result.output
    assert saved_games(db_file) == 1


def test_engine_failure_keeps_the_games_already_saved(
    ready: Path, stub: StubEngine, db_file: Path
) -> None:
    path = str(FIXTURES / "multi_game.pgn")
    (first, *_) = pgn.parse((FIXTURES / "multi_game.pgn").read_text("utf-8")).games
    stub.fail_after = len(first.plies) + 1  # game 1 finishes, game 3 fails
    result = runner.invoke(app, ["import", path])
    assert result.exit_code == 1
    assert "No blunders found." in result.output  # game 1, saved
    assert "Not analysed." in result.output  # game 3
    assert "Analysis stopped: Stockfish stopped unexpectedly." in result.output
    assert "Import the file again to analyse the rest." in result.output
    assert saved_games(db_file) == 1

    stub.fail_after = None
    again = runner.invoke(app, ["import", path])
    assert again.exit_code == 0, again.output
    assert "1 skipped (duplicate)" in again.output
    assert saved_games(db_file) == 2


def test_import_refuses_a_database_from_a_newer_app(
    ready: Path, stub: StubEngine, db_file: Path
) -> None:
    newer_db(db_file)
    result = runner.invoke(app, ["import", str(FIXTURES / "qgd_elephant.pgn")])
    assert result.exit_code == 1
    assert "Can't import: the database can't be used." in result.output
    assert "made by a newer Blunderbook" in result.output
    assert stub.opened_with == {}


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


# ---------------------------------------------------------------- fen

BACK_RANK = "3r2k1/4qppp/8/8/8/1Q6/5PPP/2R3K1 w - - 0 32"


def score(stub: StubEngine, fen: str, eval_: Eval, *pv: str) -> None:
    """Script the engine's answer for ``fen``."""
    stub.table[chess.Board(fen).fen()] = Line(eval_, tuple(map(chess.Move.from_uci, pv)))


def after(fen: str, uci: str) -> str:
    board = chess.Board(fen)
    board.push_uci(uci)
    return board.fen()


def back_rank(stub: StubEngine, after_rc7: Eval, *pv: str) -> None:
    score(stub, BACK_RANK, Eval(cp=30), "b3c4", "g7g6")
    score(stub, after(BACK_RANK, "c1c7"), after_rc7, *pv)


def fen(*args: str) -> Any:
    return runner.invoke(app, ["fen", BACK_RANK, *args])


def test_fen_logs_a_blunder(ready: Path, stub: StubEngine, db_file: Path) -> None:
    back_rank(stub, Eval(mate=-1), "e7e1")
    result = fen("--move", "Rc7", "--opponent", "endgame_eel", "--date", "2026-11-01")
    assert result.exit_code == 0, result.output
    out = result.output
    assert f"FEN entry {DOT} Rashed vs endgame_eel {DOT} 2026-11-01 {DOT} you played White" in out
    assert "  32. Rc7??  Best was Qc4: 32. Qc4 g6" in out
    assert "      Refutation: 32... Qe1#" in out
    assert "      Suggested: Missed their threat" in out
    assert "No clock times" not in out
    assert out.rstrip().endswith("Logged 32. Rc7?? as a blunder: entry #1.")
    with closing(connection.open_db(db_file)) as conn:
        (entry,) = repo.list_entries(conn)
    assert (entry.game.source, entry.game.site_label, entry.game.start_fen) == (
        "fen",
        "FEN entry",
        BACK_RANK,
    )
    assert (entry.game.black, entry.game.played_on.isoformat()) == ("endgame_eel", "2026-11-01")
    assert (entry.blunder.judgment, entry.blunder.played_uci) == ("blunder", "c1c7")


def test_fen_logs_a_mistake_too(ready: Path, stub: StubEngine) -> None:
    back_rank(stub, Eval(cp=-100), "e7c7")
    result = fen("--move", "c1c7")
    assert result.exit_code == 0, result.output
    assert "  32. Rc7?  Best was Qc4" in result.output
    assert "Logged 32. Rc7? as a mistake: entry #1." in result.output


def test_fen_twice_adds_nothing(ready: Path, stub: StubEngine, db_file: Path) -> None:
    back_rank(stub, Eval(mate=-1), "e7e1")
    assert fen("--move", "Rc7", "--date", "2026-11-01").exit_code == 0
    stub.opened_with = {}
    again = fen("--move", "c1c7", "--date", "2026-11-01")
    assert again.exit_code == 0, again.output
    assert "You've already logged 32. Rc7 in this position (entry #1). Nothing was added." in (
        again.output
    )
    assert stub.opened_with == {}
    assert entries(db_file) == [("Rashed vs None", "Rc7")]


def test_fen_move_that_isnt_a_mistake(ready: Path, stub: StubEngine, db_file: Path) -> None:
    back_rank(stub, Eval(cp=25), "g7g6")
    result = fen("--move", "Rc7")
    assert result.exit_code == 0, result.output
    assert "32. Rc7 isn't a mistake by Stockfish's measure (swing 0.00; " in result.output
    assert "inaccuracies start at 0.05). Nothing was logged." in result.output
    assert entries(db_file) == []
    assert saved_games(db_file) == 0  # not saved, so you can log it again later


def test_fen_best_move_isnt_logged(ready: Path, stub: StubEngine, db_file: Path) -> None:
    score(stub, BACK_RANK, Eval(cp=30), "b3c4")
    score(stub, after(BACK_RANK, "b3c4"), Eval(cp=-100))  # a big swing, but it's the best
    result = fen("--move", "Qc4")
    assert result.exit_code == 0, result.output
    assert "32. Qc4 is Stockfish's own choice here. Nothing was logged." in result.output
    assert entries(db_file) == []


def test_fen_date_defaults_to_today(ready: Path, stub: StubEngine) -> None:
    back_rank(stub, Eval(mate=-1), "e7e1")
    result = fen("--move", "Rc7")
    assert result.exit_code == 0, result.output
    assert f"Rashed vs ? {DOT} {date.today().isoformat()} {DOT}" in result.output


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["fen", "8/8/8/8/8/8/8/K7 w - - 0 1", "--move", "a1a2"], "Black has no king"),
        (["fen", BACK_RANK, "--move", "e1e2"], "e1e2 isn't a legal move in that position."),
        (["fen", BACK_RANK, "--move", "Rc7", "--date", "1/11/2026"], "--date needs a date like"),
    ],
)
def test_fen_bad_input_stops_before_anything_else(
    ready: Path, stub: StubEngine, db_file: Path, args: list[str], message: str
) -> None:
    result = runner.invoke(app, args)
    assert result.exit_code == 1
    assert message in result.output
    assert stub.opened_with == {}
    assert not db_file.exists()


def test_fen_needs_the_move(ready: Path, stub: StubEngine) -> None:
    assert fen().exit_code == 2


def test_fen_engine_failure_logs_nothing(ready: Path, stub: StubEngine, db_file: Path) -> None:
    stub.fail = True
    result = fen("--move", "Rc7")
    assert result.exit_code == 1
    assert "Analysis stopped: Stockfish stopped unexpectedly.\nNothing was logged." in result.output
    assert saved_games(db_file) == 0
    assert stub.closed


# ---------------------------------------------------------------- backups: init


def test_init_asks_for_the_backup_folder(
    tmp_path: Path, cfg_file: Path, db_file: Path, probes: list
) -> None:
    target = tmp_path / "cloud" / "Blunderbook"
    result = runner.invoke(app, ["init"], input=f"Rashed\n\n{target}\n\n\n")
    assert result.exit_code == 0, result.output
    default = db_file.parent / "backups"
    assert f"Press Enter to keep them in\n  {default}\nor give a folder." in result.output
    assert "OneDrive" not in result.output
    assert f"Backups go to {target}\n" in result.output
    assert target.is_dir()
    assert config.load(cfg_file).backup.dir == str(target)


def test_init_enter_keeps_backups_next_to_the_database(cfg_file: Path, probes: list) -> None:
    result = runner.invoke(app, ["init"], input="Rashed\n\n\n\n\n")
    assert result.exit_code == 0, result.output
    assert "Backups go to" not in result.output
    assert config.load(cfg_file).backup == config.BackupConfig()


@pytest.mark.skipif(not WINDOWS, reason="%OneDrive% is a Windows variable")
def test_init_suggests_onedrive(
    tmp_path: Path, cfg_file: Path, probes: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OneDrive", str(tmp_path / "OneDrive"))
    result = runner.invoke(app, ["init"], input="Rashed\n\n%OneDrive%\\Blunderbook\n\n\n")
    assert result.exit_code == 0, result.output
    assert "OneDrive is set up here, so %OneDrive%\\Blunderbook works." in result.output
    assert config.load(cfg_file).backup.dir == "%OneDrive%\\Blunderbook"  # kept portable
    assert (tmp_path / "OneDrive" / "Blunderbook").is_dir()


def test_init_asks_again_for_a_bad_backup_folder(
    cfg_file: Path, db_file: Path, probes: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BB_MISSING", raising=False)
    answers = f"Rashed\n\n$BB_MISSING/bk\n{db_file.parent}\n\n\n\n"
    result = runner.invoke(app, ["init"], input=answers)
    assert result.exit_code == 0, result.output
    assert "backup.dir uses $BB_MISSING, which isn't set on this computer" in result.output
    assert "That's the database's own folder. Pick another, or press Enter." in result.output
    assert config.load(cfg_file).backup.dir == ""


def test_init_keeps_the_backup_folder_on_enter(
    tmp_path: Path, cfg_file: Path, probes: list
) -> None:
    target = str(tmp_path / "bk")
    config.save(
        config.Config(my_names=("Rashed",), backup=config.BackupConfig(dir=target)), cfg_file
    )
    result = runner.invoke(app, ["init"], input="\n\n\n\n\n")
    assert result.exit_code == 0, result.output
    assert f"Backup folder [{target}]:" in result.output
    assert config.load(cfg_file).backup.dir == target


# ---------------------------------------------------------------- backups: doctor


def doctor_with_stockfish(tmp_path: Path) -> Any:
    return runner.invoke(app, ["doctor", "--stockfish", str(program(tmp_path / "sf"))])


def database_with_a_backup(db_file: Path, age: timedelta) -> None:
    with closing(connection.open_db(db_file, create=True)):
        pass
    backup.take(db_file, db_file.parent / "backups", keep=14, now=datetime.now(UTC) - age)


def test_doctor_backups_none_yet(
    tmp_path: Path, cfg_file: Path, db_file: Path, probes: list
) -> None:
    result = doctor_with_stockfish(tmp_path)
    assert result.exit_code == 0, result.output
    assert f"Backups    {db_file.parent / 'backups'}\n           none yet.\n" in result.output
    with closing(connection.open_db(db_file, create=True)):
        pass
    result = doctor_with_stockfish(tmp_path)
    assert "           none yet. Run blunderbook backup to take one.\n" in result.output


def test_doctor_shows_the_last_backup(
    tmp_path: Path, cfg_file: Path, db_file: Path, probes: list
) -> None:
    database_with_a_backup(db_file, timedelta(hours=3, minutes=5))
    result = doctor_with_stockfish(tmp_path)
    assert result.exit_code == 0, result.output
    assert f" (3 hours ago) {DOT} 1 backup kept\n" in result.output
    assert "Warning" not in result.output
    assert result.output.rstrip().endswith("No problems found.")


def test_doctor_warns_about_an_old_backup(
    tmp_path: Path, cfg_file: Path, db_file: Path, probes: list
) -> None:
    database_with_a_backup(db_file, timedelta(days=8, hours=1))
    result = doctor_with_stockfish(tmp_path)
    assert result.exit_code == 0, result.output
    assert f" (8 days ago) {DOT} 1 backup kept\n" in result.output
    assert "           Warning: the last backup is 8 days old.\n" in result.output
    assert result.output.rstrip().endswith("No problems found. 1 warning.")


def test_doctor_warns_about_a_missing_folder(tmp_path: Path, cfg_file: Path, probes: list) -> None:
    gone = tmp_path / "gone"
    config.save(config.Config(backup=config.BackupConfig(dir=str(gone), auto=False)), cfg_file)
    result = doctor_with_stockfish(tmp_path)
    assert result.exit_code == 0, result.output
    assert f"Backups    {gone}\n           Warning: this folder doesn't exist." in result.output
    assert "Daily backups are off ([backup] auto in config.toml)." in result.output
    assert not gone.exists()  # doctor changes nothing


def test_doctor_backup_folder_with_an_unset_variable(
    tmp_path: Path, cfg_file: Path, probes: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BB_MISSING", raising=False)
    config.save(config.Config(backup=config.BackupConfig(dir="$BB_MISSING/bk")), cfg_file)
    result = doctor_with_stockfish(tmp_path)
    assert result.exit_code == 1
    assert "Backups    Problem: backup.dir uses $BB_MISSING" in result.output
    assert "1 problem found." in result.output


# ---------------------------------------------------------------- backups: import, fen


def backups(db_file: Path) -> list[backup.Backup]:
    return backup.list_backups(db_file.parent / "backups")


def set_backup(cfg_file: Path, **changes: Any) -> None:
    cfg = config.load(cfg_file)
    config.save(replace(cfg, backup=replace(cfg.backup, **changes)), cfg_file)


def import_fixture(name: str) -> Any:
    return runner.invoke(app, ["import", str(FIXTURES / name), "--side", "white"])


def test_import_takes_the_daily_backup_first(ready: Path, stub: StubEngine, db_file: Path) -> None:
    first = import_fixture("qgd_elephant.pgn")
    assert first.exit_code == 0, first.output
    assert "Daily backup" not in first.output  # nothing to back up yet
    assert backups(db_file) == []

    second = import_fixture("blackburne_shilling.pgn")
    assert second.exit_code == 0, second.output
    (made,) = backups(db_file)
    assert f"Daily backup: {made.path}\n" in second.output
    with closing(connection.connect(made.path, mode="ro")) as conn:
        assert len(repo.known_fingerprints(conn)) == 1  # taken before this import

    third = import_fixture("legal_trap.pgn")
    assert third.exit_code == 0, third.output
    assert "Daily backup" not in third.output  # one a day
    assert len(backups(db_file)) == 1
    assert saved_games(db_file) == 3


def test_daily_backup_off(ready: Path, stub: StubEngine, db_file: Path, cfg_file: Path) -> None:
    set_backup(cfg_file, auto=False)
    assert import_fixture("qgd_elephant.pgn").exit_code == 0
    result = import_fixture("blackburne_shilling.pgn")
    assert result.exit_code == 0, result.output
    assert "Daily backup" not in result.output
    assert backups(db_file) == []


def test_a_failed_daily_backup_doesnt_stop_the_import(
    tmp_path: Path, ready: Path, stub: StubEngine, db_file: Path, cfg_file: Path
) -> None:
    blocker = tmp_path / "a file"
    blocker.write_bytes(b"")
    set_backup(cfg_file, dir=str(blocker / "bk"))
    assert import_fixture("qgd_elephant.pgn").exit_code == 0
    result = import_fixture("blackburne_shilling.pgn")
    assert result.exit_code == 0, result.output
    # Some systems fail when the folder is created, macOS already when it is listed.
    assert re.search(
        r"Warning: the daily backup didn't work: Can't (create|read) the backup folder",
        result.output,
    )
    assert saved_games(db_file) == 2


def test_fen_takes_the_daily_backup_first(ready: Path, stub: StubEngine, db_file: Path) -> None:
    assert import_fixture("qgd_elephant.pgn").exit_code == 0
    back_rank(stub, Eval(mate=-1), "e7e1")
    result = fen("--move", "Rc7")
    assert result.exit_code == 0, result.output
    (made,) = backups(db_file)
    assert f"Daily backup: {made.path}\n" in result.output


def test_import_backs_up_before_upgrading(
    ready: Path, stub: StubEngine, db_file: Path, cfg_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_backup(cfg_file, auto=False)  # the safety copy doesn't depend on daily backups
    assert import_fixture("qgd_elephant.pgn").exit_code == 0
    monkeypatch.setattr(connection, "load_migrations", with_next_migration)
    result = import_fixture("blackburne_shilling.pgn")
    assert result.exit_code == 0, result.output
    (made,) = backups(db_file)
    assert made.reason == "pre-migrate"
    assert f"Backed up the database before upgrading it:\n  {made.path}\n" in result.output
    with closing(connection.connect(made.path, mode="ro")) as conn:
        assert connection.user_version(conn) == LATEST
    with closing(connection.connect(db_file, mode="ro")) as conn:
        assert connection.user_version(conn) == LATEST + 1


def test_no_upgrade_without_the_safety_copy(
    tmp_path: Path,
    ready: Path,
    stub: StubEngine,
    db_file: Path,
    cfg_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert import_fixture("qgd_elephant.pgn").exit_code == 0
    blocker = tmp_path / "a file"
    blocker.write_bytes(b"")
    set_backup(cfg_file, dir=str(blocker / "bk"), auto=False)
    monkeypatch.setattr(connection, "load_migrations", with_next_migration)
    result = import_fixture("blackburne_shilling.pgn")
    assert result.exit_code == 1
    assert (
        "Can't import: the database can't be used.\n"
        "Can't back up the database before upgrading it, so it wasn't upgraded: "
        "Can't create the backup folder"
    ) in result.output
    with closing(connection.connect(db_file, mode="ro")) as conn:
        assert connection.user_version(conn) == LATEST


def import_labels() -> list[tuple[str, str]]:
    with closing(connection.connect(config.db_path(), mode="ro")) as conn:
        rows = conn.execute("SELECT label, kind FROM imports ORDER BY id").fetchall()
    return [tuple(r) for r in rows]
