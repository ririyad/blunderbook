"""The import pipeline without Stockfish: queueing, sides, duplicates, analysis with a
scripted engine, saving, and the summary line."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, date, datetime
from pathlib import Path

import chess
import pytest

from blunderbook import importer
from blunderbook.core.engine import Line
from blunderbook.core.models import Eval, Thresholds
from blunderbook.db import connection, repo

FIXTURES = Path(__file__).parent / "fixtures" / "pgn"
NAMES = ["Rashed"]


def read(name: str) -> str:
    return (FIXTURES / name).read_text("utf-8")


class Scripted:
    """A stand-in engine: scores from a table keyed by FEN, cp 20 everywhere else."""

    name = "Stockfish 17.1"

    def __init__(self, table: dict[str, Line] | None = None) -> None:
        self.table = table or {}
        self.positions = 0

    def lines(
        self, board: chess.Board, depth: int, multipv: int = 1, *, game: object = None
    ) -> list[Line]:
        self.positions += 1
        return [self.table.get(board.fen(), Line(Eval(cp=20)))]


def mv(*uci: str) -> tuple[chess.Move, ...]:
    return tuple(chess.Move.from_uci(u) for u in uci)


# ---------------------------------------------------------------- prepare


def test_multi_game_queue() -> None:
    queue = importer.prepare(read("multi_game.pgn"), NAMES)
    assert [(q.number, q.status, q.side) for q in queue] == [
        (1, "ready", "white"),
        (2, "error", None),
        (3, "ready", "white"),
        (4, "needs_side", None),  # a bare move list: no players to match
    ]
    assert queue[1].reason == "Illegal move 2. Ke3"
    assert queue[1].players == "Tanvir H. vs Rashed"
    assert queue[0].source is not None
    assert queue[0].source.label == "Over the board \N{MIDDLE DOT} Dhaka Chess Club"
    assert queue[0].date == "2026-10-05"
    assert queue[3].players == "? vs ?"


def test_side_option_only_fills_unmatched_games() -> None:
    queue = importer.prepare(read("multi_game.pgn"), NAMES, side="black")
    assert [(q.number, q.status, q.side, q.side_from) for q in queue if q.game] == [
        (1, "ready", "white", "names"),  # your name still wins
        (3, "ready", "white", "names"),
        (4, "ready", "black", "option"),
    ]


def test_unmatched_name_needs_side() -> None:
    (queued,) = importer.prepare(read("chesscom_unmatched_name.pgn"), NAMES)
    assert queued.status == "needs_side"
    (queued,) = importer.prepare(read("chesscom_unmatched_name.pgn"), [*NAMES, "rashed_blitz"])
    assert (queued.status, queued.side) == ("ready", "black")


def test_both_names_matching_needs_side() -> None:
    text = '[White "Rashed"]\n[Black "rashed_blitz"]\n\n1. e4 e5 *'
    (queued,) = importer.prepare(text, ["Rashed", "rashed_blitz"])
    assert queued.status == "needs_side"


def test_already_imported_is_skipped() -> None:
    (first,) = importer.prepare(read("qgd_elephant.pgn"), NAMES)
    assert first.fingerprint is not None
    (again,) = importer.prepare(read("qgd_elephant.pgn"), NAMES, known={first.fingerprint})
    assert (again.status, again.reason) == ("duplicate", "Already imported \N{EM DASH} skipped")


def test_same_game_twice_in_one_file() -> None:
    text = read("qgd_elephant.pgn") + "\n\n" + read("qgd_elephant.pgn")
    queue = importer.prepare(text, NAMES)
    assert [q.status for q in queue] == ["ready", "duplicate"]
    assert queue[1].reason == "Same game as game 1 \N{EM DASH} skipped"


def test_duplicates_are_found_before_asking_for_a_side() -> None:
    text = read("chesscom_unmatched_name.pgn") + "\n\n" + read("chesscom_unmatched_name.pgn")
    assert [q.status for q in importer.prepare(text, NAMES)] == ["needs_side", "duplicate"]


def test_parse_warnings_reach_the_queue() -> None:
    (queued,) = importer.prepare('[White "Rashed"]\n\n1. e4 e5 2. Ke9 Nf3 *', NAMES)
    assert queued.status == "ready"
    assert queued.warnings == ("Skipped unreadable text 'Ke9' at 2.",)


def test_empty_text() -> None:
    assert importer.prepare("", NAMES) == ()


# ---------------------------------------------------------------- analyse


def legal_trap() -> tuple[importer.AnalysedGame, Scripted]:
    """legal_trap.pgn analysed with a scripted engine that flags 5... Bxd1."""
    (queued,) = importer.prepare(read("legal_trap.pgn"), NAMES)
    assert queued.game is not None
    bxd1 = queued.game.plies[9]
    engine = Scripted(
        {
            bxd1.fen_before: Line(Eval(cp=-208), mv("d6e5", "d1g4")),
            bxd1.fen_after: Line(Eval(mate=2), mv("c4f7", "e8e7", "c3d5")),
        }
    )
    return importer.analyse(queued, engine, depth=12, thresholds=Thresholds()), engine


def test_analyse_adds_hints_to_each_blunder() -> None:
    result, engine = legal_trap()
    queued = result.queued
    assert queued.game is not None
    (found,) = result.blunders
    assert found.finding.ply.label == "5... Bxd1"
    assert found.finding.best_san == "dxe5"
    assert found.hints.causes == ("Missed their threat", "Moved too fast")
    assert found.hints.time_spent_s == pytest.approx(2.6)
    assert (
        engine.positions == len(queued.game.plies) + 1
    )  # the last one is checkmate: +1 for pass 2


def test_analyse_refuses_games_that_arent_ready() -> None:
    queue = importer.prepare(read("multi_game.pgn"), NAMES)
    for queued in (queue[1], queue[3]):
        with pytest.raises(ValueError, match="isn't ready"):
            importer.analyse(queued, Scripted(), depth=8, thresholds=Thresholds())


# ---------------------------------------------------------------- records and saving


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with closing(connection.open_db(tmp_path / "blunderbook.db", create=True)) as db:
        yield db


def test_new_game_from_headers() -> None:
    result, _ = legal_trap()
    game = importer.new_game(result)
    queued = result.queued
    assert queued.game is not None
    assert (game.fingerprint, game.pgn, game.start_fen) == (
        queued.fingerprint,
        queued.game.pgn,
        chess.STARTING_FEN,
    )
    assert (game.source, game.site_label, game.external_id) == (
        "chesscom",
        "Chess.com",
        "https://www.chess.com/game/live/140512345678",
    )
    assert (game.white, game.black, game.white_elo, game.black_elo) == (
        "kingside_kid",
        "Rashed",
        1290,
        1305,
    )
    assert (game.my_color, game.result, game.played_on) == ("black", "1-0", date(2026, 10, 30))
    assert (game.time_control, game.tc_base_s, game.tc_inc_s, game.speed) == (
        "600",
        600,
        0,
        "rapid",
    )
    assert (game.opening, game.eco, game.has_clocks) == (None, "C41", True)
    assert (game.engine_name, game.engine_depth) == ("Stockfish 17.1", 12)


def test_new_game_with_unknown_headers() -> None:
    (queued,) = importer.prepare("1. e4 e5 2. Qh5 Nc6 *", NAMES, side="white")
    result = importer.analyse(queued, Scripted(), depth=8, thresholds=Thresholds())
    game = importer.new_game(result)
    assert (game.source, game.site_label, game.external_id) == ("pgn", "PGN file", None)
    assert (game.white, game.black, game.white_elo, game.result, game.played_on) == (
        None,
        None,
        None,
        "*",  # python-chess fills in an unknown result
        None,
    )
    assert (game.time_control, game.tc_base_s, game.speed, game.has_clocks) == (
        None,
        None,
        None,
        False,
    )


def test_new_blunder_from_a_finding() -> None:
    result, _ = legal_trap()
    (found,) = result.blunders
    b = importer.new_blunder(found)
    f = found.finding
    assert (b.ply, b.move_no, b.played_san, b.played_uci) == (9, 5, "Bxd1", "g4d1")
    assert (b.fen_before, b.best_uci, b.best_san) == (f.ply.fen_before, "d6e5", "dxe5")
    assert (b.best_line_san, b.refutation_san, b.accept_uci) == (
        f.best_line_san,
        f.refutation_san,
        f.accept_uci,
    )
    assert (b.eval_before, b.eval_after, b.swing, b.judgment) == (
        Eval(cp=-208),
        Eval(mate=2),
        f.swing,
        "blunder",
    )
    assert (b.clock_left_s, b.time_spent_s) == (found.hints.clock_left_s, pytest.approx(2.6))
    assert b.auto_causes == ("Missed their threat", "Moved too fast")


def test_save_stores_the_game_and_its_entries(conn: sqlite3.Connection) -> None:
    result, _ = legal_trap()
    now = datetime(2026, 11, 5, 9, 30, tzinfo=UTC)
    saved = importer.save(conn, result, now=now)
    assert saved is not None and saved.analysed is result
    (entry,) = repo.list_entries(conn)
    assert entry.blunder.id == saved.blunder_ids[0]
    assert entry.game.id == saved.game_id
    assert entry.blunder.played_san == "Bxd1"
    assert entry.game.imported_at == now


def test_saved_games_are_skipped_next_time(conn: sqlite3.Connection) -> None:
    result, _ = legal_trap()
    assert importer.save(conn, result) is not None
    assert importer.save(conn, result) is None  # saved meanwhile: nothing written
    assert len(repo.list_entries(conn)) == 1
    (again,) = importer.prepare(read("legal_trap.pgn"), NAMES, known=repo.known_fingerprints(conn))
    assert (again.status, again.reason) == ("duplicate", importer.ALREADY_IMPORTED)


# ---------------------------------------------------------------- summary


def test_summary_line() -> None:
    elephant = read("qgd_elephant.pgn")
    text = "\n\n".join([read("multi_game.pgn"), elephant, elephant])
    queue = importer.prepare(text, NAMES)
    assert importer.summary(queue, []) == (
        "6 games read \N{MIDDLE DOT} 1 skipped (duplicate) \N{MIDDLE DOT} 1 needs side "
        "\N{MIDDLE DOT} 1 error \N{MIDDLE DOT} 0 blunders added"
    )


def test_summary_line_counts_blunders_and_plurals() -> None:
    (queued,) = importer.prepare(read("qgd_elephant.pgn"), NAMES)
    assert queued.game is not None
    nxd5 = queued.game.plies[10]
    engine = Scripted(
        {
            nxd5.fen_before: Line(Eval(cp=36), mv("e2e3")),
            nxd5.fen_after: Line(Eval(cp=-409), mv("f6d5")),
        }
    )
    result = importer.analyse(queued, engine, depth=8, thresholds=Thresholds())
    saved = importer.SavedGame(result, game_id=1, blunder_ids=(7,))
    assert importer.summary([queued], [saved]) == "1 game read \N{MIDDLE DOT} 1 blunder added"
    two = importer.prepare('[White "A"]\n\n1. e4 *\n\n[White "B"]\n\n1. d4 *', NAMES)
    assert "2 need side" in importer.summary(two, [])
