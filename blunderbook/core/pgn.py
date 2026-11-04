"""Read PGN text into games (CLAUDE.md §7.1). Pure: bytes or text in, dataclasses out.

- Multi-game text is split with python-chess (``chess.pgn.read_game``), never with regexes.
- Only the mainline is kept. Variations are skipped unparsed, so a bad move inside a
  side line can't reject an otherwise good game.
- A game that can't be read becomes a ``PgnProblem`` with a plain reason. The rest of the
  file is still read.
- Each game keeps its own text verbatim (only line endings are normalised).
"""

import io
import re
from dataclasses import dataclass
from datetime import date
from typing import Final, Literal

import chess
import chess.pgn

from blunderbook.core.models import Color, ParsedGame, ParsedPgn, PgnProblem, Ply

Encoding = Literal["utf-8", "cp1252"]

# python-chess error messages look like: illegal san: 'Ke3' in <fen>
_SAN_IN_ERROR: Final = re.compile(r"san: '([^']*)'")
_DATE: Final = re.compile(r"(\d{4})[.\-/](\d{2})[.\-/](\d{2})")
_WHOLE: Final = re.compile(r"\d+", re.ASCII)

# For spotting movetext python-chess skips without a word (its tokenizer ignores anything
# that doesn't look like SAN). Mirrors chess.pgn.MOVETEXT_REGEX, plus check/mate marks.
_COMMENT: Final = re.compile(r"\{[^}]*\}")  # PGN comments don't nest
_LINE_COMMENT: Final = re.compile(r";[^\n]*")
_MOVE_NUMBER: Final = re.compile(r"^\d+\.+")
_MOVE_TOKEN: Final = re.compile(
    r"(?:[NBKRQ]?[a-h]?[1-8]?[\-x]?[a-h][1-8](?:=?[nbrqkNBRQK])?"
    r"|O-O(?:-O)?|0-0(?:-0)?|--|Z0|0000|@@@@|[PNBRQK]?@[a-h][1-8])"
    r"[+#]?(?:[!?]{1,2})?"
)
_OTHER_TOKEN: Final = re.compile(r"\$\d+|[!?]{1,2}|\*|1-0|0-1|1/2-1/2|½-½|e\.p\.|ep")
_ALNUM: Final = re.compile(r"[A-Za-z0-9]")


@dataclass(frozen=True, slots=True)
class Decoded:
    text: str
    encoding: Encoding  # "cp1252" means UTF-8 failed; the import report says so


def decode(data: bytes) -> Decoded:
    """UTF-8 (BOM optional), else Windows-1252 with undecodable bytes replaced. Never fails."""
    try:
        return Decoded(data.decode("utf-8-sig"), "utf-8")
    except UnicodeDecodeError:
        return Decoded(data.decode("cp1252", errors="replace"), "cp1252")


def normalize(text: str) -> str:
    """Drop a leading BOM and turn CRLF / CR line endings into LF."""
    return text.removeprefix("﻿").replace("\r\n", "\n").replace("\r", "\n")


def parse(text: str) -> ParsedPgn:
    """Read every game in ``text``. Empty text gives no games and no problems."""
    text = normalize(text)
    handle = io.StringIO(text)
    games: list[ParsedGame] = []
    problems: list[PgnProblem] = []
    number = 0
    while True:
        start = handle.tell()
        game = chess.pgn.read_game(handle, Visitor=_MainlineBuilder)
        if game is None:
            break
        number += 1
        own_text = text[start : handle.tell()].strip()
        headers = frozendict(game.headers)
        try:
            games.append(_build(number, game, headers, own_text))
        except _Unreadable as exc:
            problems.append(PgnProblem(number, str(exc), headers, own_text))
    return ParsedPgn(tuple(games), tuple(problems))


def parse_date(value: str | None) -> date | None:
    """``"2026.11.02"`` -> ``date(2026, 11, 2)``. Partial or invalid dates -> None."""
    if value is None:
        return None
    match = _DATE.fullmatch(value.strip())
    if match is None:
        return None
    try:
        return date(int(match[1]), int(match[2]), int(match[3]))
    except ValueError:
        return None


def parse_int(value: str | None) -> int | None:
    """A whole number such as a rating: ``"1402"`` -> 1402. Anything else -> None."""
    if value is None or _WHOLE.fullmatch(value.strip()) is None:
        return None
    return int(value)


# ---------------------------------------------------------------- internals


class _Unreadable(Exception):
    pass


class _MainlineBuilder(chess.pgn.GameBuilder[chess.pgn.Game]):
    """A GameBuilder that skips variations and collects errors without logging them."""

    def begin_variation(self) -> chess.pgn.SkipType:  # type: ignore[override]
        return chess.pgn.SKIP

    def end_variation(self) -> None:
        # begin_variation pushed nothing, so there is nothing to pop.
        pass

    def handle_error(self, error: Exception) -> None:
        self.game.errors.append(error)


def _build(
    number: int, game: chess.pgn.Game, headers: frozendict[str, str], text: str
) -> ParsedGame:
    moves_seen, skipped = _scan_movetext(text)
    if game.errors:
        reason = _describe(game.errors[0], game)
        parsed = sum(1 for _ in game.mainline())
        earlier = [token for moves_before, token in skipped if moves_before <= parsed]
        if earlier:
            reason += f" (after unreadable text '{earlier[0]}')"
        raise _Unreadable(reason)
    board = game.board()
    if type(board) is not chess.Board or board.chess960 or game.headers.is_chess960():
        variant = headers.get("Variant", "")
        raise _Unreadable(f"{variant or 'This variant'} isn't supported, only standard chess.")
    start_fen = board.fen()
    plies: list[Ply] = []
    for index, node in enumerate(game.mainline()):
        move = node.move
        color: Color = "white" if board.turn == chess.WHITE else "black"
        move_no = board.fullmove_number
        if not move:
            raise _Unreadable(f"Null move (--) at move {move_no}, which the engine can't analyse.")
        san = board.san(move)
        before = board.fen()
        board.push(move)
        plies.append(Ply(index, move_no, color, san, move.uci(), before, board.fen(), node.clock()))
    if not plies:
        raise _Unreadable("No moves in this game.")
    if skipped and moves_seen != len(plies):
        # python-chess read part of a token as a move (e.g. "♘f3" as the pawn move f3),
        # so the moves can't be trusted.
        moves_before, token = skipped[0]
        label = _position_label(plies, start_fen, moves_before)
        raise _Unreadable(f"Couldn't read '{token}' at {label}")
    warnings = tuple(
        f"Skipped unreadable text '{token}' at {_position_label(plies, start_fen, moves_before)}"
        for moves_before, token in skipped
    )
    return ParsedGame(number, headers, start_fen, tuple(plies), text, warnings)


def _scan_movetext(text: str) -> tuple[int, list[tuple[int, str]]]:
    """Count the mainline move tokens, and list the tokens python-chess ignores.

    Each ignored token comes with the number of moves before it. Only tokens with a
    letter or digit count (``Ke9``, ``O-0``, ``resigns``). Symbols such as ``±`` are
    commentary and are left alone. Variations are not checked.
    """
    lines = [line for line in text.split("\n") if not line.startswith("%")]
    while lines and (not lines[0].strip() or lines[0].lstrip().startswith("[")):
        lines.pop(0)  # the header block
    body = _LINE_COMMENT.sub(" ", _COMMENT.sub(" ", "\n".join(lines)))
    skipped: list[tuple[int, str]] = []
    depth = 0
    moves = 0
    for token in body.replace("(", " ( ").replace(")", " ) ").split():
        if token in ("(", ")"):
            depth = depth + 1 if token == "(" else max(0, depth - 1)
            continue
        if depth:
            continue
        bare = _MOVE_NUMBER.sub("", token, count=1)
        if not bare or _OTHER_TOKEN.fullmatch(bare):
            continue
        if _MOVE_TOKEN.fullmatch(bare):
            moves += 1
        elif _ALNUM.search(bare):
            skipped.append((moves, bare))
    return moves, skipped


def _position_label(plies: list[Ply], start_fen: str, moves_before: int) -> str:
    """``"2."`` or ``"2..."``: the move that was due after ``moves_before`` plies."""
    k = min(moves_before, len(plies))
    board = chess.Board(plies[k - 1].fen_after if k else start_fen)
    dots = "." if board.turn == chess.WHITE else "..."
    return f"{board.fullmove_number}{dots}"


def _describe(error: Exception, game: chess.pgn.Game) -> str:
    kind = None
    if isinstance(error, chess.IllegalMoveError):
        kind = "Illegal move"
    elif isinstance(error, chess.AmbiguousMoveError):
        kind = "Ambiguous move"
    elif isinstance(error, chess.InvalidMoveError):
        kind = "Unreadable move"
    if kind is not None:
        match = _SAN_IN_ERROR.search(str(error))
        san = match[1] if match else "?"
        board = game.end().board()
        dots = "." if board.turn == chess.WHITE else "..."
        return f"{kind} {board.fullmove_number}{dots} {san}"
    message = str(error)
    if message.startswith("unsupported variant"):
        variant = game.headers.get("Variant", "?")
        return f"{variant} isn't supported, only standard chess."
    if "FEN" in game.headers:
        return "The FEN header isn't a valid position."
    return f"This game couldn't be read ({message})."
