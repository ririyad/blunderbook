import logging
from datetime import date
from pathlib import Path

import chess
import pytest

from blunderbook.core import pgn
from blunderbook.core.models import ParsedGame

FIXTURES = Path(__file__).parent / "fixtures" / "pgn"


def read(name: str) -> str:
    return (FIXTURES / name).read_text("utf-8")


def only_game(text: str) -> ParsedGame:
    result = pgn.parse(text)
    assert result.problems == ()
    assert len(result.games) == 1
    return result.games[0]


# ---------------------------------------------------------------- fixtures (CLAUDE.md §12)

# file, ply index of the expected blunder, its label, side, plies in total, has clocks
FIXTURE_TABLE = [
    ("qgd_elephant.pgn", 10, "6. Nxd5", "white", 18, False),
    ("scholars_mate.pgn", 5, "3... Nf6", "black", 7, True),
    ("legal_trap.pgn", 9, "5... Bxd1", "black", 13, True),
    ("blackburne_shilling.pgn", 8, "5. Nxf7", "white", 14, False),
    ("back_rank.pgn", 0, "32. Rc7", "white", 2, True),
    ("petroff_trap.pgn", 7, "4... Nf6", "black", 12, False),
    ("otb_club_no_clocks.pgn", 24, "13. Nc3", "white", 28, False),
    ("chesscom_unmatched_name.pgn", 9, "5... Ngf6", "black", 11, True),
]


@pytest.mark.parametrize(("name", "ply", "label", "color", "total", "clocks"), FIXTURE_TABLE)
def test_fixture_reads_and_has_the_blunder_move(
    name: str, ply: int, label: str, color: str, total: int, clocks: bool
) -> None:
    game = only_game(read(name))
    assert len(game.plies) == total
    assert game.plies[ply].label == label
    assert game.plies[ply].color == color
    assert game.has_clocks is clocks


def test_multi_game_reads_good_games_and_reports_the_broken_one() -> None:
    result = pgn.parse(read("multi_game.pgn"))
    assert [g.number for g in result.games] == [1, 3, 4]
    assert len(result.problems) == 1
    problem = result.problems[0]
    assert problem.number == 2
    assert problem.reason == "Illegal move 2. Ke3"
    assert (problem.header("White"), problem.header("Black")) == ("Tanvir H.", "Rashed")
    assert problem.pgn.startswith('[Event "Club blitz"]')
    assert problem.pgn.endswith("1. e4 e5 2. Ke3 Nc6 3. Nf3 1-0")


def test_each_game_keeps_its_own_text_verbatim() -> None:
    result = pgn.parse(read("multi_game.pgn"))
    first, third, bare = result.games
    assert first.pgn == (
        '[Event "Club blitz"]\n[Site "Dhaka Chess Club"]\n[Date "2026.10.05"]\n'
        '[White "Rashed"]\n[Black "Faisal K."]\n[Result "1/2-1/2"]\n\n'
        "1. e4 c5 2. Nf3 d6 3. d4 cxd4 4. Nxd4 Nf6 5. Nc3 a6 1/2-1/2"
    )
    assert third.pgn.startswith('[Event "Club blitz"]') and third.pgn.endswith("6. Qxc3 b6 0-1")
    assert bare.pgn == "1. e4 e6 2. d4 d5 3. Nd2 c5 *"


def test_fixture_text_is_kept_whole() -> None:
    text = read("otb_club_no_clocks.pgn")
    assert only_game(text).pgn == text.strip()


# ---------------------------------------------------------------- moves, positions, clocks


def test_plies_carry_positions_and_notation() -> None:
    game = only_game(read("qgd_elephant.pgn"))
    assert game.start_fen == chess.STARTING_FEN
    first = game.plies[0]
    assert (first.index, first.move_no, first.color, first.san, first.uci) == (
        0,
        1,
        "white",
        "d4",
        "d2d4",
    )
    assert first.fen_before == chess.STARTING_FEN
    for prev, ply in zip(game.plies, game.plies[1:], strict=False):
        assert ply.fen_before == prev.fen_after
    blunder = game.plies[10]
    board = chess.Board(blunder.fen_before)
    assert board.san(chess.Move.from_uci(blunder.uci)) == "Nxd5"


def test_castling_is_stored_as_king_move_uci() -> None:
    game = only_game(read("otb_club_no_clocks.pgn"))
    castle = game.plies[6]
    assert (castle.san, castle.uci) == ("O-O", "e1g1")


def test_game_from_fen_starts_there() -> None:
    game = only_game(read("back_rank.pgn"))
    assert game.start_fen == "3r2k1/4qppp/8/8/8/1Q6/5PPP/2R3K1 w - - 0 32"
    assert game.plies[0].fen_before == game.start_fen
    assert game.plies[1].label == "32... Qe1#"


def test_game_from_fen_with_black_to_move() -> None:
    text = '[SetUp "1"]\n[FEN "4k3/8/8/8/8/8/4P3/4K3 b - - 3 41"]\n\n41... Kd7 42. e4 Ke6 *'
    game = only_game(text)
    assert [p.label for p in game.plies] == ["41... Kd7", "42. e4", "42... Ke6"]
    assert game.plies[0].color == "black"


def test_clocks_are_read_in_seconds() -> None:
    game = only_game(read("legal_trap.pgn"))
    assert [p.clock_s for p in game.plies[:3]] == [598.9, 599.1, 597.2]
    back_rank = only_game(read("back_rank.pgn"))
    assert back_rank.plies[0].clock_s == 9


def test_partial_clocks_still_count() -> None:
    game = only_game("1. e4 {[%clk 0:03:00]} e5 2. Nf3 *")
    assert [p.clock_s for p in game.plies] == [180, None, None]
    assert game.has_clocks


def test_no_clocks() -> None:
    game = only_game(read("otb_club_no_clocks.pgn"))
    assert all(p.clock_s is None for p in game.plies)
    assert not game.has_clocks


def test_eval_annotations_are_ignored() -> None:
    game = only_game(read("scholars_mate.pgn"))
    assert game.plies[5].label == "3... Nf6"
    assert game.plies[5].clock_s == 173


# ---------------------------------------------------------------- variations and errors


def test_variations_are_skipped() -> None:
    game = only_game(read("blackburne_shilling.pgn"))
    assert [p.san for p in game.plies[8:11]] == ["Nxf7", "Qxg2", "Rf1"]


def test_bad_move_inside_a_variation_does_not_reject_the_game() -> None:
    game = only_game("1. e4 e5 (1... Ke3 2. Qh9) 2. Nf3 Nc6 *")
    assert [p.san for p in game.plies] == ["e4", "e5", "Nf3", "Nc6"]


def test_nested_variations_and_comments_keep_the_mainline() -> None:
    text = "1. e4 {start} e5 (1... c5 (1... e6 2. d4) 2. Nf3) 2. Nf3 {[%clk 0:01:00]} Nc6 *"
    game = only_game(text)
    assert [p.san for p in game.plies] == ["e4", "e5", "Nf3", "Nc6"]
    assert game.plies[2].clock_s == 60


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("1. e4 e5 2. Ke3 *", "Illegal move 2. Ke3"),
        ("1. e4 e5 2. N@c3 *", "Unreadable move 2. N@c3"),
        ("1. e4 e5 2. -- Nc6 *", "Null move (--) at move 2, which the engine can't analyse."),
        ('[FEN "not a position"]\n\n1. e4 *', "The FEN header isn't a valid position."),
        ('[Event "Only headers"]\n[Result "*"]\n\n*', "No moves in this game."),
        ('[Variant "Atomic"]\n\n1. e4 e5 *', "Atomic isn't supported, only standard chess."),
        ('[Variant "Chess960"]\n\n1. e4 e5 *', "Chess960 isn't supported, only standard chess."),
        ('[Variant "Bogus"]\n\n1. e4 e5 *', "Bogus isn't supported, only standard chess."),
    ],
)
def test_unreadable_games_get_a_plain_reason(text: str, reason: str) -> None:
    result = pgn.parse(text)
    assert result.games == ()
    assert [p.reason for p in result.problems] == [reason]


def test_ambiguous_move() -> None:
    # Knights on b1 and d1 can both reach c3.
    text = '[SetUp "1"]\n[FEN "4k3/8/8/8/8/8/8/1N1NK3 w - - 0 1"]\n\n1. Nc3 *'
    assert pgn.parse(text).problems[0].reason == "Ambiguous move 1. Nc3"


# ---------------------------------------------------------------- text python-chess skips


@pytest.mark.parametrize(
    ("text", "warnings", "sans"),
    [
        # A typo at the end would otherwise vanish without a trace.
        ("1. e4 e5 2. Ke9 *", ["Skipped unreadable text 'Ke9' at 2."], ["e4", "e5"]),
        ("1. e4 e5 2. Nf3 Qxx5 *", ["Skipped unreadable text 'Qxx5' at 2..."], ["e4", "e5", "Nf3"]),
        (
            "1. e4 e5 2. Nf3 resigns 1-0",
            ["Skipped unreadable text 'resigns' at 2..."],
            ["e4", "e5", "Nf3"],
        ),
    ],
)
def test_skipped_text_becomes_a_warning(text: str, warnings: list[str], sans: list[str]) -> None:
    game = only_game(text)
    assert list(game.warnings) == warnings
    assert [p.san for p in game.plies] == sans


def test_misread_token_rejects_the_game() -> None:
    # python-chess would read "♘f3" as the pawn move f3: a wrong game, not a skipped word.
    result = pgn.parse("1. e4 e5 2. ♘f3 Nc6 *")
    assert result.games == ()
    assert [p.reason for p in result.problems] == ["Couldn't read '♘f3' at 2."]


def test_illegal_move_names_the_unreadable_text_before_it() -> None:
    # "O-0" is skipped, so Black's Nc6 is read as White's second move.
    result = pgn.parse("1. e4 e5 2. O-0 Nc6 3. Nf3 *")
    assert [p.reason for p in result.problems] == [
        "Illegal move 2. Nc6 (after unreadable text 'O-0')"
    ]


@pytest.mark.parametrize(
    "text",
    [
        "1.e4 e5 2.Nf3 Nc6 3.Bb5 a6 *",  # move numbers glued to moves
        "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7 6. Re1 b5 7. Bb3 d6 1/2-1/2",
        "1. e4! e5?! 2. Nf3!! $1 Nc6 $14 3. Bb5 ± ∞ +- *",  # glyphs, NAGs, symbols
        "1. e4 {a comment with Ke9 in it} e5 ; Qxx5 to the end of the line\n2. Nf3 *",
        "1. e4 e5 (1... Ke9 2. Qxx5) 2. Nf3 *",  # variations aren't checked
        "1. e4 d5 2. e5 f5 3. exf6 e.p. Nxf6 ½-½",
        '[Event "Ke9 in a header"]\n\n1. e4 *',
        "1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7# 1-0",
    ],
)
def test_ordinary_movetext_has_no_warnings(text: str) -> None:
    assert only_game(text).warnings == ()


def test_fixtures_have_no_warnings() -> None:
    for path in sorted(FIXTURES.glob("*.pgn")):
        for game in pgn.parse(path.read_text("utf-8")).games:
            assert game.warnings == (), (path.name, game.warnings)


def test_errors_are_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        pgn.parse("1. e4 e5 2. Ke3 *")
    assert caplog.records == []


# ---------------------------------------------------------------- text handling


def test_bare_move_list_without_headers() -> None:
    game = only_game("1. e4 e5 2. Nf3 Nc6 *")
    assert game.header("White") is None
    assert game.header("Date") is None
    assert game.result == "*"


@pytest.mark.parametrize("newline", ["\r\n", "\r"])
def test_line_endings_are_normalised(newline: str) -> None:
    lf = read("multi_game.pgn")
    other = pgn.parse(lf.replace("\n", newline))
    assert other == pgn.parse(lf)
    assert "\r" not in other.games[0].pgn


def test_leading_bom_is_ignored() -> None:
    game = only_game("﻿" + read("qgd_elephant.pgn"))
    assert game.header("Event") == "Casual game"
    assert not game.pgn.startswith("﻿")


@pytest.mark.parametrize("text", ["", "   \n\n  ", "% only an escape line\n"])
def test_empty_text_has_no_games(text: str) -> None:
    result = pgn.parse(text)
    assert (result.games, result.problems) == ((), ())


def test_text_that_is_not_pgn() -> None:
    result = pgn.parse("Dear diary, today I lost again.")
    assert result.games == ()
    assert [p.reason for p in result.problems] == ["No moves in this game."]


# ---------------------------------------------------------------- headers


def test_unknown_header_values_are_none() -> None:
    game = only_game(read("petroff_trap.pgn"))
    assert game.header("Site") is None  # missing; python-chess fills in "?"
    assert game.header("Date") == "2026.??.??"
    assert pgn.parse_date(game.header("Date")) is None
    assert game.header("WhiteElo") is None
    assert game.header("Black") == "Rashed"


def test_headers_are_read_only_and_kept_as_written() -> None:
    game = only_game(read("legal_trap.pgn"))
    assert game.headers["Link"] == "https://www.chess.com/game/live/140512345678"
    assert game.headers["Round"] == "-"
    assert isinstance(game.headers, frozendict)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026.11.02", date(2026, 11, 2)),
        ("2026-11-02", date(2026, 11, 2)),
        (" 2026.01.31 ", date(2026, 1, 31)),
        ("2026.??.??", None),
        ("????.??.??", None),
        ("2026.13.40", None),
        ("2026.02.30", None),
        ("yesterday", None),
        (None, None),
    ],
)
def test_parse_date(value: str | None, expected: date | None) -> None:
    assert pgn.parse_date(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1402", 1402), (" 2150 ", 2150), ("?", None), ("", None), ("1500?", None), ("١٤٠٢", None)],
)
def test_parse_int(value: str, expected: int | None) -> None:
    assert pgn.parse_int(value) == expected


# ---------------------------------------------------------------- decoding files


def test_decode_utf8_with_and_without_bom() -> None:
    assert pgn.decode('[White "রাশেদ"]'.encode()) == pgn.Decoded('[White "রাশেদ"]', "utf-8")
    assert pgn.decode(b"\xef\xbb\xbf1. e4 *") == pgn.Decoded("1. e4 *", "utf-8")


def test_decode_falls_back_to_cp1252() -> None:
    # An en dash is 0x96 in cp1252 but a control code in Latin-1, so this
    # also proves the fallback is cp1252 and not Latin-1.
    text = '[White "Müller"] [Event "Café \N{EN DASH} Open"]'
    assert pgn.decode(text.encode("cp1252")) == pgn.Decoded(text, "cp1252")


def test_decode_never_fails() -> None:
    decoded = pgn.decode(b'[White "A\x81B"]')  # 0x81 is undefined in cp1252
    assert decoded.encoding == "cp1252"
    assert decoded.text == '[White "A�B"]'


def test_decoded_cp1252_file_parses() -> None:
    data = '[White "Müller"]\n[Black "Rashed"]\n\n1. e4 e5 *'.encode("cp1252")
    decoded = pgn.decode(data)
    assert only_game(decoded.text).header("White") == "Müller"
