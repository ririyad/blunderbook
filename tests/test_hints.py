"""Suggested causes (CLAUDE.md §7.7).

Engine output is stubbed: each test builds the Finding the engine would have produced.
The ``engine`` tests at the end use real Stockfish.
"""

from pathlib import Path

import chess
import pytest

from blunderbook.core import pgn, timecontrol
from blunderbook.core.engine import Engine, analyse_game
from blunderbook.core.hints import (
    Hints,
    hung_a_piece,
    material_balance,
    missed_their_threat,
    moved_too_fast,
    suggest,
    time_spent,
    time_trouble,
)
from blunderbook.core.models import Color, Eval, Finding, ParsedGame, Thresholds, TimeControl

FIXTURES = Path(__file__).parent / "fixtures" / "pgn"


def fixture(name: str) -> ParsedGame:
    return pgn.parse((FIXTURES / name).read_text("utf-8")).games[0]


def only_game(text: str) -> ParsedGame:
    result = pgn.parse(text)
    assert result.problems == ()
    return result.games[0]


def tc_of(game: ParsedGame) -> TimeControl | None:
    return timecontrol.parse(game.header("TimeControl"))


def finding(game: ParsedGame, index: int, after: Eval, refutation: tuple[str, ...] = ()) -> Finding:
    """What the engine would report for ``game.plies[index]``; only the fields hints read
    matter."""
    ply = game.plies[index]
    return Finding(
        ply=ply,
        eval_before=Eval(cp=0),
        eval_after=after,
        swing=0.3,
        judgment="blunder",
        best_uci="0000",
        best_san="?",
        best_line_san="",
        refutation_san=None,
        refutation_uci=refutation,
        accept_uci=("0000",),
    )


def hints_for(name: str, index: int, after: Eval, refutation: tuple[str, ...] = ()) -> Hints:
    game = fixture(name)
    return suggest(finding(game, index, after, refutation), game, tc_of(game))


# ---------------------------------------------------------------- the §12 fixtures


def test_back_rank_time_trouble() -> None:
    hints = hints_for("back_rank.pgn", 0, Eval(mate=-1), ("e7e1",))
    assert hints.causes == ("Missed their threat", "Time trouble")
    assert hints.clock_left_s == 9
    assert hints.time_spent_s is None  # first move of a game set up from a FEN


def test_scholars_mate_missed_their_threat() -> None:
    hints = hints_for("scholars_mate.pgn", 5, Eval(mate=1), ("h5f7",))
    assert hints.causes == ("Missed their threat",)
    assert (hints.clock_left_s, hints.time_spent_s) == (173, 4)


def test_legal_trap_fast_and_missed_mate() -> None:
    hints = hints_for("legal_trap.pgn", 9, Eval(mate=2), ("c4f7", "e8e7", "c3d5"))
    assert hints.causes == ("Missed their threat", "Moved too fast")
    assert hints.time_spent_s == pytest.approx(2.6)


def test_unmatched_name_fixture() -> None:
    hints = hints_for("chesscom_unmatched_name.pgn", 9, Eval(mate=1), ("e4d6",))
    assert hints.causes == ("Missed their threat", "Moved too fast")
    assert hints.time_spent_s == 1


def test_blackburne_shilling_hung_a_piece() -> None:
    refutation = ("g5g2", "d2d3", "g2h1", "e1d2", "h1d1", "d2d1")
    hints = hints_for("blackburne_shilling.pgn", 8, Eval(cp=-538), refutation)
    assert hints == Hints(causes=("Hung a piece",), clock_left_s=None, time_spent_s=None)


def test_petroff_trap_hung_the_queen() -> None:
    refutation = ("e5c6", "d8e7", "c6e7", "f8e7", "e2d1")
    assert hints_for("petroff_trap.pgn", 7, Eval(cp=500), refutation).causes == ("Hung a piece",)


def test_elephant_trap_is_a_piece_for_a_pawn() -> None:
    # 6. Nxd5 Nxd5 7. Bxd8 Bb4+ 8. Qd2 Bxd2+ 9. Kxd2: White ends a pawn up after 6 plies
    # (Kxd8 comes next), so no cause is suggested. The user picks one.
    refutation = ("f6d5", "g5d8", "f8b4", "d1d2", "b4d2", "e1d2", "e8d8")
    assert hints_for("qgd_elephant.pgn", 10, Eval(cp=-409), refutation).causes == ()


# ---------------------------------------------------------------- no clocks -> skip


def test_no_clocks_skips_the_time_rules() -> None:
    hints = hints_for("otb_club_no_clocks.pgn", 24, Eval(cp=-150))
    assert hints == Hints(causes=(), clock_left_s=None, time_spent_s=None)


def test_clocks_without_a_time_control_skip_the_time_rules() -> None:
    game = fixture("legal_trap.pgn")
    hints = suggest(finding(game, 9, Eval(cp=-300)), game, None)
    assert (hints.causes, hints.time_spent_s) == ((), None)
    assert hints.clock_left_s == pytest.approx(587.6)  # still reported


def test_time_control_without_clocks_skips_the_time_rules() -> None:
    game = only_game('[TimeControl "180+2"]\n\n1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7# 1-0')
    hints = suggest(finding(game, 5, Eval(mate=1)), game, tc_of(game))
    assert hints.causes == ("Missed their threat",)
    assert (hints.clock_left_s, hints.time_spent_s) == (None, None)


# ---------------------------------------------------------------- time spent


CLOCKED = (
    '[TimeControl "180+2"]\n\n'
    "1. e4 { [%clk 0:03:01] } e5 { [%clk 0:02:59.5] } "
    "2. Nf3 { [%clk 0:02:58.4] } Nc6 { [%clk 0:02:58] } "
    "3. Bb5 { [%clk 0:03:01.5] } a6 *"
)
TC_180_2 = TimeControl(180, 2)


def test_time_spent_includes_the_increment() -> None:
    game = only_game(CLOCKED)
    assert time_spent(game, game.plies[0], TC_180_2) == 1  # 180 - 181 + 2
    assert time_spent(game, game.plies[1], TC_180_2) == pytest.approx(2.5)  # 180 - 179.5 + 2
    assert time_spent(game, game.plies[2], TC_180_2) == pytest.approx(4.6)  # 181 - 178.4 + 2
    assert time_spent(game, game.plies[3], TC_180_2) == pytest.approx(3.5)  # 179.5 - 178 + 2


def test_time_spent_unknown_cases() -> None:
    game = only_game(CLOCKED)
    assert time_spent(game, game.plies[5], TC_180_2) is None  # no clock on 3... a6
    assert time_spent(game, game.plies[2], None) is None  # increment unknown
    # 3. Bb5 shows 3.1 s more than 2. Nf3 did, more than the 2 s increment explains.
    assert time_spent(game, game.plies[4], TC_180_2) is None


def test_time_spent_skips_a_missing_previous_clock() -> None:
    game = only_game('[TimeControl "60"]\n\n1. e4 e5 2. Nf3 { [%clk 0:00:55] } *')
    assert time_spent(game, game.plies[2], TimeControl(60, 0)) is None


def test_time_spent_after_a_fen_start() -> None:
    game = only_game(
        '[SetUp "1"]\n[FEN "4k3/8/8/8/8/8/4P3/4K3 b - - 0 40"]\n[TimeControl "300"]\n\n'
        "40... Kd7 { [%clk 0:00:30] } 41. e4 { [%clk 0:00:50] } Kd6 { [%clk 0:00:28] } *"
    )
    tc = TimeControl(300, 0)
    assert time_spent(game, game.plies[0], tc) is None  # the first move: unknown
    assert time_spent(game, game.plies[1], tc) is None
    assert time_spent(game, game.plies[2], tc) == 2


def test_time_spent_has_no_float_noise() -> None:
    game = only_game(
        '[TimeControl "600"]\n\n1. e4 { [%clk 0:09:57.1] } e5 2. d4 { [%clk 0:09:54.2] } *'
    )
    assert time_spent(game, game.plies[2], TimeControl(600, 0)) == 2.9  # not 2.9000000000000341


# ---------------------------------------------------------------- time trouble / moved too fast


@pytest.mark.parametrize(
    ("clock", "tc", "expected"),
    [
        (17.9, TimeControl(180, 2), True),  # under 10% and under 20 s
        (19.9, TimeControl(180, 2), True),  # under 20 s
        (20, TimeControl(180, 2), False),
        (59, TimeControl(600, 0), True),  # under 10% of 10 minutes
        (60, TimeControl(600, 0), False),
        (5, TimeControl(0, 1), True),  # 0+1: only the 20 s rule applies
        (5, None, False),  # no time control
        (None, TimeControl(180, 2), False),  # no clock
    ],
)
def test_time_trouble(clock: float | None, tc: TimeControl | None, expected: bool) -> None:
    assert time_trouble(clock, tc) is expected


@pytest.mark.parametrize(
    ("spent", "clock", "expected"),
    [
        (3, 100, True),
        (0, 100, True),
        (3.1, 100, False),
        (2, 54, False),  # exactly 30% of 180 left is not "more than 30%"
        (2, 54.1, True),
        (None, 100, False),
        (2, None, False),
    ],
)
def test_moved_too_fast(spent: float | None, clock: float | None, expected: bool) -> None:
    assert moved_too_fast(spent, clock, TimeControl(180, 0)) is expected


def test_moved_too_fast_needs_a_time_control() -> None:
    assert not moved_too_fast(1, 100, None)


# ---------------------------------------------------------------- missed their threat


@pytest.mark.parametrize(
    ("after", "me", "expected"),
    [
        (Eval(mate=-1), "white", True),
        (Eval(mate=-7), "white", True),
        (Eval(mate=2), "white", False),  # my own mate
        (Eval(mate=1), "black", True),
        (Eval(mate=-3), "black", False),
        (Eval(mate=0), "white", False),  # I just gave checkmate
        (Eval(cp=-2500), "white", False),  # lost, but no forced mate seen
    ],
)
def test_missed_their_threat(after: Eval, me: Color, expected: bool) -> None:
    assert missed_their_threat(after, me) is expected


def test_mate_wins_over_hung_a_piece() -> None:
    # 3... Nf6 also drops the f7 pawn to the mate, but only the mate is suggested.
    hints = hints_for("scholars_mate.pgn", 5, Eval(mate=1), ("h5f7",))
    assert "Hung a piece" not in hints.causes


# ---------------------------------------------------------------- hung a piece


def after(fen: str, uci: str) -> str:
    board = chess.Board(fen)
    board.push_uci(uci)
    return board.fen()


def test_hanging_the_queen() -> None:
    white = "4k3/8/2n5/8/8/8/8/3QK3 w - - 0 1"  # 1. Qd4?? Nxd4
    assert hung_a_piece(white, after(white, "d1d4"), ("c6d4",), "white")
    assert not hung_a_piece(white, after(white, "d1d4"), (), "white")  # no line, nothing lost
    black = "3qk3/8/8/8/8/2N5/8/4K3 b - - 0 1"  # 1... Qd5?? Nxd5
    assert hung_a_piece(black, after(black, "d8d5"), ("c3d5",), "black")


def test_losing_a_pawn_is_not_hanging_a_piece() -> None:
    before = "rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2"
    assert not hung_a_piece(before, after(before, "g1f3"), ("d5e4",), "white")


def test_counts_from_before_my_move() -> None:
    before = "r1b1kbnr/pppp1ppp/8/4N1q1/2BnP3/8/PPPP1PPP/RNBQK2R w KQkq - 1 5"
    fen_after = after(before, "e5f7")  # 5. Nxf7 wins a pawn first
    four = ("g5g2", "d2d3", "g2h1", "e1d2")  # then Qxg2 and Qxh1+: 4 below the start
    assert hung_a_piece(before, fen_after, four, "white")
    two = ("g5g2", "d2d3")  # Nxf7 and Qxg2 cancel out
    assert not hung_a_piece(before, fen_after, two, "white")


def test_only_six_plies_are_played() -> None:
    before = "4k3/8/8/8/8/4n3/7P/3QK3 w - - 0 1"  # the knight already hits the queen
    fen_after = after(before, "h2h3")
    shuffle = ("e8f8", "h3h4", "f8e8", "h4h5", "e8f8", "h5h6")
    assert not hung_a_piece(before, fen_after, (*shuffle, "e3d1"), "white")  # Nxd1 is ply 7
    assert hung_a_piece(before, fen_after, ("e3d1",), "white")


def test_bad_uci_in_the_line_stops_it() -> None:
    before = "r1b1kbnr/pppp1ppp/8/4N1q1/2BnP3/8/PPPP1PPP/RNBQK2R w KQkq - 1 5"
    assert not hung_a_piece(before, after(before, "e5f7"), ("g5g2", "zz99", "g2h1"), "white")


def test_material_balance() -> None:
    assert material_balance(chess.Board(), chess.WHITE) == 0
    board = chess.Board("4k3/8/8/8/8/8/8/R3K2Q w - - 0 1")
    assert material_balance(board, chess.WHITE) == 14
    assert material_balance(board, chess.BLACK) == -14


# ---------------------------------------------------------------- real Stockfish


@pytest.mark.engine
@pytest.mark.parametrize(
    ("name", "label", "expected"),
    [
        ("back_rank.pgn", "32. Rc7", {"Time trouble", "Missed their threat"}),
        ("scholars_mate.pgn", "3... Nf6", {"Missed their threat"}),
    ],
)
def test_stockfish_fixture_hints(
    stockfish_path: Path, name: str, label: str, expected: set[str]
) -> None:
    game = fixture(name)
    me = "white" if game.header("White") == "Rashed" else "black"
    with Engine.open(str(stockfish_path), threads=1, hash_mb=16) as engine:
        result = analyse_game(game, me, engine, depth=10, thresholds=Thresholds())
    found = {f.ply.label: f for f in result.findings}[label]
    assert expected <= set(suggest(found, game, tc_of(game)).causes)
