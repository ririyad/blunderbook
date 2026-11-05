from pathlib import Path

import chess
import pytest

from blunderbook.core import pgn
from blunderbook.core.detect import (
    MATE_CP,
    accepted_moves,
    best_line_san,
    chances,
    is_flagged,
    judgment,
    line_san,
    maths_cp,
    refutation_san,
    swing,
    winning_chances,
)
from blunderbook.core.models import Color, Eval, Judgment, Thresholds

FIXTURES = Path(__file__).parent / "fixtures" / "pgn"
TH = Thresholds()


def cp(value: int) -> Eval:
    return Eval(cp=value)


def mate(value: int) -> Eval:
    return Eval(mate=value)


def moves(*uci: str) -> list[chess.Move]:
    return [chess.Move.from_uci(u) for u in uci]


def fen_after(*san: str) -> str:
    board = chess.Board()
    for move in san:
        board.push_san(move)
    return board.fen()


# ---------------------------------------------------------------- winning chances


def test_winning_chances_shape() -> None:
    assert winning_chances(0) == 0
    assert winning_chances(36) == pytest.approx(0.0662, abs=1e-4)
    assert winning_chances(-409) == pytest.approx(-0.6369, abs=1e-4)
    assert winning_chances(MATE_CP) == pytest.approx(1, abs=1e-12)
    assert winning_chances(-MATE_CP) == pytest.approx(-1, abs=1e-12)


@pytest.mark.parametrize("value", [1, 50, 300, 1000, 5000])
def test_winning_chances_is_symmetric_and_bounded(value: int) -> None:
    assert winning_chances(-value) == pytest.approx(-winning_chances(value))
    assert 0 < winning_chances(value) < 1


def test_winning_chances_grow_with_the_score() -> None:
    values = [winning_chances(c) for c in range(-2000, 2001, 50)]
    assert values == sorted(values)


# ---------------------------------------------------------------- scores for the maths


def test_maths_cp() -> None:
    assert maths_cp(cp(36), "white") == 36
    assert maths_cp(cp(-409), "black") == -409
    assert maths_cp(mate(3), "black") == MATE_CP  # White mates in 3
    assert maths_cp(mate(-1), "white") == -MATE_CP  # Black mates in 1


def test_mate_zero_takes_its_side_from_the_turn() -> None:
    assert maths_cp(mate(0), "white") == -MATE_CP  # White to move, checkmated
    assert maths_cp(mate(0), "black") == MATE_CP  # Black to move, checkmated


# ---------------------------------------------------------------- swing (§2, §7.6)


@pytest.mark.parametrize(
    ("before", "after", "mover", "expected"),
    [
        (cp(36), cp(-409), "white", 0.352),  # qgd_elephant 6. Nxd5
        (cp(-32), mate(1), "black", 0.529),  # scholars_mate 3... Nf6, mate in 1 against me
        (cp(208), mate(2), "black", 0.317),  # legal_trap 5... Bxd1
        (cp(-52), cp(-538), "white", 0.331),  # blackburne_shilling 5. Nxf7
        (cp(3), mate(-1), "white", 0.503),  # back_rank 32. Rc7
        (cp(52), cp(500), "black", 0.315),  # petroff_trap 4... Nf6
    ],
)
def test_swing_matches_the_demo(before: Eval, after: Eval, mover: Color, expected: float) -> None:
    assert swing(before, after, mover) == pytest.approx(expected, abs=5e-4)


def test_swing_is_the_same_maths_for_both_colours() -> None:
    white = swing(cp(100), cp(-200), "white")
    black = swing(cp(-100), cp(200), "black")
    assert white == pytest.approx(black)
    assert white > 0


def test_swing_is_never_negative() -> None:
    assert swing(cp(0), cp(300), "white") == 0
    assert swing(cp(0), cp(-300), "black") == 0
    assert swing(cp(50), cp(50), "white") == 0


def test_delivering_mate_is_no_swing() -> None:
    # Mate in 1 for White, then White mates: Black to move and checkmated (mate 0).
    assert swing(mate(1), mate(0), "white") == 0
    assert swing(mate(-1), mate(0), "black") == 0


def test_already_lost_positions_dont_swing() -> None:
    assert swing(mate(-5), mate(-1), "white") == 0  # being mated either way
    assert swing(cp(-3000), mate(-2), "white") < TH.inaccuracy


def test_throwing_away_a_mate_is_a_blunder() -> None:
    assert swing(mate(2), cp(0), "white") == pytest.approx(0.5)


# ---------------------------------------------------------------- the Log's eval bar


def test_chances_are_from_my_side() -> None:
    assert chances(cp(0), "white", "white") == 0.5
    assert chances(cp(0), "black", "black") == 0.5
    assert chances(cp(36), "white", "white") == pytest.approx(0.5331, abs=1e-4)
    assert chances(cp(36), "white", "black") == pytest.approx(1 - 0.5331, abs=1e-4)
    assert chances(mate(1), "black", "white") == pytest.approx(1)
    assert chances(mate(1), "black", "black") == pytest.approx(0)


def test_chances_after_mate_zero() -> None:
    assert chances(mate(0), "black", "white") == pytest.approx(1)  # I mated Black
    assert chances(mate(0), "white", "white") == pytest.approx(0)  # I'm checkmated


@pytest.mark.parametrize(
    ("before", "after", "mover"),
    [(cp(36), cp(-409), "white"), (cp(-32), mate(1), "black"), (cp(3), mate(-1), "white")],
)
def test_swing_is_the_drop_in_chances(before: Eval, after: Eval, mover: Color) -> None:
    them: Color = "black" if mover == "white" else "white"
    drop = chances(before, mover, mover) - chances(after, them, mover)
    assert drop == pytest.approx(swing(before, after, mover))


# ---------------------------------------------------------------- judgment and flagging


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1.0, "blunder"),
        (0.15, "blunder"),
        (0.1499, "mistake"),
        (0.10, "mistake"),
        (0.0999, "inaccuracy"),
        (0.05, "inaccuracy"),
        (0.0499, None),
        (0.0, None),
    ],
)
def test_judgment_thresholds(value: float, expected: str | None) -> None:
    assert judgment(value, TH) == expected


def test_judgment_uses_the_configured_thresholds() -> None:
    strict = Thresholds(inaccuracy=0.02, mistake=0.04, blunder=0.08)
    assert judgment(0.09, strict) == "blunder"
    assert judgment(0.05, strict) == "mistake"
    assert judgment(0.03, strict) == "inaccuracy"
    assert judgment(0.01, strict) is None


@pytest.mark.parametrize(
    ("value", "played", "best", "flagged"),
    [
        (0.15, "c3d5", "e2e3", True),
        (0.352, "c3d5", "e2e3", True),
        (0.1499, "c3d5", "e2e3", False),  # a mistake isn't logged from imports
        (0.4, "e2e3", "e2e3", False),  # the engine's own move: its score just moved
        (0.4, "c3d5", None, False),
    ],
)
def test_is_flagged(value: float, played: str, best: str | None, flagged: bool) -> None:
    assert is_flagged(value, played, best, TH) is flagged


def test_flagging_uses_the_configured_blunder_line() -> None:
    assert is_flagged(0.12, "c3d5", "e2e3", Thresholds(blunder=0.12))
    assert not is_flagged(0.15, "c3d5", "e2e3", Thresholds(blunder=0.2))


@pytest.mark.parametrize(
    ("value", "flag_at", "flagged"),
    [
        (0.06, "inaccuracy", True),
        (0.04, "inaccuracy", False),
        (0.12, "mistake", True),
        (0.06, "mistake", False),
        (0.12, "blunder", False),
    ],
)
def test_flag_at_a_lower_line(value: float, flag_at: Judgment, flagged: bool) -> None:
    """A FEN entry logs anything from an inaccuracy up (CLAUDE.md §9)."""
    assert is_flagged(value, "c3d5", "e2e3", TH, flag_at) is flagged
    assert not is_flagged(value, "e2e3", "e2e3", TH, flag_at)  # your move was the best


# ---------------------------------------------------------------- accepted moves (pass 2)


def test_accepted_moves_within_the_margin() -> None:
    lines = [("e2e3", cp(36)), ("d1c2", cp(-24)), ("a2a3", cp(-25))]
    assert accepted_moves(lines, "white", "e2e3", 60) == ("e2e3", "d1c2")  # 60 in, 61 out


def test_accepted_moves_for_black_use_black_scores() -> None:
    lines = [("d6e5", cp(-208)), ("g4e6", cp(-170)), ("g4h5", cp(-100))]
    assert accepted_moves(lines, "black", "d6e5", 60) == ("d6e5", "g4e6")


def test_best_move_is_always_first_and_never_repeated() -> None:
    lines = [("d1c2", cp(40)), ("e2e3", cp(36))]
    assert accepted_moves(lines, "white", "e2e3", 60) == ("e2e3", "d1c2")
    assert accepted_moves([], "white", "e2e3", 60) == ("e2e3",)


def test_every_mating_move_is_accepted() -> None:
    lines = [("h5f7", mate(1)), ("c4f7", mate(4)), ("h5e5", cp(900))]
    assert accepted_moves(lines, "white", "h5f7", 60) == ("h5f7", "c4f7")


def test_the_flagged_move_is_never_accepted() -> None:
    lines = [("e2e3", cp(36)), ("c3d5", cp(20)), ("d1c2", cp(10))]
    accepted = accepted_moves(lines, "white", "e2e3", 60, played_uci="c3d5")
    assert accepted == ("e2e3", "d1c2")


def test_zero_margin_accepts_only_equal_scores() -> None:
    lines = [("e2e3", cp(36)), ("d1c2", cp(36)), ("a2a3", cp(35))]
    assert accepted_moves(lines, "white", "e2e3", 0) == ("e2e3", "d1c2")


# ---------------------------------------------------------------- lines (best, refutation)


def test_white_line_with_move_numbers() -> None:
    fen = "r1bqkb1r/pppn1ppp/5n2/3p2B1/3P4/2N5/PP2PPPP/R2QKBNR w KQkq - 0 6"
    pv = moves("e2e3", "f8e7", "f1d3", "c7c6", "h2h3", "d7f8", "g1f3", "f8g6")
    assert best_line_san(fen, pv) == "6. e3 Be7 7. Bd3 c6 8. h3 Nf8"  # 6 plies of 8


def test_black_start_numbering() -> None:
    fen = fen_after("e4", "e5", "Nf3", "Nc6", "Nc3", "Nf6", "d4", "d6", "dxe5")
    assert line_san(fen, moves("c6e5", "f1e2"), 6) == "5... Nxe5 6. Be2"


def test_black_start_longer_line() -> None:
    fen = "rn1qkbnr/ppp2p1p/3p2p1/4N3/2B1P1b1/2N5/PPPP1PPP/R1BQK2R b KQkq - 0 5"
    pv = moves("d6e5", "d1g4", "b8c6", "d2d3", "h7h5", "g4f3", "g8f6")
    assert best_line_san(fen, pv) == "5... dxe5 6. Qxg4 Nc6 7. d3 h5 8. Qf3"


def test_refutation_is_five_plies() -> None:
    fen = "r1b1kbnr/pppp1Npp/8/6q1/2BnP3/8/PPPP1PPP/RNBQK2R b KQkq - 0 5"
    pv = moves("g5g2", "d2d3", "g2h1", "e1d2", "h1d1", "d2d1")
    assert refutation_san(fen, pv) == "5... Qxg2 6. d3 Qxh1+ 7. Kd2 Qxd1+"


def test_lines_show_check_and_mate() -> None:
    fen = fen_after("e4", "e5", "Bc4", "Nc6", "Qh5", "Nf6")
    assert refutation_san(fen, moves("h5f7")) == "4. Qxf7#"


def test_refutation_from_a_fixture_ply() -> None:
    game = pgn.parse((FIXTURES / "back_rank.pgn").read_text("utf-8")).games[0]
    rc7 = game.plies[0]
    assert rc7.label == "32. Rc7"
    assert refutation_san(rc7.fen_after, moves("e7e1")) == "32... Qe1#"


def test_line_stops_at_an_illegal_move() -> None:
    fen = "r1bqkb1r/pppn1ppp/5n2/3p2B1/3P4/2N5/PP2PPPP/R2QKBNR w KQkq - 0 6"
    assert best_line_san(fen, moves("e2e3", "f8e7", "e2e4", "c7c6")) == "6. e3 Be7"
    assert best_line_san(fen, moves("e1e8")) == ""


def test_empty_lines() -> None:
    fen = chess.STARTING_FEN
    assert best_line_san(fen, []) == ""
    assert refutation_san(fen, []) is None


def test_line_accepts_any_iterable() -> None:
    pv = iter(moves("e2e4", "e7e5", "g1f3"))
    assert line_san(chess.STARTING_FEN, pv, 2) == "1. e4 e5"
