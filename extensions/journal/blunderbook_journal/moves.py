"""The chess in a note (ROADMAP 19.2), read with python-chess: ```pgn and ```fen blocks, the
arrows and highlights in them, and runs of moves typed in a sentence ("after 5. cxd5 exd5
6. Nxd5??"), and the boards you play on (ROADMAP 19.4). Pure: text in, positions out.

A block's reading is cached by its text, so saving a long note again re-reads only the
blocks that changed. Named ``moves`` rather than ``chess``, which would read like
python-chess itself."""

import io
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Final

import chess
import chess.pgn

# ---------------------------------------------------------------- shared shapes


@dataclass(frozen=True, slots=True)
class Marks:
    """Arrows (from, to, colour) and highlighted squares (square, colour), as Lichess
    writes them: ``[%cal Rc3d5,Gf8b4]`` and ``[%csl Rd5]``. Colours are R, G, B or Y."""

    arrows: tuple[tuple[str, str, str], ...] = ()
    squares: tuple[tuple[str, str], ...] = ()


NO_MARKS: Final = Marks()


@dataclass(frozen=True, slots=True)
class Move:
    """One move of a block, by its index in the block's ``moves``."""

    san: str
    uci: str
    fen: str  # the position after it
    no: int  # its move number
    white: bool  # White played it
    prev: int | None  # the move before; None: the block's start position
    next: int | None  # the move after, in the same line
    nag: str  # "??", "?", "?!", "!?", "!", "!!" or ""
    marks: Marks


@dataclass(frozen=True, slots=True)
class MoveItem:
    move: int


@dataclass(frozen=True, slots=True)
class CommentItem:
    text: str


@dataclass(frozen=True, slots=True)
class LineItem:
    """A variation: the moves played instead of the move just before it."""

    items: tuple[Item, ...]


type Item = MoveItem | CommentItem | LineItem


@dataclass(frozen=True, slots=True)
class PgnBlock:
    """A ```pgn block. When ``error`` is set it couldn't be read and has no moves."""

    headers: tuple[tuple[str, str], ...] = ()
    start: str = chess.STARTING_FEN
    moves: tuple[Move, ...] = ()
    items: tuple[Item, ...] = ()  # in the order written: moves, comments, variations
    result: str = ""
    error: str = ""
    note: str = ""  # e.g. that only the first game is shown


@dataclass(frozen=True, slots=True)
class FenBlock:
    fen: str = ""
    marks: Marks = NO_MARKS
    caption: str = ""
    playable: bool = False  # a legal position: moves can be played from it
    error: str = ""


# ---------------------------------------------------------------- notation

NAGS: Final = {1: "!", 2: "?", 3: "!!", 4: "??", 5: "!?", 6: "?!"}

SAN: Final = (
    r"(?:O-O-O|O-O|0-0-0|0-0|[KQRBN][a-h]?[1-8]?x?[a-h][1-8]|[a-h](?:x[a-h])?[1-8](?:=?[QRBN])?)"
    r"[+#]?"
)
NAG: Final = r"(?:!!|\?\?|!\?|\?!|!|\?)?"
NUMBER: Final = r"(\d{1,3})\s?(\.\.\.|…|\.)\s?"
# A typed move: an optional number ("6." or "6..."), the move, an optional mark.
TYPED: Final = re.compile(rf"(?:{NUMBER})?({SAN})({NAG})(?![\w+#=-])")
# A run in a sentence starts with a numbered move; more moves follow after spaces.
RUN: Final = re.compile(
    rf"(?<![\w.]){NUMBER}{SAN}{NAG}(?![\w+#=-])(?:\s+(?:\d{{1,3}}\s?(?:\.\.\.|…|\.)\s?)?{SAN}{NAG}(?![\w+#=-]))*"
)
STARTS_WITH_A_MOVE: Final = re.compile(rf"\s*\d{{1,3}}\s?(?:\.\.\.|…|\.)\s?{SAN}(?![\w-])")

_COMMAND: Final = re.compile(r"\[%(\w+)\s*([^\]]*)\]")
_ARROW: Final = re.compile(r"^([RGBY])([a-h][1-8])([a-h][1-8])$")
_SQUARE: Final = re.compile(r"^([RGBY])([a-h][1-8])$")
_SAN_IN_ERROR: Final = re.compile(r"san: '([^']*)'")
# '[White "Tal"] [Black "Petrosian"]' on one line: python-chess reads one header a line.
_HEADERS_ON_ONE_LINE: Final = re.compile(r'"\][ \t]+\[(?=\w+[ \t]+")')
_STANDARD: Final = frozenset({"", "standard", "chess", "normal", "from position"})


@dataclass(frozen=True, slots=True)
class Typed:
    """A move as typed in a sentence: ``text`` is exactly what was typed for it."""

    text: str
    number: int | None
    black: bool | None  # "6..." True, "6." False, no number None
    san: str
    nag: str


def typed_moves(run: str) -> list[tuple[int, Typed]]:
    """The moves of a run found by :data:`RUN`, each with where it starts in ``run``."""
    found: list[tuple[int, Typed]] = []
    for match in TYPED.finditer(run):
        number, dots, san, nag = match.groups()
        found.append(
            (
                match.start(),
                Typed(
                    text=match.group(0),
                    number=None if number is None else int(number),
                    black=None if dots is None else dots != ".",
                    san=san.replace("0", "O"),
                    nag=nag,
                ),
            )
        )
    return found


@dataclass(frozen=True, slots=True)
class Played:
    san: str
    uci: str
    fen: str
    no: int
    white: bool


def fits(fen: str, first: Typed) -> bool:
    """Whether a run whose first move is ``first`` can start at ``fen``: the same move
    number and side to move. Read from the FEN's own fields: no board is built."""
    fields = fen.split()
    return f"{first.number}" == fields[5] and first.black == (fields[1] == "b")


def step(fen: str, typed: Typed) -> Played | None:
    """Play one typed move at ``fen``. None when it isn't legal there, or its number
    doesn't fit the position."""
    board = chess.Board(fen)
    if typed.number is not None and (
        typed.number != board.fullmove_number or typed.black != (board.turn == chess.BLACK)
    ):
        return None
    try:
        move = board.parse_san(typed.san)
    except ValueError:
        return None
    san = board.san(move)
    no, white = board.fullmove_number, board.turn == chess.WHITE
    board.push(move)
    return Played(san=san, uci=move.uci(), fen=board.fen(), no=no, white=white)


def uci_of(fen: str, typed: Typed) -> str | None:
    """The move ``typed`` is at ``fen``, as UCI, or None when it isn't legal there."""
    try:
        return chess.Board(fen).parse_san(typed.san).uci()
    except ValueError:
        return None


# ---------------------------------------------------------------- arrows


def marks(text: str) -> tuple[Marks, str]:
    """The arrows and highlights in a comment, and the comment without any ``[%...]``
    command (clocks and evals go too)."""
    arrows: list[tuple[str, str, str]] = []
    squares: list[tuple[str, str]] = []
    for name, value in _COMMAND.findall(text):
        for part in value.replace(" ", "").split(","):
            if name == "cal" and (arrow := _ARROW.match(part)):
                colour, start, end = arrow.groups()
                arrows.append((start, end, colour))
            elif name == "csl" and (square := _SQUARE.match(part)):
                colour, where = square.groups()
                squares.append((where, colour))
    rest = " ".join(_COMMAND.sub(" ", text).split())
    return Marks(tuple(arrows), tuple(squares)), rest


# ---------------------------------------------------------------- blocks


@lru_cache(maxsize=512)
def read_fen(text: str) -> FenBlock:
    """A ```fen block: the position on its first line, then arrows and highlights
    (``{[%cal Rc3d5][%csl Rd5]}``) and a caption, in any order."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return FenBlock(error="This FEN block is empty.")
    first, rest = lines[0], " ".join(lines[1:])
    try:
        board = chess.Board(first)
    except ValueError:
        return FenBlock(error=f"Couldn't read the FEN '{_short(first)}'.")
    found, caption = marks(rest)
    caption = " ".join(caption.replace("{", " ").replace("}", " ").split())
    return FenBlock(fen=board.fen(), marks=found, caption=caption, playable=board.is_valid())


@lru_cache(maxsize=512)
def read_pgn(text: str) -> PgnBlock:
    """A ```pgn block: its first game, with variations, comments, marks and arrows."""
    handle = io.StringIO(_HEADERS_ON_ONE_LINE.sub('"]\n[', text))
    game = chess.pgn.read_game(handle, Visitor=_Builder)
    if game is None:
        return PgnBlock(error="This PGN block is empty.")
    if game.errors:
        return PgnBlock(error=_describe(game.errors[0]))
    variant = game.headers.get("Variant", "").strip()
    board = game.board()
    if variant.casefold() not in _STANDARD or board.chess960 or type(board) is not chess.Board:
        return PgnBlock(error=f"{variant or 'This variant'} isn't supported, only standard chess.")
    if not game.variations and "FEN" not in game.headers:
        return PgnBlock(error="There are no moves in this PGN.")
    walk = _Walk()
    try:
        items = walk.line(game, board, None)
    except _NullMove as stop:
        return PgnBlock(error=f"Null moves (--) aren't supported (move {stop.number}).")
    opening = _comment(game.comment)
    if opening is not None:
        items = (opening, *items)
    note = ""
    if chess.pgn.read_game(handle, Visitor=_Builder) is not None:
        note = "Only the first game in this block is shown."
    return PgnBlock(
        headers=tuple((k, v) for k, v in game.headers.items() if v.strip() not in ("", "?")),
        start=game.board().fen(),
        moves=tuple(walk.moves),
        items=items,
        result=game.headers.get("Result", ""),
        note=note,
    )


class _Builder(chess.pgn.GameBuilder[chess.pgn.Game]):
    """Collects errors without logging them."""

    def handle_error(self, error: Exception) -> None:
        self.game.errors.append(error)


class _NullMove(Exception):
    def __init__(self, number: int) -> None:
        super().__init__(number)
        self.number = number


class _Walk:
    """Numbers a game's moves in the order they're written: each move, then the
    variations that replace it, then the rest of the line."""

    def __init__(self) -> None:
        self.moves: list[Move] = []
        self.nodes: list[chess.pgn.ChildNode] = []  # each move's node, by its index

    def line(
        self, parent: chess.pgn.GameNode, board: chess.Board, prev: int | None
    ) -> tuple[Item, ...]:
        """The items of the line that continues from ``parent`` with its main move."""
        items: list[Item] = []
        node, before, pushed = parent, prev, 0
        while node.variations:
            main, *others = node.variations
            index = self._add(main, board, before)
            items.append(MoveItem(index))
            comment = _comment(main.comment)
            if comment is not None:
                items.append(comment)
            for other in others:
                items.append(LineItem(self._variation(other, board, before)))
            board.push(main.move)
            pushed += 1
            node, before = main, index
        for _ in range(pushed):
            board.pop()
        return tuple(items)

    def _variation(
        self, start: chess.pgn.ChildNode, board: chess.Board, prev: int | None
    ) -> tuple[Item, ...]:
        items: list[Item] = []
        opening = _comment(start.starting_comment)
        if opening is not None:
            items.append(opening)
        index = self._add(start, board, prev)
        items.append(MoveItem(index))
        comment = _comment(start.comment)
        if comment is not None:
            items.append(comment)
        board.push(start.move)
        items.extend(self.line(start, board, index))
        board.pop()
        return tuple(items)

    def _add(self, node: chess.pgn.ChildNode, board: chess.Board, prev: int | None) -> int:
        move = node.move
        if not move:
            raise _NullMove(board.fullmove_number)
        san = board.san(move)
        no, white = board.fullmove_number, board.turn == chess.WHITE
        board.push(move)
        fen = board.fen()
        board.pop()
        found, _ = marks(node.comment)
        nag = next((NAGS[n] for n in sorted(node.nags) if n in NAGS), "")
        index = len(self.moves)
        self.moves.append(Move(san, move.uci(), fen, no, white, prev, None, nag, found))
        self.nodes.append(node)
        if prev is not None and node.parent.variations[0] is node:
            self.moves[prev] = replace(self.moves[prev], next=index)
        return index


def _comment(text: str) -> CommentItem | None:
    _, rest = marks(text)
    return CommentItem(rest) if rest else None


def _describe(error: Exception) -> str:
    message = str(error)
    found = _SAN_IN_ERROR.search(message)
    move = found.group(1) if found else ""
    if message.startswith("illegal san") and move:
        return f"Couldn't play {move}: it isn't legal there."
    if message.startswith("ambiguous san") and move:
        return f"Couldn't play {move}: more than one piece can make it."
    if message.startswith("invalid san") and move:
        return f"Couldn't read the move '{move}'."
    return f"Couldn't read this PGN: {_short(message)}"


def _short(text: str, limit: int = 80) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "\N{HORIZONTAL ELLIPSIS}"


def legal_line(fen: str, typed: Sequence[Typed]) -> list[Played] | None:
    """Play a whole run from ``fen``; None when any move of it can't be played."""
    played: list[Played] = []
    for one in typed:
        move = step(fen, one)
        if move is None:
            return None
        played.append(move)
        fen = move.fen
    return played


# ---------------------------------------------------------------- boards you play on (19.4)


class BoardError(ValueError):
    """A position or a move that can't be played, with a plain message."""


@dataclass(frozen=True, slots=True)
class Position:
    """Moves played from a FEN: each one, where they end, and what can be played next."""

    start: str
    moves: tuple[Played, ...]
    fen: str
    legal: tuple[str, ...]  # UCI, every promotion spelled out ("e7e8q", "e7e8n", ...)
    line: str  # "6. e3 Be7 7. Bd3", "6... Be7"; "" with no moves
    pgn: str  # the line as a PGN game, with the start position when it isn't the usual one
    over: str  # "Checkmate", "Stalemate", "Insufficient material" or ""


def board_at(fen: str) -> chess.Board:
    """The position of a FEN, if it can be played. Raises BoardError."""
    try:
        board = chess.Board(fen)
    except ValueError:
        raise BoardError(f"Couldn't read the FEN '{_short(fen.strip())}'.") from None
    if not board.is_valid():
        raise BoardError("This isn't a legal position, so it can't be played.")
    return board


def position(fen: str, ucis: Sequence[str]) -> Position:
    """Play ``ucis`` from ``fen``. Raises BoardError for a FEN that can't be played or a
    move that isn't legal, naming it."""
    board = board_at(fen)
    start = board.fen()
    played: list[Played] = []
    for uci in ucis:
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            raise BoardError(f"Couldn't read the move '{_short(uci, 12)}'.") from None
        if move not in board.legal_moves:
            raise BoardError(f"{uci} isn't legal there{_after(played)}.")
        no, white = board.fullmove_number, board.turn == chess.WHITE
        san = board.san(move)
        board.push(move)
        played.append(Played(san=san, uci=uci, fen=board.fen(), no=no, white=white))
    line = written(played)
    headers = "" if start == chess.STARTING_FEN else f'[SetUp "1"]\n[FEN "{start}"]\n\n'
    outcome = board.outcome(claim_draw=False)
    over = "" if outcome is None else outcome.termination.name.replace("_", " ").capitalize()
    result = outcome.result() if outcome is not None else "*"
    return Position(
        start=start,
        moves=tuple(played),
        fen=board.fen(),
        legal=tuple(sorted(m.uci() for m in board.legal_moves)),
        line=line,
        pgn=f"{headers}{line} {result}".lstrip(),
        over=over,
    )


def written(played: Sequence[Played]) -> str:
    """Moves as you'd write them: "6. e3 Be7 7. Bd3", or "6... Be7 7. Bd3"."""
    parts: list[str] = []
    for i, move in enumerate(played):
        if move.white:
            parts.append(f"{move.no}. {move.san}")
        elif i == 0:
            parts.append(f"{move.no}... {move.san}")
        else:
            parts.append(move.san)
    return " ".join(parts)


def _after(played: Sequence[Played]) -> str:
    if not played:
        return ""
    last = played[-1]
    return f" (after {last.no}{'.' if last.white else '...'} {last.san})"


def san_line(fen: str, ucis: Sequence[str], limit: int = 10) -> str:
    """An engine line as you'd write it, up to ``limit`` moves; it stops at a move that
    isn't legal."""
    board = chess.Board(fen)
    played: list[Played] = []
    for uci in ucis[:limit]:
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            break
        if move not in board.legal_moves:
            break
        no, white = board.fullmove_number, board.turn == chess.WHITE
        san = board.san(move)
        board.push(move)
        played.append(Played(san=san, uci=uci, fen=board.fen(), no=no, white=white))
    return written(played)


_HEADER_LINE: Final = re.compile(r'^\s*(?:\[\s*\w+\s+"(?:[^"\\]|\\.)*"\s*\]\s*)+$')
_NAG_OUT: Final = re.compile(r"\s+\$([1-6])(?!\d)")
_INSIDE: Final = re.compile(r"([({])[ \t]+|[ \t]+([)}])")  # "( 6. e3" -> "(6. e3"
# A move number left at the end of a line goes to the next, with its "(" when it opens a
# variation: "9.\nKxd2" -> "\n9. Kxd2", " (4...\nNd7" -> "\n(4... Nd7".
_SPLIT_NUMBER: Final = re.compile(r" (\(?\d+\.(?:\.\.)?)\n")


def with_line(text: str, after: int | None, ucis: Sequence[str]) -> str | None:
    """A ```pgn block's text with a line added: played after move ``after`` (the block's
    own numbering, as :func:`read_pgn` gives it), or from the start with None. Where the
    game already has those moves, the line follows them; the rest becomes a variation (or
    the line's continuation, at its end). None when nothing is new.

    The headers stay as written; the moves are written out again by python-chess, with
    your comments, arrows and marks. Raises BoardError when the block can't be read, has
    more than one game, or a move isn't legal there."""
    read = read_pgn(text)
    if read.error:
        raise BoardError(read.error)
    if read.note:
        raise BoardError("This block has more than one game, so the line can't go into it.")
    handle = io.StringIO(_HEADERS_ON_ONE_LINE.sub('"]\n[', text))
    game = chess.pgn.read_game(handle, Visitor=_Builder)
    assert game is not None
    walk = _Walk()
    walk.line(game, game.board(), None)
    if after is not None and not 0 <= after < len(walk.nodes):
        raise BoardError("That move isn't in this game any more.")
    node: chess.pgn.GameNode = game if after is None else walk.nodes[after]
    board = node.board()
    added = False
    for uci in ucis:
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            raise BoardError(f"Couldn't read the move '{_short(uci, 12)}'.") from None
        if move not in board.legal_moves:
            raise BoardError(f"{uci} isn't legal there.")
        child = next((v for v in node.variations if v.move == move), None)
        if child is None:
            child = node.add_variation(move)
            added = True
        node = child
        board.push(move)
    if not added:
        return None
    lines = text.replace("\r\n", "\n").split("\n")
    head = 0
    while head < len(lines) and (not lines[head].strip() or _HEADER_LINE.match(lines[head])):
        head += 1
    headers = "\n".join(line for line in lines[:head] if line.strip())
    exporter = chess.pgn.StringExporter(headers=False, variations=True, comments=True, columns=80)
    movetext = _NAG_OUT.sub(lambda m: NAGS[int(m.group(1))], game.accept(exporter))
    movetext = _INSIDE.sub(lambda m: m.group(1) or m.group(2), movetext)
    movetext = _SPLIT_NUMBER.sub(lambda m: f"\n{m.group(1)} ", movetext)
    return f"{headers}\n{movetext}" if headers else movetext
