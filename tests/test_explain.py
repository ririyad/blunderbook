"""The facts and prompt for an AI explanation (CLAUDE.md §7.10): pure, no network.

The lines here stand in for Stockfish's: they're the §12 fixture blunders with their known
refutations, so the board facts can be checked exactly."""

from dataclasses import replace

import chess
import pytest
from test_patterns import entry

from blunderbook.core import explain
from blunderbook.core.explain import Mistake, build_prompt, eval_words, facts, read_line
from blunderbook.core.models import Eval


def fen(moves: str) -> str:
    board = chess.Board()
    for san in moves.split():
        board.push_san(san)
    return board.fen()


ELEPHANT = Mistake(
    fen_before=fen("d4 d5 c4 e6 Nc3 Nf6 Bg5 Nbd7 cxd5 exd5"),
    my_color="white",
    played_uci="c3d5",
    best_uci="e2e3",
    best_line_san="6. e3 Be7 7. Bd3 c6 8. Nf3 O-O",
    refutation_san="6... Nxd5 7. Bxd8 Bb4+ 8. Qd2 Bxd2+",
    eval_before=Eval(cp=36),
    eval_after=Eval(cp=-409),
    judgment="blunder",
    clock_left_s=151.0,
    time_spent_s=2.4,
    time_control="3+2 blitz",
    opening="Queen's Gambit Declined (D51)",
    auto_causes=("Hung a piece",),
)
SCHOLARS = Mistake(
    fen_before=fen("e4 e5 Bc4 Nc6 Qh5"),
    my_color="black",
    played_uci="g8f6",
    best_uci="g7g6",
    best_line_san="3... g6 4. Qf3 Nf6",
    refutation_san="4. Qxf7#",
    eval_before=Eval(cp=-32),
    eval_after=Eval(mate=1),
    judgment="blunder",
)
BACK_RANK = Mistake(
    fen_before="3r2k1/4qppp/8/8/8/1Q6/5PPP/2R3K1 w - - 0 32",
    my_color="white",
    played_uci="c1c7",
    best_uci="g2g3",
    best_line_san="32. g3",
    refutation_san="32... Qe1#",
    eval_before=Eval(cp=3),
    eval_after=Eval(mate=-1),
    judgment="blunder",
    clock_left_s=9.0,
    time_control="3+2 blitz",
)
LEGAL_TRAP = Mistake(
    fen_before=fen("e4 e5 Nf3 d6 Bc4 Bg4 Nc3 g6 Nxe5"),
    my_color="black",
    played_uci="g4d1",
    best_uci="d6e5",
    best_line_san="5... dxe5 6. Qxg4",
    refutation_san="6. Bxf7+ Ke7 7. Nd5#",
    eval_before=Eval(cp=-150),
    eval_after=Eval(mate=2),
    judgment="blunder",
)


# ---------------------------------------------------------------- facts


def test_elephant_refutation_shows_each_capture() -> None:
    f = facts(ELEPHANT)
    assert (f.side, f.move, f.played_san, f.best_san) == ("White", "6. Nxd5", "Nxd5", "e3")
    assert f.after_move == ("Your knight on d5 is attacked and not defended.",)
    assert f.refutation is not None
    assert f.refutation.text == "6... Nxd5 7. Bxd8 Bb4+ 8. Qd2 Bxd2+"
    assert f.refutation.captures == (
        "Nxd5 takes your knight on d5",
        "Bxd8 takes their queen on d8",
        "Bxd2+ takes your queen on d2",
    )
    assert f.refutation.material == -2  # a pawn won, a knight lost, queens traded so far
    assert f.refutation.unsettled and f.refutation.ending is None
    assert f.best_line is not None
    assert (f.best_line.material, f.best_line.captures, f.best_line.unsettled) == (0, (), False)


def test_scholars_mate_threat() -> None:
    f = facts(SCHOLARS)
    assert f.move == "3... Nf6"
    assert f.eval_after == "they have mate in 1"
    assert f.after_move == (
        "Your pawn on f7 is attacked twice and defended once.",
        "They now have a forced mate.",
    )
    assert f.refutation is not None
    assert f.refutation.captures == ("Qxf7# takes your pawn on f7",)
    assert f.refutation.ending == "checkmate"


def test_back_rank() -> None:
    f = facts(BACK_RANK)
    assert f.after_move == (
        "Your rook on c7 is attacked and not defended.",
        "They now have a forced mate.",
    )
    assert f.refutation is not None
    assert (f.refutation.text, f.refutation.ending) == ("32... Qe1#", "checkmate")


def test_legal_trap_wins_the_queen_but_gets_mated() -> None:
    f = facts(LEGAL_TRAP)
    assert f.refutation is not None
    assert f.refutation.ending == "checkmate"
    assert f.refutation.captures == ("Bxf7+ takes your pawn on f7",)
    assert f.best_move_notes == ("it captures their knight on e5",)
    assert f.best_line is not None
    assert f.best_line.captures == (
        "dxe5 takes their knight on e5",
        "Qxg4 takes your bishop on g4",
    )


def test_best_move_notes_check_and_promotion() -> None:
    m = replace(
        BACK_RANK,
        fen_before="8/P5k1/8/8/8/8/6K1/8 w - - 0 50",
        played_uci="g2f3",
        best_uci="a7a8q",
        best_line_san="50. a8=Q",
        refutation_san=None,
    )
    assert facts(m).best_move_notes == ("it promotes to a queen",)
    m = replace(m, fen_before="6k1/P7/8/8/8/8/6K1/8 w - - 0 50")
    assert facts(m).best_move_notes == ("it promotes to a queen", "it gives check")


def test_en_passant_capture_names_the_pawn() -> None:
    m = replace(
        ELEPHANT,
        fen_before="4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 30",
        played_uci="e1d1",
        best_uci="e5d6",
        best_line_san="30. exd6",
        refutation_san=None,
    )
    assert facts(m).best_move_notes == ("it captures their pawn on d5",)


def test_stalemate_after_the_move() -> None:
    m = replace(
        BACK_RANK,
        fen_before="7k/8/5K2/6Q1/8/8/8/8 w - - 0 60",
        played_uci="g5g6",
        best_uci="g5g7",
        best_line_san="60. Qg7#",
        refutation_san=None,
        eval_before=Eval(mate=1),
        eval_after=Eval(cp=0),
    )
    f = facts(m)
    assert f.game_over == "stalemate"
    assert f.eval_before == "you have mate in 1"
    assert f.best_line is not None and f.best_line.ending == "checkmate"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("6. e3 Be7 7. Bd3", ["e2e3", "f8e7", "f1d3"]),
        ("6. e3 Ke9 7. Bd3", ["e2e3"]),  # stops at the first unreadable token
        ("6. e3 e3", ["e2e3"]),  # ... or the first illegal one
        ("", []),
    ],
)
def test_read_line(text: str, expected: list[str]) -> None:
    board = chess.Board(ELEPHANT.fen_before)
    assert [m.uci() for m in read_line(board, text)] == expected
    assert board.fen() == ELEPHANT.fen_before  # the board isn't changed


@pytest.mark.parametrize(
    ("score", "turn", "me", "words"),
    [
        (Eval(cp=36), "white", "white", "+0.36, about equal (53% winning chances)"),
        (Eval(cp=36), "black", "black", "-0.36, about equal (47% winning chances)"),
        (Eval(cp=-409), "black", "white", "-4.09, better for them (18% winning chances)"),
        (Eval(cp=900), "black", "white", "+9.00, winning for you (96% winning chances)"),
        (Eval(mate=-2), "white", "black", "you have mate in 2"),
        (Eval(mate=-2), "white", "white", "they have mate in 2"),
        (Eval(mate=0), "white", "white", "checkmate, you lost"),
        (Eval(mate=0), "black", "white", "checkmate, you won"),
    ],
)
def test_eval_words(score: Eval, turn: str, me: str, words: str) -> None:
    assert eval_words(score, turn, me) == words  # type: ignore[arg-type]


# ---------------------------------------------------------------- prompt


def test_prompt_text() -> None:
    prompt = build_prompt(ELEPHANT)
    assert prompt.system == explain.SYSTEM
    assert "Use only the moves and facts given." in prompt.system
    user = prompt.user
    assert user.startswith("You played White. Your move was 6. Nxd5??, a blunder.\n")
    assert f"Position before your move (FEN): {ELEPHANT.fen_before}" in user
    assert "Opening: Queen's Gambit Declined (D51)" in user
    assert (
        "Time control: 3+2 blitz. Your clock after the move: 2:31. "
        "Time you spent on it: 2 s." in user
    )
    assert "Evaluation after your move: -4.09, better for them (18% winning chances)." in user
    assert "Stockfish's line after your move:\n6... Nxd5 7. Bxd8 Bb4+ 8. Qd2 Bxd2+\n" in user
    assert "- Bxd8 takes their queen on d8." in user
    assert "2 points down (the line stops in the middle of an exchange or a check)." in user
    assert "Stockfish's best move instead: e3.\nStockfish's best line:\n6. e3 Be7" in user
    assert "compared with before your move: the same.\n" in user
    assert user.endswith("The app suggests, unconfirmed: Hung a piece.")


def test_prompt_without_clock_opening_or_lines() -> None:
    m = replace(SCHOLARS, refutation_san=None, best_line_san="")
    user = build_prompt(m).user
    assert "Opening" not in user and "clock" not in user and "Time control" not in user
    assert "Stockfish's line after your move" not in user
    assert "Stockfish's best line" not in user
    assert "Stockfish's best move instead: g6." in user
    assert "unconfirmed" not in user


def test_prompt_with_nothing_attacked() -> None:
    m = replace(ELEPHANT, played_uci="a2a3", refutation_san="6... c6")
    assert "- None of your pieces is attacked." in build_prompt(m).user


def test_mate_line_says_so_instead_of_material() -> None:
    user = build_prompt(SCHOLARS).user
    assert "- The line ends in checkmate." in user


# ---------------------------------------------------------------- privacy


def test_names_ratings_and_notes_are_never_sent() -> None:
    """Only engine facts leave the computer: no names, ratings, site, date or your notes."""
    e = entry(1, white="Rashed Zzwhite", black="Opponent Zzblack")
    e = replace(
        e,
        game=replace(
            e.game,
            white_elo=1987,
            black_elo=2345,
            site_label="Over the board · Zzclub",
            opening="Zzopening Gambit",
            eco="A00",
            tc_base_s=180,
            tc_inc_s=2,
        ),
        blunder=replace(
            e.blunder,
            thinking="Zzthinking about the knight",
            lesson="Zzlesson: check checks",
            causes=("Wrong plan",),
            other_cause="Zzother",
            auto_causes=("Moved too fast",),
        ),
    )
    m = explain.mistake(e)
    assert m.time_control == "3+2 blitz"
    assert m.opening == "Zzopening Gambit (A00)"
    prompt = build_prompt(m)
    sent = prompt.system + prompt.user
    for secret in (
        "Rashed", "Zzwhite", "Zzblack", "1987", "2345", "Zzclub", "Zzthinking", "Zzlesson",
        "Wrong plan", "Zzother", "2026",
    ):  # fmt: skip
        assert secret not in sent, secret
    assert "The app suggests, unconfirmed: Moved too fast." in sent


def test_mistake_has_no_field_for_private_data() -> None:
    fields = set(Mistake.__dataclass_fields__)
    assert not fields & {
        "white", "black", "white_elo", "black_elo", "site_label", "played_on", "thinking",
        "lesson", "causes", "other_cause", "pgn", "external_id",
    }  # fmt: skip
