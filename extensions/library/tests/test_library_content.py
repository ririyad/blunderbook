"""The Library's content (ROADMAP 11.1): the shipped entries, and every problem the checker
reports, each naming the file and the place in it."""

from pathlib import Path

import chess
import pytest
from blunderbook_library import content

from blunderbook import ext

PACKAGE = Path(content.__file__).parent

LEGAL = """
kind = "trap"
name = "Légal's trap"
side = "black"
moves = "1. e4 e5 2. Nf3 d6 3. Bc4 Bg4 4. Nc3 g6 5. Nxe5"
idea = "The bishop pins the knight, and the knight moves anyway."

[[next]]
move = "5... Bxd1"
line = "6. Bxf7+ Ke7 7. Nd5#"
says = "Takes the queen and is mated."
loses = true

[[practise]]
answers = ["dxe5"]
"""


def folder(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "content"
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, "utf-8")
    return root


def problems(tmp_path: Path, text: str, rel: str = "traps/legal-trap.toml") -> list[str]:
    return list(content.load(folder(tmp_path, {rel: text})).problems)


# ---------------------------------------------------------------- the shipped entries


def test_every_shipped_entry_is_fine() -> None:
    found = content.load()
    assert found.problems == ()
    kinds = [e.kind for e in found.entries]
    assert (kinds.count("opening"), kinds.count("trap"), kinds.count("tactic")) == (5, 6, 4)
    assert len({e.id for e in found.entries}) == 15


def test_the_shipped_entries_are_practised_from_their_side() -> None:
    for entry in content.load().entries:
        for practise in entry.practise:
            turn = chess.Board(practise.fen).turn
            assert (turn == chess.WHITE) == (entry.side == "white"), entry.id
            assert practise.answers, entry.id


def test_the_traps_from_the_test_games_are_there() -> None:
    """The fixture games' blunders (CLAUDE.md §12) are among the traps, so 11.4 can link
    them: each trap's losing move is the one played in that game."""
    losing = {
        e.id: [n.move.san for n in e.next if n.loses]
        for e in content.load().entries
        if e.kind == "trap"
    }
    assert losing["legal-trap"] == ["Bxd1"]
    assert losing["blackburne-shilling"] == ["Nxf7"]
    assert losing["elephant-trap"] == ["Nxd5"]
    assert losing["petrov-queen-trap"] == ["Nf6"]
    assert losing["scholars-mate"] == ["Nf6"]
    assert losing["caro-kann-smothered-mate"] == ["Ngf6"]


def test_an_entry_is_read_in_full(tmp_path: Path) -> None:
    (entry,) = content.load(folder(tmp_path, {"traps/legal-trap.toml": LEGAL})).entries
    assert (entry.id, entry.path, entry.kind, entry.side) == (
        "legal-trap", "traps/legal-trap.toml", "trap", "black"
    )  # fmt: skip
    assert entry.start_fen == chess.STARTING_FEN
    assert [m.label for m in entry.moves][-2:] == ["4... g6", "5. Nxe5"]
    assert entry.moves[-1].uci == "f3e5"
    (nxt,) = entry.next
    assert (nxt.move.label, nxt.loses) == ("5... Bxd1", True)
    assert [m.label for m in nxt.line] == ["6. Bxf7+", "6... Ke7", "7. Nd5#"]
    (practise,) = entry.practise
    assert practise.ply == 9
    assert practise.fen == entry.end_fen
    assert [a.uci for a in practise.answers] == ["d6e5"]
    assert practise.prompt == content.PROMPTS["trap"]


def test_practise_positions_inside_the_line(tmp_path: Path) -> None:
    text = """
kind = "opening"
name = "Italian Game"
side = "white"
moves = "1. e4 e5 2. Nf3 Nc6 3. Bc4"
idea = "Bishop to c4."

[[practise]]
after = "1... e5"
answers = ["Nf3"]

[[practise]]
after = "2...   Nc6"
answers = ["Bc4", "Bb5"]
"""
    (entry,) = content.load(folder(tmp_path, {"openings/italian.toml": text})).entries
    assert [p.ply for p in entry.practise] == [2, 4]
    assert [a.san for a in entry.practise[1].answers] == ["Bc4", "Bb5"]


def test_a_tactic_starts_from_its_fen(tmp_path: Path) -> None:
    text = """
kind = "tactic"
name = "Smothered mate"
side = "white"
fen = "6rk/6pp/8/6N1/8/8/6PP/6K1 w - - 0 1"
idea = "A lone knight."

[[practise]]
answers = ["Nf7#"]
"""
    (entry,) = content.load(folder(tmp_path, {"tactics/smothered.toml": text})).entries
    assert entry.moves == ()
    assert entry.practise[0].ply == 0
    assert entry.practise[0].answers[0].label == "1. Nf7#"


# ---------------------------------------------------------------- problems

BAD = [
    (
        LEGAL.replace("7. Nd5#", "7. Nd6#"),
        "next 1: 7. Nd6# isn't legal after 6... Ke7.",
    ),
    (
        LEGAL.replace("2. Nf3 d6", "2. Ke3 d6"),
        "moves: 2. Ke3 isn't legal after 1... e5.",
    ),
    (
        LEGAL.replace("6. Bxf7+", "6. Bxf7"),
        "next 1: write 6. Bxf7 as Bxf7+.",
    ),
    (
        LEGAL.replace("2. Nf3 d6 3.", "2. Nf3 3... d6 3."),
        "moves: '3...' should be 2... (after 2. Nf3).",
    ),
    (
        LEGAL.replace("1. e4 e5 2. Nf3", "1. e4 1. e5 2. Nf3"),
        "moves: '1.' should be 1... (after 1. e4).",
    ),
    (
        LEGAL.replace("5. Nxe5", "5. Nxe5 5..."),
        "moves: a move number with no move after it.",
    ),
    (
        LEGAL.replace("Bg4 4. Nc3", "Bg4 4. hello"),
        "moves: 'hello' isn't a move.",
    ),
    (
        LEGAL.replace('name = "Légal\'s trap"', 'nmae = "Légal\'s trap"'),
        "unknown field 'nmae' (there's eco, fen, idea, kind, moves, name, next, opening, "
        "practise, side).",
    ),
    (
        LEGAL.replace('kind = "trap"', 'kind = "gambit"'),
        "kind is 'opening' or 'trap' or 'tactic', not 'gambit'.",
    ),
    (
        LEGAL.replace('kind = "trap"', 'kind = "tactic"'),
        "kind is 'tactic', so the file goes in tactics/, not traps/.",
    ),
    (LEGAL.replace('side = "black"', 'side = "Black"'), "side is 'white' or 'black', not 'Black'."),
    (LEGAL.replace('side = "black"\n', ""), "side is 'white' or 'black'."),
    (LEGAL.replace('name = "Légal\'s trap"\n', ""), "name is missing."),
    (LEGAL.replace('idea = "The bishop', 'idea = "  "\n#'), "idea should be some text."),
    (
        LEGAL.replace('name = "Légal\'s trap"', 'name = "Légal\'s trap"\neco = "c41"'),
        "eco 'c41' isn't an ECO code like C41.",
    ),
    (
        LEGAL.replace('moves = "1. e4', 'fen = "8/8/8/8/8/8/8/8 w - - 0 1"\nmoves = "1. e4'),
        "fen isn't a legal position.",
    ),
    (
        LEGAL.replace('moves = "1. e4', 'fen = "not a fen"\nmoves = "1. e4'),
        "fen isn't a position: ",
    ),
    (
        LEGAL.split("moves =")[0] + 'idea = "x"\n[[practise]]\nanswers = ["e4"]\n',
        "give the moves, or a fen to start from.",
    ),
    (LEGAL.split("[[practise]]")[0], "add at least one [[practise]] position."),
    (
        LEGAL + 'after = "4... g6"\n',
        "practise 1: it's White to move there, but the entry is practised as Black.",
    ),
    (
        LEGAL + 'after = "4... g5"\n',
        "practise 1: after '4... g5' isn't a move of the line (1. e4, 1... e5, 2. Nf3, ...).",
    ),
    (
        LEGAL.replace('answers = ["dxe5"]', 'answers = ["dxe5", "Bxd1"]'),
        "practise 1: Bxd1 is marked as losing in next, so it can't be an answer.",
    ),
    (
        LEGAL.replace('answers = ["dxe5"]', 'answers = ["dxe5", "dxe5"]'),
        "practise 1: dxe5 is in answers twice.",
    ),
    (
        LEGAL.replace('answers = ["dxe5"]', "answers = []"),
        'practise 1: answers is a list of moves, like ["dxe5"].',
    ),
    (
        LEGAL.replace('answers = ["dxe5"]', 'answers = ["5... dxe5"]'),
        "practise 1: write '5...' without its move number.",
    ),
    (
        LEGAL + '[[practise]]\nafter = "3. Bc4"\nanswers = ["Nc6"]\n',
        "practise 2: the line goes on with 3... Bg4; add Bg4 to answers.",
    ),
    (
        LEGAL.replace('move = "5... Bxd1"', 'move = "5... Bxd1 6. Bxf7+"'),
        "next 1: move is one move; the rest goes in line.",
    ),
    (LEGAL.replace("loses = true", 'loses = "yes"'), "next 1: loses is true or false."),
    (LEGAL.replace('says = "Takes the queen and is mated."\n', ""), "next 1: says is missing."),
    (LEGAL.replace("[[next]]", "[next]"), "next should be [[next]] tables."),
    (LEGAL.replace('kind = "trap"', 'kind = "trap'), "isn't valid TOML: "),
]


@pytest.mark.parametrize(("text", "problem"), BAD)
def test_problems(tmp_path: Path, text: str, problem: str) -> None:
    (found,) = problems(tmp_path, text)
    assert found.startswith("traps/legal-trap.toml: " + problem), found


def test_an_ambiguous_move(tmp_path: Path) -> None:
    text = LEGAL.replace(
        "1. e4 e5 2. Nf3 d6 3. Bc4 Bg4 4. Nc3 g6 5. Nxe5", "1. Nf3 d5 2. d3 e5 3. Nd2"
    )
    assert problems(tmp_path, text) == [
        "traps/legal-trap.toml: moves: 3. Nd2 could be more than one piece after 2... e5; "
        "say which."
    ]


def test_files_and_folders(tmp_path: Path) -> None:
    root = folder(
        tmp_path,
        {
            "traps/Bad.toml": LEGAL,
            "traps/notes.md": "ignored",
            "gambits/x.toml": LEGAL,
            "loose.toml": LEGAL,
            "traps/copy.toml": LEGAL,
            "traps/legal.toml": LEGAL,
        },
    )
    assert content.load(root).problems == (
        "gambits/: not a kind; use openings, traps, tactics.",
        "loose.toml: put it in openings, traps, tactics.",
        "traps/Bad.toml: name the file in lowercase letters, digits and dashes (legal-trap.toml).",
        'traps/legal.toml: traps/copy.toml has the same name, "Légal\'s trap".',
    )
    assert [e.path for e in content.load(root).entries] == ["traps/copy.toml", "traps/legal.toml"]


def test_a_missing_folder(tmp_path: Path) -> None:
    assert content.load(tmp_path / "nope").problems == (f"{tmp_path / 'nope'} isn't a folder.",)


def test_not_utf8(tmp_path: Path) -> None:
    root = folder(tmp_path, {})
    (root / "traps").mkdir(parents=True)
    (root / "traps" / "x.toml").write_bytes(b'name = "L\xe9gal"')
    assert content.load(root).problems == ("traps/x.toml: isn't UTF-8 text.",)


# ---------------------------------------------------------------- the extension


def test_it_uses_only_the_host_api() -> None:
    assert ext.boundary_problems(PACKAGE) == []


def test_it_is_found_and_loads() -> None:
    point = ext.find("library")
    assert point is not None
    extension, problem = ext.load_one(point)
    assert problem is None
    assert extension is not None
    assert (extension.name, extension.title) == ("library", "Library")
    assert extension.router is not None and extension.web is not None  # 11.2
    assert extension.migrations is None  # library.db comes with 11.3
