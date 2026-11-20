"""What the Journal reads from a note's text on every save (ROADMAP 19.1): its title, the
line shown under it in the list, its #tags, and the PGN headers worth searching. Pure and
cheap: no chess, no Markdown tree (that's the parser, 19.2).

Lines inside a ``` block are code or chess: they give no tags, and no title or snippet."""

import re
from collections.abc import Iterator
from dataclasses import dataclass

TITLE_MAX = 200
SNIPPET_MAX = 140
FENCE = "```"

# A tag starts with a letter, after the start of a line or a space or bracket, so
# "Qxf7#", "C#", "##" and "# Heading" aren't tags.
TAG = re.compile(r"(?:^|(?<=[\s(\[{]))#([^\W\d_][\w-]*)")
_INLINE_CODE = re.compile(r"`[^`\n]*`")
_HEADER = re.compile(r'\[\s*(\w+)\s+"((?:[^"\\]|\\.)*)"\s*\]')
_SEARCHED = frozenset({"white", "black", "event", "site", "opening", "variation", "eco"})
_MARKERS = re.compile(r"^(?:#{1,6}\s+|>\s*|[-*+]\s+|\d+[.)]\s+)+")
_SLUG = re.compile(r"[^\w]+")


@dataclass(frozen=True, slots=True)
class Read:
    """What a save reads from the text."""

    title: str  # "" when the note has no line of text yet
    snippet: str
    tags: tuple[str, ...]  # lower case, sorted, each once
    players: str  # PGN header values, space-separated, for search


def read(body: str) -> Read:
    prose = [line for line, fenced in _lines(body) if not fenced]
    text = [line.strip() for line in prose if line.strip()]
    title = _cut(_MARKERS.sub("", text[0]).strip(), TITLE_MAX) if text else ""
    snippet = _cut(_MARKERS.sub("", text[1]).strip(), SNIPPET_MAX) if len(text) > 1 else ""
    return Read(title=title, snippet=snippet, tags=tags(prose), players=players(body))


def tags(lines: list[str]) -> tuple[str, ...]:
    """The #tags in these lines, lower case, without the '#', outside `inline code`."""
    found: set[str] = set()
    for line in lines:
        for match in TAG.finditer(_INLINE_CODE.sub(" ", line)):
            found.add(match.group(1).rstrip("-").casefold())
    return tuple(sorted(found))


def players(body: str) -> str:
    """The headers of the note's PGN blocks that you'd search by: players, event, site,
    opening and ECO. "?" (unknown) is left out."""
    values: list[str] = []
    block: str | None = None
    for line, _ in _lines(body):
        stripped = line.strip()
        if stripped.startswith(FENCE):
            block = None if block is not None else stripped[len(FENCE) :].strip().casefold()
            continue
        if block != "pgn":
            continue
        for name, value in _HEADER.findall(line):
            if name.casefold() in _SEARCHED and value.strip() not in ("", "?", "-"):
                values.append(value.strip())
    return " ".join(values)


def slug(title: str) -> str:
    """A file name for the note's export, from its title: "the-elephant-trap"."""
    words = _SLUG.sub("-", title.casefold()).strip("-_")
    return words[:60].rstrip("-_") or "note"


def _lines(body: str) -> Iterator[tuple[str, bool]]:
    """Each line, and whether it's inside a ``` block (the fence lines count as inside)."""
    fenced = False
    for line in body.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.strip().startswith(FENCE):
            yield line, True
            fenced = not fenced
            continue
        yield line, fenced


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "\N{HORIZONTAL ELLIPSIS}"
