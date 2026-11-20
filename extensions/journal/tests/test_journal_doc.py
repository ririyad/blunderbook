"""The note parser (ROADMAP 19.2): Markdown, chess blocks and moves in sentences, as the
tree Reading mode draws."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from typing import Any

import chess
import pytest
from blunderbook_journal import doc, extension, store
from journal_fakes import ELEPHANT, FENCE, cfg_file  # noqa: F401  (fixtures)

from blunderbook import host

GAME = f"""{FENCE}pgn
1. d4 d5 2. c4 e6 3. Nc3 Nf6 4. Bg5 Nbd7 5. cxd5 exd5
6. Nxd5?? (6. e3 {{The quiet move.}} 6... Be7 7. Bd3 c6) 6... Nxd5 7. Bxd8 Bb4+ *
{FENCE}"""


def tree(body: str) -> Any:
    """The parsed note, after a round trip through JSON (as it's stored)."""
    return json.loads(json.dumps(doc.parse(body)))


def blocks(body: str) -> list[Any]:
    return list(tree(body)["blocks"])


def spans(body: str) -> list[Any]:
    [block] = blocks(body)
    return list(block["spans"])


def moves_in(found: Any, block: int = -1) -> list[tuple[str, str]]:
    """(text as typed, SAN) of each move span in a block."""
    by_id = {m["id"]: m for m in found["moves"]}
    return [
        (s["text"], by_id[s["move"]]["san"])
        for s in found["blocks"][block]["spans"]
        if s["t"] == "move"
    ]


def texts(found: list[Any]) -> str:
    return "".join(s.get("text", "") for s in found)


# ---------------------------------------------------------------- blocks


def test_a_note_with_no_chess() -> None:
    found = tree("# Plans\n\nJust words.")
    assert found == {
        "v": doc.DOC_VERSION,
        "starts": [],
        "moves": [],
        "blocks": [
            {"t": "heading", "level": 1, "spans": [{"t": "text", "text": "Plans"}]},
            {"t": "para", "spans": [{"t": "text", "text": "Just words."}]},
        ],
    }


def test_an_empty_note() -> None:
    assert tree("") == {"v": doc.DOC_VERSION, "starts": [], "moves": [], "blocks": []}


@pytest.mark.parametrize(("line", "level"), [("# One", 1), ("### Three ###", 3), ("###### Six", 6)])
def test_headings(line: str, level: int) -> None:
    [block] = blocks(line)
    assert (block["t"], block["level"], texts(block["spans"])) == (
        "heading",
        level,
        line.strip("# "),
    )


def test_a_tag_at_the_start_of_a_line_isnt_a_heading() -> None:
    [block] = blocks("#traps and more")
    assert block["t"] == "para"
    assert block["spans"][0] == {"t": "tag", "tag": "traps", "text": "#traps"}


def test_paragraphs_keep_their_line_breaks() -> None:
    first, second = blocks("One line\nand the next.\n\nA new paragraph.")
    assert texts(first["spans"]) == "One line\nand the next."
    assert texts(second["spans"]) == "A new paragraph."


def test_a_quote() -> None:
    [block] = blocks("> Checks, captures,\n> threats.")
    assert (block["t"], texts(block["spans"])) == ("quote", "Checks, captures,\nthreats.")


def test_lists() -> None:
    unordered, ordered = blocks("- one\n- two\n  more of two\n  - nested\n\n3) third\n4) fourth")
    assert (unordered["t"], unordered["ordered"]) == ("list", False)
    assert [(i["depth"], texts(i["spans"])) for i in unordered["items"]] == [
        (0, "one"),
        (0, "two\nmore of two"),
        (1, "nested"),
    ]
    assert (ordered["ordered"], ordered["start"]) == (True, 3)
    assert [texts(i["spans"]) for i in ordered["items"]] == ["third", "fourth"]


def test_a_loose_list_stays_one_list() -> None:
    [block] = blocks("- one\n\n- two\n\n\n- three")
    assert len(block["items"]) == 3


def test_moves_at_the_start_of_a_line_arent_a_list() -> None:
    [block] = blocks("1. e4 e5 2. Nf3")
    assert block["t"] == "para"
    assert [s["text"] for s in block["spans"] if s["t"] == "move"] == ["1. e4", "e5", "2. Nf3"]


def test_an_ordered_list_of_words() -> None:
    [block] = blocks("1. Develop\n2. Castle")
    assert block["t"] == "list" and block["ordered"]


def test_a_rule_and_a_log_link_on_its_own_line() -> None:
    para, rule, ref, game = blocks("Above\n---\n[[log 12]]\n  [[game 40]]  ")
    assert para["t"] == "para"
    assert rule == {"t": "rule"}
    assert ref == {"t": "ref", "kind": "log", "id": 12}
    assert game == {"t": "ref", "kind": "game", "id": 40}


@pytest.mark.parametrize(
    ("body", "lang", "text"),
    [
        (f"{FENCE}python\nprint('#x **y**')\n{FENCE}", "python", "print('#x **y**')"),
        (f"{FENCE}\nplain\n\nlines\n{FENCE}", "", "plain\n\nlines"),
        (f"{FENCE}text\nnever closed", "text", "never closed"),
    ],
)
def test_code_blocks(body: str, lang: str, text: str) -> None:
    assert blocks(body) == [{"t": "code", "lang": lang, "text": text}]


def test_a_broken_pgn_is_shown_as_code_with_the_reason() -> None:
    [block] = blocks(f"{FENCE}pgn\n1. e4 e5 2. Ke3\n{FENCE}")
    assert block == {
        "t": "code",
        "lang": "pgn",
        "text": "1. e4 e5 2. Ke3",
        "error": "Couldn't play Ke3: it isn't legal there.",
    }


def test_a_broken_fen_is_shown_as_code_with_the_reason() -> None:
    [block] = blocks(f"{FENCE}fen\nnonsense\n{FENCE}")
    assert block["t"] == "code" and block["error"] == "Couldn't read the FEN 'nonsense'."


# ---------------------------------------------------------------- inline


def test_bold_italic_and_code() -> None:
    assert spans("**bold** and *it* and _it_ and `co*de`") == [
        {"t": "text", "text": "bold", "b": True},
        {"t": "text", "text": " and "},
        {"t": "text", "text": "it", "i": True},
        {"t": "text", "text": " and "},
        {"t": "text", "text": "it", "i": True},
        {"t": "text", "text": " and "},
        {"t": "code", "text": "co*de"},
    ]


def test_nested_emphasis() -> None:
    assert spans("**bold *both* bold**") == [
        {"t": "text", "text": "bold ", "b": True},
        {"t": "text", "text": "both", "b": True, "i": True},
        {"t": "text", "text": " bold", "b": True},
    ]


@pytest.mark.parametrize(
    "text",
    ["snake_case_name", "2 * 3 * 4", "a lone * star", "**unclosed", "under_ score"],
)
def test_markers_that_dont_pair_are_text(text: str) -> None:
    assert spans(text) == [{"t": "text", "text": text}]


def test_escapes() -> None:
    assert spans(r"\*not italic\* and \#notatag") == [
        {"t": "text", "text": "*not italic* and #notatag"}
    ]


def test_links() -> None:
    assert spans("[Lichess](https://lichess.org/abc) and [top](#top)") == [
        {"t": "link", "text": "Lichess", "href": "https://lichess.org/abc"},
        {"t": "text", "text": " and "},
        {"t": "link", "text": "top", "href": "#top"},
    ]


@pytest.mark.parametrize("href", ["javascript:alert(1)", "data:text/html,x", "file:///etc"])
def test_links_that_could_run_code_stay_text(href: str) -> None:
    assert spans(f"[click]({href})") == [{"t": "text", "text": f"[click]({href})"}]


def test_tags_and_log_links_in_a_sentence() -> None:
    assert spans("See [[log 12]] and [[game 40]] #traps, not `#code`") == [
        {"t": "text", "text": "See "},
        {"t": "ref", "kind": "log", "id": 12, "text": "[[log 12]]"},
        {"t": "text", "text": " and "},
        {"t": "ref", "kind": "game", "id": 40, "text": "[[game 40]]"},
        {"t": "text", "text": " "},
        {"t": "tag", "tag": "traps", "text": "#traps"},
        {"t": "text", "text": ", not "},
        {"t": "code", "text": "#code"},
    ]


def test_unicode() -> None:
    body = "# Défense française ♞\n\nÉchecs: **très** bien #échecs 1. e4 e6 \U0001f600"
    heading, para = blocks(body)
    assert texts(heading["spans"]) == "Défense française ♞"
    assert {"t": "tag", "tag": "échecs", "text": "#échecs"} in para["spans"]
    assert [s["text"] for s in para["spans"] if s["t"] == "move"] == ["1. e4", "e6"]
    assert para["spans"][-1] == {"t": "text", "text": " \U0001f600"}


# ---------------------------------------------------------------- chess blocks


def test_a_pgn_block() -> None:
    found = tree(f'{FENCE}pgn\n[White "Tal"] [Date "????.??.??"]\n1. e4 e5 *\n{FENCE}')
    [block] = found["blocks"]
    assert block == {
        "t": "pgn",
        "start": 0,
        "headers": {"White": "Tal", "Result": "*"},
        "items": [{"move": 0}, {"move": 1}],
        "result": "*",
    }
    assert found["starts"] == [chess.STARTING_FEN]
    e4, e5 = found["moves"]
    assert e4 == {
        "id": 0,
        "san": "e4",
        "uci": "e2e4",
        "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
        "no": 1,
        "white": True,
        "prev": None,
        "next": 1,
        "start": 0,
        "nag": "",
        "arrows": [],
        "squares": [],
    }
    assert (e5["prev"], e5["next"], e5["start"]) == (0, None, None)


def test_a_pgn_blocks_variation() -> None:
    found = tree(GAME)
    [block] = found["blocks"]
    line = block["items"][11]
    assert line == {
        "line": [
            {"move": 11},
            {"comment": "The quiet move."},
            {"move": 12},
            {"move": 13},
            {"move": 14},
        ]
    }
    by_move = {(m["san"], m["no"], m["white"]): m for m in found["moves"]}
    assert by_move[("e3", 6, True)]["prev"] == 9  # from the position before 6. Nxd5
    assert by_move[("Nxd5", 6, True)]["nag"] == "??"


def test_two_blocks_get_their_own_ids_and_starts() -> None:
    found = tree(f"{FENCE}pgn\n1. e4 e5\n{FENCE}\n\n{FENCE}pgn\n1. d4 d5\n{FENCE}")
    first, second = found["blocks"]
    assert (first["start"], second["start"]) == (0, 1)
    assert second["items"] == [{"move": 2}, {"move": 3}]
    assert found["moves"][2]["start"] == 1


def test_a_fen_block() -> None:
    fen = "r1bqkb1r/pppn1ppp/5n2/3p2B1/3P4/2N5/PP2PPPP/R2QKBNR w KQkq - 0 6"
    found = tree(f"{FENCE}fen\n{fen}\n{{[%cal Rc3d5][%csl Rd5]}} Before the trap.\n{FENCE}")
    assert found["starts"] == [fen]
    assert found["blocks"] == [
        {
            "t": "fen",
            "start": 0,
            "arrows": [["c3", "d5", "R"]],
            "squares": [["d5", "R"]],
            "caption": "Before the trap.",
            "playable": True,
        }
    ]


# ---------------------------------------------------------------- moves in sentences


def test_a_sentence_above_its_game_plays_the_games_moves() -> None:
    found = tree(f"After 5. cxd5 exd5 6. Nxd5?? the queen goes.\n\n{GAME}")
    game_ids = [i["move"] for i in found["blocks"][1]["items"] if "move" in i]
    sentence = [s["move"] for s in found["blocks"][0]["spans"] if s["t"] == "move"]
    assert sentence == game_ids[8:11]
    assert len(found["moves"]) == 18  # nothing added: the sentence shares the game's moves


def test_a_sentence_below_its_game() -> None:
    found = tree(f"{GAME}\n\nThe trap is 6. Nxd5?? Nxd5 7. Bxd8 Bb4+.")
    assert moves_in(found) == [
        ("6. Nxd5??", "Nxd5"),
        ("Nxd5", "Nxd5"),
        ("7. Bxd8", "Bxd8"),
        ("Bb4+", "Bb4+"),
    ]
    assert len(found["moves"]) == 18


def test_a_sentence_can_follow_a_side_line() -> None:
    found = tree(f"{GAME}\n\nBetter is 6. e3 Be7 7. Bd3, the quiet line.")
    ids = [s["move"] for s in found["blocks"][1]["spans"] if s["t"] == "move"]
    assert [found["moves"][i]["san"] for i in ids] == ["e3", "Be7", "Bd3"]
    assert ids == [11, 12, 13]  # the side line's own moves


def test_a_sentence_that_goes_past_the_game_adds_its_own_line() -> None:
    found = tree(f"{GAME}\n\nAfter 7. Bd3 h6 8. Nge2 White is fine.")
    bd3, h6, nge2 = (s["move"] for s in found["blocks"][1]["spans"] if s["t"] == "move")
    assert bd3 == 13  # the side line's 7. Bd3
    added = found["moves"][h6]
    assert (added["san"], added["prev"], added["next"]) == ("h6", 13, nge2)
    assert found["moves"][13]["next"] == 14  # the game's own line is unchanged: 7... c6


def test_a_sentence_plays_from_a_diagram() -> None:
    fen = "3r2k1/4qppp/8/8/8/1Q6/5PPP/2R3K1 w - - 0 32"
    found = tree(f"{FENCE}fen\n{fen}\n{FENCE}\n\nHere 32. Rc7?? Qe1# ends it.")
    rc7, qe1 = (s["move"] for s in found["blocks"][1]["spans"] if s["t"] == "move")
    assert found["moves"][rc7]["start"] == 0 and found["moves"][rc7]["prev"] is None
    assert found["moves"][rc7]["nag"] == "??"
    assert found["moves"][qe1]["prev"] == rc7


def test_a_sentence_from_move_one_with_no_game() -> None:
    found = tree("The oldest trap: 1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6?? 4. Qxf7#.")
    assert found["starts"] == [chess.STARTING_FEN]
    assert [san for _, san in moves_in(found)] == ["e4", "e5", "Bc4", "Nc6", "Qh5", "Nf6", "Qxf7#"]
    assert found["moves"][0]["start"] == 0
    assert [m["next"] for m in found["moves"]] == [1, 2, 3, 4, 5, 6, None]


def test_a_later_sentence_goes_on_from_an_earlier_one() -> None:
    found = tree("Play 1. e4 e5 2. Nf3 Nc6.\n\nNow 3. Bb5 is the Spanish.")
    bb5 = found["moves"][-1]
    assert (bb5["san"], bb5["prev"]) == ("Bb5", 3)
    assert len(found["starts"]) == 1


def test_a_black_move_in_a_sentence() -> None:
    found = tree(f"{GAME}\n\nInstead of 6... Nxd5, nothing better.")
    [(typed, san)] = moves_in(found)
    assert (typed, san) == ("6... Nxd5", "Nxd5")


def test_the_nearest_game_above_wins() -> None:
    first = f"{FENCE}pgn\n1. e4 e5 2. Nf3 Nc6\n{FENCE}"
    second = f"{FENCE}pgn\n1. e4 e5 2. Nf3 Nf6\n{FENCE}"
    found = tree(f"{first}\n\n{second}\n\nThen 3. Nxe5 is played.")
    nxe5 = found["moves"][-1]
    assert (nxe5["san"], nxe5["prev"]) == ("Nxe5", 7)  # after the second game's 2... Nf6


@pytest.mark.parametrize(
    "sentence",
    [
        "Then 32. Rc7?? from nowhere.",  # no position reaches move 32
        "After 5. Ke2 nothing.",  # move 5 is reached, but Ke2 isn't legal there
        "After 5. cxd5 exd5 6. Nxd5?? Ke7 it's text.",  # one move in it isn't legal
        "After 5. cxd5 6. exd5 it's text.",  # the number doesn't fit
    ],
)
def test_a_run_that_cant_be_played_stays_text(sentence: str) -> None:
    found = tree(f"{GAME}\n\n{sentence}")
    assert found["blocks"][1]["spans"] == [{"t": "text", "text": sentence}]
    assert len(found["moves"]) == 18


def test_moves_keep_their_style() -> None:
    found = tree("A **1. e4 e5** opening")
    assert found["blocks"][0]["spans"] == [
        {"t": "text", "text": "A "},
        {"t": "move", "text": "1. e4", "move": 0, "b": True},
        {"t": "text", "text": " ", "b": True},
        {"t": "move", "text": "e5", "move": 1, "b": True},
        {"t": "text", "text": " opening"},
    ]


def test_moves_in_headings_lists_and_quotes() -> None:
    found = tree(f"{GAME}\n\n## Why 6. Nxd5?? fails\n\n- 6... Nxd5\n\n> 7. Bxd8 Bb4+")
    kinds = [s["t"] for b in found["blocks"][1:] for s in b.get("spans", [])]
    items = found["blocks"][2]["items"][0]["spans"]
    assert kinds.count("move") == 3 and items[0]["t"] == "move"
    assert len(found["moves"]) == 18


def test_the_sample_note() -> None:
    found = tree(ELEPHANT)
    _, para, game, board, ref = found["blocks"]
    assert [b["t"] for b in found["blocks"]] == ["heading", "para", "pgn", "fen", "ref"]
    assert [s for s in para["spans"] if s["t"] == "tag"] == [
        {"t": "tag", "tag": "qgd", "text": "#qgd"},
        {"t": "tag", "tag": "traps", "text": "#traps"},
    ]
    assert len([s for s in para["spans"] if s["t"] == "move"]) == 6
    assert game["headers"]["White"] == "Ivanov"
    assert board["playable"] and ref["id"] == 12


def test_a_long_game_reads_quickly() -> None:
    board = chess.Board()
    sans = []
    for _ in range(120):
        move = sorted(board.legal_moves, key=lambda m: m.uci())[0]
        if board.is_game_over():
            break
        sans.append(board.san(move))
        board.push(move)
    game = " ".join(sans)
    found = tree(f"{FENCE}pgn\n{game}\n{FENCE}\n\nThe end: " + "it." * 2000)
    assert len(found["moves"]) == len(sans)


# ---------------------------------------------------------------- stored with the note


@pytest.fixture
def db() -> Iterator[sqlite3.Connection]:
    with closing(host.open_db(extension)) as conn:
        yield conn


def test_the_tree_is_saved_with_the_note(db: sqlite3.Connection) -> None:
    note = store.create(db, ELEPHANT)
    assert store.document(db, note.id) == doc.parse(ELEPHANT)
    store.update(db, note.id, "# Changed\n1. e4")
    found = store.document(db, note.id)
    assert found is not None and found["starts"] == [chess.STARTING_FEN]
    assert store.document(db, note.id + 1) is None


def test_a_tree_from_an_older_parser_is_made_again(db: sqlite3.Connection) -> None:
    note = store.create(db, "1. e4 e5")
    db.execute("UPDATE notes SET doc = '{}', doc_version = 0 WHERE id = ?", (note.id,))
    assert store.document(db, note.id) == doc.parse("1. e4 e5")
    kept = db.execute("SELECT doc_version FROM notes WHERE id = ?", (note.id,)).fetchone()[0]
    assert kept == doc.DOC_VERSION


def test_where_each_block_is() -> None:
    game = f"{FENCE}pgn\n1. e4\n{FENCE}"
    body = f"# Title\n\n{game}\n\nText\n\n{FENCE}fen\n8/8/8/8/8/8/8/K6k w\n\n{FENCE}"
    assert doc.sources(body) == {1: (3, 4), 3: (9, 11)}
    assert doc.sources("No blocks") == {}
