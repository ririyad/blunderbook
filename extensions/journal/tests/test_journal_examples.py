"""The starter notes in ``examples/`` (once the Library's entries): each reads as a note,
with its title and tag, and every game and diagram in it plays."""

from pathlib import Path
from typing import Any

import pytest
from blunderbook_journal import doc, notes

EXAMPLES = Path(__file__).parents[1] / "examples"
FILES = sorted(EXAMPLES.rglob("*.md"))
TAGS = {"openings": "openings", "traps": "traps", "tactics": "tactics"}


def test_there_are_examples() -> None:
    assert {p.parent.name for p in FILES} == set(TAGS)
    assert len(FILES) == 15


@pytest.mark.parametrize("path", FILES, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_an_example_plays(path: Path) -> None:
    text = path.read_text("utf-8")
    read = notes.read(text)
    assert read.title and not read.title.startswith("#")
    assert TAGS[path.parent.name] in read.tags
    tree = doc.parse(text)
    blocks: list[dict[str, Any]] = tree["blocks"]  # type: ignore[assignment]
    assert not [b for b in blocks if b.get("error")], path.name
    games = [b for b in blocks if b["t"] == "pgn"]
    assert len(games) == 1 and games[0]["items"], path.name
    diagrams = [b for b in blocks if b["t"] == "fen"]
    assert all(b["playable"] for b in diagrams)
    assert (path.parent.name == "tactics") == bool(diagrams)
