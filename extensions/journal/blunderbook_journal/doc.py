"""The note parser (ROADMAP 19.2): a note's Markdown in, the tree Reading mode draws out.
Pure: no I/O, no database. The tree is JSON (plain dicts, lists, strings, numbers), stored
next to the text on every save so Reading mode is one read.

The tree::

    {"v": 1,
     "starts": [FEN, ...],          # each block's (or run's) start position
     "moves":  [{"id", "san", "uci", "fen", "no", "white", "prev", "next", "start",
                 "nag", "arrows", "squares"}, ...],
     "blocks": [...]}

Every playable move is in ``moves``, wherever it was written. ``prev`` is the move before
it (None at a start, then ``start`` is set); ``next`` the move after it in its own line, so
the board's ← → stay in the line you're in.

Blocks: ``heading`` (level, spans), ``para`` (spans), ``quote`` (spans), ``list`` (ordered,
start, items of depth and spans), ``rule``, ``ref`` (a ``[[log 12]]`` on its own line),
``code`` (lang, text, and error when it's a PGN or FEN that couldn't be read), ``pgn``
(start, headers, items, result, note) and ``fen`` (start, arrows, squares, caption,
playable). A pgn block's items are ``{"move": id}``, ``{"comment": text}`` and
``{"line": items}`` for a variation, in the order written.

Spans: ``text`` (text, with ``b`` / ``i`` when bold or italic), ``code``, ``link`` (text,
href: web, mail and ``#`` links only), ``tag``, ``ref`` (kind, id, text) and ``move``
(text as typed, move).

Moves in a sentence: a run starts with a numbered move ("5. cxd5", "6...Nxd5") and goes on
while moves follow. It plays from the nearest block or run above it that reaches its first
move (the move number and side to move fit, and the whole run is legal), else from the
nearest block below it (you may write about a game before you paste it), sharing that
block's moves where it follows them. A run starting at 1. with no such block plays from
the start. A run that can't be played stays text."""

import re
from dataclasses import dataclass
from typing import Final

import chess

from blunderbook_journal import moves, notes

DOC_VERSION: Final = 1

type Json = dict[str, object]
type Pos = tuple[str, int]  # ("s", start) or ("n", move id)

_FENCE: Final = "```"
_HEADING: Final = re.compile(r"^\s{0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
_RULE: Final = re.compile(r"^\s{0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_REF_LINE: Final = re.compile(r"^\s*\[\[(log|game)\s+(\d{1,9})\]\]\s*$")
_QUOTE: Final = re.compile(r"^\s{0,3}>[ \t]?(.*)$")
_ITEM: Final = re.compile(r"^([ \t]*)([-*+]|\d{1,9}[.)])[ \t]+(.*)$")
_INLINE: Final = re.compile(
    r"(?P<code>(?P<ticks>`+)(?P<codetext>.+?)(?<!`)(?P=ticks)(?!`))"
    r"|(?P<ref>\[\[(?P<kind>log|game)\s+(?P<num>\d{1,9})\]\])"
    r"|(?P<link>\[(?P<ltext>[^\]\n]+)\]\((?P<href>[^)\s]+)\))"
    r"|(?P<esc>\\(?P<echar>[\\`*_\[\]#(){}!.+\-]))"
    r"|(?P<delim>\*\*|__|\*|_)",
    re.DOTALL,
)
_SAFE_HREF: Final = re.compile(r"^(?:https?://|mailto:|#)", re.IGNORECASE)
_RUN: Final = "run"  # a placeholder span, never in the tree
_UNKNOWN: Final = re.compile(r"^[?.\s-]*$")  # "?", "????.??.??": a header with no value


def parse(body: str) -> Json:
    """The tree for a note's text."""
    return _Doc().read(body)


def sources(body: str) -> dict[int, tuple[int, int]]:
    """Where each ``` block's text is in the note: the tree's block index -> its first line
    and the line after its last (0-based, in the text split at its line breaks)."""
    reader = _Doc()
    reader.read(body)
    return reader.sources


# ---------------------------------------------------------------- the builder


@dataclass(slots=True)
class _Node:
    id: int
    san: str
    uci: str
    fen: str
    no: int
    white: bool
    prev: int | None
    next: int | None
    start: int | None
    nag: str
    marks: moves.Marks

    def json(self) -> Json:
        return {
            "id": self.id,
            "san": self.san,
            "uci": self.uci,
            "fen": self.fen,
            "no": self.no,
            "white": self.white,
            "prev": self.prev,
            "next": self.next,
            "start": self.start,
            "nag": self.nag,
            "arrows": [list(a) for a in self.marks.arrows],
            "squares": [list(s) for s in self.marks.squares],
        }


@dataclass(frozen=True, slots=True)
class _Delim:
    marker: str
    opens: bool
    closes: bool


type _Token = tuple[str, str] | tuple[str, Json] | tuple[str, _Delim]


class _Doc:
    def __init__(self) -> None:
        self.starts: list[str] = []
        self.nodes: list[_Node] = []
        self.children: dict[Pos, list[int]] = {}
        self.contexts: list[_Context] = []  # where runs may start
        self.blocks: list[Json] = []
        # Runs found in text, played once every block is read: (spans, index, block).
        self.pending: list[tuple[list[Json], int, int]] = []
        self.sources: dict[int, tuple[int, int]] = {}  # a ``` block's lines, by block index

    def read(self, body: str) -> Json:
        lines = body.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        i = 0
        while i < len(lines):
            i = self._block(lines, i)
        self._play_runs()
        return {
            "v": DOC_VERSION,
            "starts": self.starts,
            "moves": [node.json() for node in self.nodes],
            "blocks": self.blocks,
        }

    # ------------------------------------------------------------ blocks

    def _block(self, lines: list[str], i: int) -> int:
        """Read the block that starts at line ``i``; the line after it."""
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            return i + 1
        if stripped.startswith(_FENCE):
            info = stripped[len(_FENCE) :].strip()
            lang = info.split()[0].casefold() if info else ""
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith(_FENCE):
                j += 1
            self.sources[len(self.blocks)] = (i + 1, j)
            self._fenced(lang, "\n".join(lines[i + 1 : j]))
            return j + 1
        if heading := _HEADING.match(line):
            level = len(heading.group(1))
            self.blocks.append(
                {"t": "heading", "level": level, "spans": self._spans(heading.group(2) or "")}
            )
            return i + 1
        if _RULE.match(line):
            self.blocks.append({"t": "rule"})
            return i + 1
        if ref := _REF_LINE.match(line):
            self.blocks.append({"t": "ref", "kind": ref.group(1), "id": int(ref.group(2))})
            return i + 1
        if _QUOTE.match(line):
            j, quoted = i, []
            while j < len(lines) and (quote := _QUOTE.match(lines[j])):
                quoted.append(quote.group(1))
                j += 1
            self.blocks.append({"t": "quote", "spans": self._spans("\n".join(quoted))})
            return j
        if _list_item(line) is not None:
            return self._list(lines, i)
        j = i + 1
        while j < len(lines) and lines[j].strip() and not _interrupts(lines[j]):
            j += 1
        text = "\n".join(part.strip() for part in lines[i:j])
        self.blocks.append({"t": "para", "spans": self._spans(text)})
        return j

    def _list(self, lines: list[str], i: int) -> int:
        first = _list_item(lines[i])
        assert first is not None
        ordered = first[1][0].isdigit()
        start = int(first[1][:-1]) if ordered else 1
        items: list[tuple[int, list[str]]] = []
        j = i
        while j < len(lines):
            item = _list_item(lines[j])
            if item is not None and item[1][0].isdigit() == ordered:
                indent, _, text = item
                items.append((min(len(indent.expandtabs(4)) // 2, 3), [text]))
                j += 1
                continue
            if lines[j].strip() and items and not _interrupts(lines[j]):
                items[-1][1].append(lines[j].strip())  # the item goes on
                j += 1
                continue
            if not lines[j].strip():
                k = j
                while k < len(lines) and not lines[k].strip():
                    k += 1
                after = _list_item(lines[k]) if k < len(lines) else None
                if after is not None and after[1][0].isdigit() == ordered:
                    j = k
                    continue
            break
        self.blocks.append(
            {
                "t": "list",
                "ordered": ordered,
                "start": start,
                "items": [
                    {"depth": depth, "spans": self._spans("\n".join(text))} for depth, text in items
                ],
            }
        )
        return j

    def _fenced(self, lang: str, text: str) -> None:
        if lang == "pgn":
            game = moves.read_pgn(text)
            if game.error:
                self.blocks.append({"t": "code", "lang": lang, "text": text, "error": game.error})
                return
            self._pgn(game)
            return
        if lang == "fen":
            board = moves.read_fen(text)
            if board.error:
                self.blocks.append({"t": "code", "lang": lang, "text": text, "error": board.error})
                return
            start = self._start(board.fen)
            if board.playable:
                self.contexts.append(_Context(len(self.blocks), 0, [("s", start)]))
            self.blocks.append(
                {
                    "t": "fen",
                    "start": start,
                    "arrows": [list(a) for a in board.marks.arrows],
                    "squares": [list(s) for s in board.marks.squares],
                    "caption": board.caption,
                    "playable": board.playable,
                }
            )
            return
        self.blocks.append({"t": "code", "lang": lang, "text": text})

    def _pgn(self, game: moves.PgnBlock) -> None:
        start = self._start(game.start)
        offset = len(self.nodes)
        for index, move in enumerate(game.moves):
            node = _Node(
                id=offset + index,
                san=move.san,
                uci=move.uci,
                fen=move.fen,
                no=move.no,
                white=move.white,
                prev=None if move.prev is None else offset + move.prev,
                next=None if move.next is None else offset + move.next,
                start=start if move.prev is None else None,
                nag=move.nag,
                marks=move.marks,
            )
            self._add(node)
        positions: list[Pos] = [("s", start)]
        positions.extend(("n", offset + index) for index in range(len(game.moves)))
        self.contexts.append(_Context(len(self.blocks), 0, positions))
        block: Json = {
            "t": "pgn",
            "start": start,
            "headers": {k: v for k, v in game.headers if not _UNKNOWN.match(v)},
            "items": _items(game.items, offset),
            "result": game.result,
        }
        if game.note:
            block["note"] = game.note
        self.blocks.append(block)

    def _start(self, fen: str) -> int:
        self.starts.append(fen)
        return len(self.starts) - 1

    def _add(self, node: _Node) -> None:
        self.nodes.append(node)
        if node.prev is not None:
            at: Pos = ("n", node.prev)
        else:
            assert node.start is not None
            at = ("s", node.start)
        self.children.setdefault(at, []).append(node.id)

    def _fen(self, pos: Pos) -> str:
        kind, index = pos
        return self.starts[index] if kind == "s" else self.nodes[index].fen

    # ------------------------------------------------------------ inline

    def _spans(self, text: str) -> list[Json]:
        tokens = _tokens(text)
        spans: list[Json] = []
        bold = italic = 0
        for kind, value in tokens:
            if isinstance(value, _Delim):
                strong = len(value.marker) == 2
                change = 1 if value.opens else -1
                if strong:
                    bold += change
                else:
                    italic += change
                continue
            if isinstance(value, dict):
                spans.append(_styled(value, bold, italic) if kind == "link" else value)
                continue
            if kind == "text":
                spans.extend(_text(value, bold > 0, italic > 0))
        merged = _merged(spans)
        for index, span in enumerate(merged):
            if span["t"] == _RUN:
                self.pending.append((merged, index, len(self.blocks)))
        return merged

    # ------------------------------------------------------------ moves in sentences

    def _play_runs(self) -> None:
        """Play every run in the order written, then put its moves in its place: as move
        spans, or as text when it can't be played."""
        played: dict[tuple[int, int], list[Json]] = {}
        for spans, index, block in self.pending:
            run = spans[index]
            raw = str(run["text"])
            found = moves.typed_moves(raw)
            ids = self._resolve([one for _, one in found], block)
            if ids is None:
                out: list[Json] = [{"t": "text", "text": raw}]
            else:
                out = []
                at = 0
                for (offset, one), move_id in zip(found, ids, strict=True):
                    if offset > at:
                        out.append({"t": "text", "text": raw[at:offset]})
                    out.append({"t": "move", "text": one.text, "move": move_id})
                    at = offset + len(one.text)
            played[(id(spans), index)] = [
                _styled(span, bool(run.get("b")), bool(run.get("i"))) for span in out
            ]
        lists = {id(spans): spans for spans, _, _ in self.pending}
        for key, spans in lists.items():
            rebuilt: list[Json] = []
            for index, span in enumerate(spans):
                rebuilt.extend(played.get((key, index), [span]))
            spans[:] = _merged(rebuilt)

    def _resolve(self, typed: list[moves.Typed], block: int) -> list[int] | None:
        """The moves a run plays, sharing what's already written; None when it can't be
        played. It looks above first, nearest first (runs before it count too), then
        below, nearest first; a run from 1. with nothing to follow plays from the start."""
        first = typed[0]
        above = sorted(
            (c for c in self.contexts if c.block < block or c.run),
            key=lambda c: (c.block, c.run),
            reverse=True,
        )
        below = sorted((c for c in self.contexts if c.block > block and not c.run), key=_block_of)
        for context in [*above, *below]:
            fitting = [p for p in context.positions if moves.fits(self._fen(p), first)]
            following = [p for p in fitting if self._follows(p, first)]
            for pos in following + [p for p in fitting if p not in following]:
                if moves.legal_line(self._fen(pos), typed) is not None:
                    return self._play(pos, typed, block)
        from_the_start = first.number == 1 and first.black is False
        if from_the_start and moves.legal_line(chess.STARTING_FEN, typed) is not None:
            return self._play(("s", self._start(chess.STARTING_FEN)), typed, block)
        return None

    def _follows(self, pos: Pos, first: moves.Typed) -> bool:
        uci = moves.uci_of(self._fen(pos), first)
        return any(self.nodes[child].uci == uci for child in self.children.get(pos, ()))

    def _play(self, pos: Pos, typed: list[moves.Typed], block: int) -> list[int]:
        """Play a legal run from ``pos``: a move already written there is reused, the
        rest are added as a line of their own."""
        ids: list[int] = []
        at, last_new = pos, None
        for one in typed:
            played = moves.step(self._fen(at), one)
            assert played is not None
            same = [c for c in self.children.get(at, ()) if self.nodes[c].uci == played.uci]
            if same:
                ids.append(same[0])
                at, last_new = ("n", same[0]), None
                continue
            kind, index = at
            node = _Node(
                id=len(self.nodes),
                san=played.san,
                uci=played.uci,
                fen=played.fen,
                no=played.no,
                white=played.white,
                prev=index if kind == "n" else None,
                next=None,
                start=index if kind == "s" else None,
                nag=one.nag,
                marks=moves.NO_MARKS,
            )
            self._add(node)
            if last_new is not None:
                self.nodes[last_new].next = node.id
            ids.append(node.id)
            at, last_new = ("n", node.id), node.id
        runs = sum(1 for c in self.contexts if c.run)
        self.contexts.append(_Context(block, runs + 1, [pos, *(("n", i) for i in ids)]))
        return ids


@dataclass(frozen=True, slots=True)
class _Context:
    """Where a run may start: a block's positions, or an earlier run's."""

    block: int  # the block it's in
    run: int  # 0 for a block; 1, 2, ... for runs, in the order played
    positions: list[Pos]


def _block_of(context: _Context) -> int:
    return context.block


def _text(text: str, bold: bool, italic: bool) -> list[Json]:
    """Plain text: runs of moves become placeholders, played once every block is read;
    #tags become tag spans."""
    spans: list[Json] = []
    at = 0
    for run in moves.RUN.finditer(text):
        spans.extend(_tagged(text[at : run.start()], bold, italic))
        spans.append(_styled({"t": _RUN, "text": run.group(0)}, bold, italic))
        at = run.end()
    spans.extend(_tagged(text[at:], bold, italic))
    return spans


# ---------------------------------------------------------------- helpers


def _list_item(line: str) -> tuple[str, str, str] | None:
    """(indent, marker, text) of a list item. "1. e4 e5" is moves, not a list."""
    item = _ITEM.match(line)
    if item is None:
        return None
    if item.group(2)[0].isdigit() and moves.STARTS_WITH_A_MOVE.match(line):
        return None
    indent, marker, text = item.groups()
    return indent, marker, text


def _interrupts(line: str) -> bool:
    """Whether a line ends the paragraph above it."""
    stripped = line.strip()
    if stripped.startswith(_FENCE) or _HEADING.match(line) or _RULE.match(line):
        return True
    if _QUOTE.match(line) or _REF_LINE.match(line):
        return True
    item = _list_item(line)
    return item is not None and not item[1][0].isdigit()


def _tokens(text: str) -> list[_Token]:
    """Code, refs, links, escapes and emphasis markers; the rest as text. Markers that
    don't pair up are text too."""
    raw: list[_Token] = []
    at = 0
    for match in _INLINE.finditer(text):
        if match.start() > at:
            raw.append(("text", text[at : match.start()]))
        at = match.end()
        if match.group("code"):
            code = match.group("codetext")
            if code.startswith(" ") and code.endswith(" ") and code.strip():
                code = code[1:-1]
            raw.append(("code", {"t": "code", "text": code}))
        elif match.group("ref"):
            raw.append(
                (
                    "ref",
                    {
                        "t": "ref",
                        "kind": match.group("kind"),
                        "id": int(match.group("num")),
                        "text": match.group(0),
                    },
                )
            )
        elif match.group("link"):
            href = match.group("href")
            if _SAFE_HREF.match(href):
                raw.append(("link", {"t": "link", "text": match.group("ltext"), "href": href}))
            else:
                raw.append(("text", match.group(0)))
        elif match.group("esc"):
            raw.append(("text", match.group("echar")))
        else:
            marker = match.group("delim")
            before = text[match.start() - 1] if match.start() > 0 else " "
            after = text[match.end()] if match.end() < len(text) else " "
            opens, closes = not after.isspace(), not before.isspace()
            if marker[0] == "_":
                opens, closes = opens and not before.isalnum(), closes and not after.isalnum()
            raw.append(("delim", _Delim(marker, opens, closes)))
    if at < len(text):
        raw.append(("text", text[at:]))
    return _paired(raw)


def _paired(raw: list[_Token]) -> list[_Token]:
    """Keep the markers that open and close a run of text; the others become text."""
    paired: dict[int, _Delim] = {}
    stack: list[int] = []
    for index, (_, value) in enumerate(raw):
        if not isinstance(value, _Delim):
            continue
        match = next(
            (k for k in reversed(range(len(stack))) if _marker(raw, stack[k]) == value.marker),
            None,
        )
        if value.closes and match is not None:
            opener = stack[match]
            paired[opener] = _Delim(value.marker, True, False)
            paired[index] = _Delim(value.marker, False, True)
            del stack[match:]
        elif value.opens:
            stack.append(index)
    out: list[_Token] = []
    for index, token in enumerate(raw):
        value = token[1]
        if isinstance(value, _Delim):
            out.append(("delim", paired[index]) if index in paired else ("text", value.marker))
        else:
            out.append(token)
    return out


def _marker(raw: list[_Token], index: int) -> str:
    value = raw[index][1]
    return value.marker if isinstance(value, _Delim) else ""


def _tagged(text: str, bold: bool, italic: bool) -> list[Json]:
    spans: list[Json] = []
    at = 0
    for match in notes.TAG.finditer(text):
        tag = match.group(1).rstrip("-")
        end = match.start() + 1 + len(tag)
        if match.start() > at:
            spans.append(_styled({"t": "text", "text": text[at : match.start()]}, bold, italic))
        spans.append({"t": "tag", "tag": tag.casefold(), "text": text[match.start() : end]})
        at = end
    if at < len(text):
        spans.append(_styled({"t": "text", "text": text[at:]}, bold, italic))
    return spans


def _styled(span: Json, bold: bool | int, italic: bool | int) -> Json:
    if bold and span["t"] in ("text", "link", "move", _RUN):
        span = {**span, "b": True}
    if italic and span["t"] in ("text", "link", "move", _RUN):
        span = {**span, "i": True}
    return span


def _merged(spans: list[Json]) -> list[Json]:
    """Join neighbouring text spans with the same style."""
    out: list[Json] = []
    for span in spans:
        last = out[-1] if out else None
        if (
            last is not None
            and span["t"] == "text"
            and last["t"] == "text"
            and last.get("b") == span.get("b")
            and last.get("i") == span.get("i")
        ):
            out[-1] = {**last, "text": f"{last['text']}{span['text']}"}
        elif span["t"] != "text" or span["text"]:
            out.append(span)
    return out


def _items(items: tuple[moves.Item, ...], offset: int) -> list[Json]:
    out: list[Json] = []
    for item in items:
        match item:
            case moves.MoveItem(move):
                out.append({"move": offset + move})
            case moves.CommentItem(text):
                out.append({"comment": text})
            case moves.LineItem(inner):
                out.append({"line": _items(inner, offset)})
    return out
