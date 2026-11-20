"""The chess in a note (ROADMAP 19.2): PGN and FEN blocks, arrows, and typed moves."""

import chess
import pytest
from blunderbook_journal import moves
from blunderbook_journal.moves import CommentItem, LineItem, MoveItem


def sans(game: moves.PgnBlock) -> list[str]:
    return [m.san for m in game.moves]


# ---------------------------------------------------------------- PGN blocks


def test_a_game_with_headers() -> None:
    game = moves.read_pgn('[White "Tal"]\n[Result "1-0"]\n\n1. e4 e5 2. Nf3 1-0')
    assert game.error == ""
    assert dict(game.headers)["White"] == "Tal"
    assert game.result == "1-0"
    assert game.start == chess.STARTING_FEN
    assert sans(game) == ["e4", "e5", "Nf3"]
    assert game.items == (MoveItem(0), MoveItem(1), MoveItem(2))
    first, second, third = game.moves
    assert (first.prev, first.next, second.prev, second.next, third.next) == (None, 1, 0, 2, None)
    assert (first.no, first.white, second.no, second.white) == (1, True, 1, False)
    assert first.uci == "e2e4"
    assert (
        third.fen
        == chess.Board("rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2").fen()
    )


def test_headers_on_one_line() -> None:
    game = moves.read_pgn('[White "Tal"] [Black "Petrosian"]\n1. e4 *')
    assert dict(game.headers)["White"] == "Tal"
    assert dict(game.headers)["Black"] == "Petrosian"


def test_bare_moves_need_no_headers() -> None:
    assert sans(moves.read_pgn("1. d4 d5")) == ["d4", "d5"]


def test_variations_comments_and_marks() -> None:
    game = moves.read_pgn(
        "{Before it all.} 1. e4 $1 {Best by test.} (1. d4 {Solid.} d5 (1... Nf6 2. c4)) "
        "1... e5 $4 {[%cal Ge1g1,Rd8h4][%csl Ye5][%clk 0:03:00] castle soon} 2. Nf3 *"
    )
    assert sans(game) == ["e4", "d4", "d5", "Nf6", "c4", "e5", "Nf3"]
    assert game.items == (
        CommentItem("Before it all."),
        MoveItem(0),
        CommentItem("Best by test."),
        LineItem(
            (
                MoveItem(1),
                CommentItem("Solid."),
                MoveItem(2),
                LineItem((MoveItem(3), MoveItem(4))),
            )
        ),
        MoveItem(5),
        CommentItem("castle soon"),
        MoveItem(6),
    )
    e4, d4, d5, nf6, c4, e5, nf3 = game.moves
    assert (e4.nag, e5.nag, nf3.nag) == ("!", "??", "")
    assert e5.marks == moves.Marks((("e1", "g1", "G"), ("d8", "h4", "R")), (("e5", "Y"),))
    # Each line's own next move; a variation starts from the move before the one it replaces.
    assert (e4.prev, e4.next, e5.prev, e5.next) == (None, 5, 0, 6)
    assert (d4.prev, d4.next, d5.prev, d5.next) == (None, 2, 1, None)
    assert (nf6.prev, nf6.next, c4.prev) == (1, 4, 3)


def test_variations_within_variations() -> None:
    game = moves.read_pgn("1. e4 e5 (1... c5 2. Nf3 (2. c3 d5) 2... d6) 2. Nf3 *")
    assert sans(game) == ["e4", "e5", "c5", "Nf3", "c3", "d5", "d6", "Nf3"]
    assert game.items == (
        MoveItem(0),
        MoveItem(1),
        LineItem((MoveItem(2), MoveItem(3), LineItem((MoveItem(4), MoveItem(5))), MoveItem(6))),
        MoveItem(7),
    )
    c3 = game.moves[4]
    assert (c3.san, c3.prev, c3.next, c3.no, c3.white) == ("c3", 2, 5, 2, True)


def test_a_variation_written_inside_another_is_a_sibling() -> None:
    """(1. d4 (1. c4)) is PGN for two alternatives to 1. e4, not one inside the other."""
    game = moves.read_pgn("1. e4 (1. d4 (1. c4 e5) d5) e5 *")
    assert sans(game) == ["e4", "d4", "d5", "c4", "e5", "e5"]
    assert [m.prev for m in game.moves] == [None, None, 1, None, 3, 0]


def test_a_game_from_a_position() -> None:
    fen = "3r2k1/4qppp/8/8/8/1Q6/5PPP/2R3K1 w - - 0 32"
    game = moves.read_pgn(f'[SetUp "1"]\n[FEN "{fen}"]\n\n32. Rc7 Qe1# 0-1')
    assert game.start == fen
    assert sans(game) == ["Rc7", "Qe1#"]
    assert (game.moves[0].no, game.moves[1].no) == (32, 32)


def test_a_position_with_no_moves() -> None:
    fen = "8/8/8/4k3/8/8/8/4K2R w K - 0 1"
    game = moves.read_pgn(f'[FEN "{fen}"]\n*')
    assert (game.error, game.start, game.moves) == ("", fen, ())


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("", "This PGN block is empty."),
        ("Just some words", "There are no moves in this PGN."),
        ("1. e4 e5 2. Nf3 Nxd4 3. Bc4", "Couldn't play Nxd4: it isn't legal there."),
        (
            '[FEN "4k3/8/8/8/8/8/4K3/R6R w - - 0 1"]\n1. Rd1',
            "Couldn't play Rd1: more than one piece can make it.",
        ),
        ('[Variant "Chess960"]\n1. e4 *', "Chess960 isn't supported, only standard chess."),
        ('[Variant "Atomic"]\n1. e4 *', "Atomic isn't supported, only standard chess."),
        ("1. e4 -- 2. Nf3", "Null moves (--) aren't supported (move 1)."),
    ],
)
def test_a_pgn_that_cant_be_read(text: str, error: str) -> None:
    game = moves.read_pgn(text)
    assert game.error == error
    assert game.moves == ()


def test_only_the_first_game() -> None:
    game = moves.read_pgn("1. e4 e5 *\n\n1. d4 d5 *")
    assert sans(game) == ["e4", "e5"]
    assert game.note == "Only the first game in this block is shown."


def test_a_block_is_read_once() -> None:
    text = "1. c4 e5 2. Nc3 *"
    assert moves.read_pgn(text) is moves.read_pgn(text)
    assert moves.read_fen(chess.STARTING_FEN) is moves.read_fen(chess.STARTING_FEN)


# ---------------------------------------------------------------- FEN blocks


def test_a_fen_with_arrows_and_a_caption() -> None:
    board = moves.read_fen(
        "r1bqkb1r/pppn1ppp/5n2/3p2B1/3P4/2N5/PP2PPPP/R2QKBNR w KQkq - 0 6\n"
        "{[%cal Rc3d5,Bf8b4][%csl Rd5]}\nWhite to move.\n"
    )
    assert board.error == ""
    assert board.playable
    assert board.marks.arrows == (("c3", "d5", "R"), ("f8", "b4", "B"))
    assert board.marks.squares == (("d5", "R"),)
    assert board.caption == "White to move."


def test_a_fen_with_only_the_board_and_the_side() -> None:
    board = moves.read_fen("8/8/8/8/8/8/8/K6k b")
    assert board.fen == "8/8/8/8/8/8/8/K6k b - - 0 1"


def test_a_diagram_that_isnt_a_legal_position() -> None:
    board = moves.read_fen("8/8/8/8/8/8/8/8 w - - 0 1")  # no kings
    assert (board.error, board.playable) == ("", False)


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("", "This FEN block is empty."),
        ("not a fen", "Couldn't read the FEN 'not a fen'."),
    ],
)
def test_a_fen_that_cant_be_read(text: str, error: str) -> None:
    assert moves.read_fen(text).error == error


def test_marks_ignore_what_they_cant_read() -> None:
    found, rest = moves.marks("[%cal Rc3d5, Xa1a2,Rz9a1][%csl Gh8,Bi9] [%eval 0.3] keep this")
    assert found == moves.Marks((("c3", "d5", "R"),), (("h8", "G"),))
    assert rest == "keep this"


# ---------------------------------------------------------------- typed moves


@pytest.mark.parametrize(
    ("text", "run"),
    [
        ("after 5. cxd5 exd5 6. Nxd5?? Nxd5, White", "5. cxd5 exd5 6. Nxd5?? Nxd5"),
        ("then 6...Nxd5! wins", "6...Nxd5!"),
        ("then 6… Nxd5 wins", "6… Nxd5"),
        ("1.e4 e5 2.Nf3", "1.e4 e5 2.Nf3"),
        ("castles with 10. O-O-O+ and", "10. O-O-O+"),
        ("castles with 10. 0-0 and", "10. 0-0"),
        ("promotes: 40. e8=Q+.", "40. e8=Q+"),
        ("over two lines 1. e4\ne5 2. d4", "1. e4\ne5 2. d4"),
    ],
)
def test_a_run_in_a_sentence(text: str, run: str) -> None:
    found = moves.RUN.search(text)
    assert found is not None and found.group(0) == run


@pytest.mark.parametrize(
    "text",
    [
        "in 1958. Then he",  # a year, not a move
        "version 1.2 of it",
        "v1.e4",  # glued to a word
        "e4 e5 with no number",
        "1. Ke9",  # not a square
    ],
)
def test_not_a_run(text: str) -> None:
    assert moves.RUN.search(text) is None


def test_typed_moves() -> None:
    found = moves.typed_moves("5. cxd5 exd5 6...Nxd5?! 7. 0-0")
    assert [offset for offset, _ in found] == [0, 8, 13, 24]
    assert [t.text for _, t in found] == ["5. cxd5", "exd5", "6...Nxd5?!", "7. 0-0"]
    assert [(t.number, t.black) for _, t in found] == [
        (5, False),
        (None, None),
        (6, True),
        (7, False),
    ]
    assert [(t.san, t.nag) for _, t in found] == [
        ("cxd5", ""),
        ("exd5", ""),
        ("Nxd5", "?!"),
        ("O-O", ""),
    ]


def test_step_checks_the_number() -> None:
    [(_, e4)] = moves.typed_moves("1. e4")
    [(_, late)] = moves.typed_moves("2. e4")
    [(_, black)] = moves.typed_moves("1... e4")
    assert moves.step(chess.STARTING_FEN, e4) is not None
    assert moves.step(chess.STARTING_FEN, late) is None
    assert moves.step(chess.STARTING_FEN, black) is None
    assert moves.legal_line(chess.STARTING_FEN, [e4, black]) is None
