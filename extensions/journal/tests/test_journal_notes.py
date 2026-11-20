"""What a save reads from a note's text (ROADMAP 19.1): title, snippet, tags, PGN headers."""

import pytest
from blunderbook_journal import notes
from journal_fakes import ELEPHANT, FENCE


def test_the_sample_note() -> None:
    read = notes.read(ELEPHANT)
    assert read.title == "The Elephant trap"
    assert read.snippet.startswith("The d5 pawn looks free, but after 5. cxd5")
    assert read.tags == ("qgd", "traps")
    assert read.players == "Club night Ivanov Petrova Queen's Gambit Declined D51"


def test_an_empty_note() -> None:
    assert notes.read("") == notes.Read(title="", snippet="", tags=(), players="")
    assert notes.read("\n  \n\n").title == ""


@pytest.mark.parametrize(
    ("body", "title"),
    [
        ("Just a line", "Just a line"),
        ("## Second level\ntext", "Second level"),
        ("\n\n   # Spaced  \n", "Spaced"),
        ("> A quote first", "A quote first"),
        ("- a list item", "a list item"),
        (f"{FENCE}pgn\n1. e4 e5\n{FENCE}\nAfter the game", "After the game"),
        (f"{FENCE}fen\n8/8/8/8/8/8/8/8 w - - 0 1\n{FENCE}", ""),  # only chess: untitled
        ("Windows line\r\nnext", "Windows line"),
        ("# **A new** note", "A new note"),
        ("# The _Elephant_ trap in `QGD`", "The Elephant trap in QGD"),
        ("[Lichess](https://lichess.org) study", "Lichess study"),
        ("snake_case_name and 2 * 3 * 4", "snake_case_name and 2 * 3 * 4"),
        (r"\*not italic\* and __bold__", "*not italic* and bold"),
        ("[[log 12]] again", "[[log 12]] again"),
    ],
)
def test_the_title(body: str, title: str) -> None:
    assert notes.read(body).title == title


def test_the_snippet_is_plain_text_too() -> None:
    assert notes.read("# Title\nA **bold** line with `code`").snippet == "A bold line with code"


def test_long_titles_and_snippets_are_cut() -> None:
    read = notes.read("x" * 500 + "\n" + "y" * 500)
    assert len(read.title) == notes.TITLE_MAX and read.title.endswith("\N{HORIZONTAL ELLIPSIS}")
    assert len(read.snippet) == notes.SNIPPET_MAX


def test_the_snippet_skips_blocks() -> None:
    body = f"# Title\n\n{FENCE}pgn\n1. e4\n{FENCE}\n\n- First point\n"
    assert notes.read(body).snippet == "First point"


@pytest.mark.parametrize(
    ("line", "found"),
    [
        ("#traps #QGD", ("qgd", "traps")),
        ("A tag at the end #caro-kann.", ("caro-kann",)),
        ("(#endgame) and [#otb]", ("endgame", "otb")),
        ("#échecs #шахматы", ("échecs", "шахматы")),
        ("#traps and #traps again", ("traps",)),
        ("# Heading", ()),
        ("Qxf7# mates", ()),
        ("C# and ab#cd", ()),
        ("#1 choice and #2nd", ()),
        ("##double", ()),
        ("`#not-a-tag` but #yes", ("yes",)),
        ("#trailing-", ("trailing",)),
    ],
)
def test_tags(line: str, found: tuple[str, ...]) -> None:
    assert notes.read(f"Title\n{line}").tags == found


def test_tags_inside_blocks_are_ignored() -> None:
    body = f"Title #outside\n{FENCE}pgn\n1. e4 {{#inside}} e5\n{FENCE}\n"
    assert notes.read(body).tags == ("outside",)


def test_players_only_from_pgn_blocks() -> None:
    body = (
        '[White "Prose"]\n'
        f'{FENCE}pgn\n[White "Anand"] [Black "?"] [Date "2026.01.01"] [Site "-"]\n1. e4\n{FENCE}\n'
        f'{FENCE}text\n[White "Code"]\n{FENCE}\n'
        f'{FENCE}PGN\n[Black "Carlsen"]\n{FENCE}\n'
    )
    assert notes.read(body).players == "Anand Carlsen"


def test_an_unclosed_block_runs_to_the_end() -> None:
    body = f'Title\n{FENCE}pgn\n[White "Tal"]\n#nottag'
    read = notes.read(body)
    assert (read.tags, read.players) == ((), "Tal")


@pytest.mark.parametrize(
    ("title", "slug"),
    [
        ("The Elephant trap", "the-elephant-trap"),
        ("Caro-Kann: the 4... Bf5 lines", "caro-kann-the-4-bf5-lines"),
        ("Échecs et mat", "échecs-et-mat"),
        ("", "note"),
        ("???", "note"),
        ("a" * 100, "a" * 60),
    ],
)
def test_slug(title: str, slug: str) -> None:
    assert notes.slug(title) == slug
