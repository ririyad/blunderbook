"""The Library's content: one TOML file per opening, trap or tactic, checked with python-chess
before anything uses it (ROADMAP 11.1).

Files live in ``content/openings``, ``content/traps`` and ``content/tactics``; a file's name is
the entry's id (``traps/legal-trap.toml`` is ``legal-trap``). ``content/README.md`` describes
every field. Moves are SAN, written the way python-chess writes them (``Bxf7+``, ``Nd5#``),
with optional move numbers (``5. Nxe5``, ``5... Bxd1``), which are checked too.

Nothing here raises for bad content: :func:`load` returns the entries that are fine and one
plain line per problem, naming the file and the place in it.
"""

import re
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, cast

import chess

type Kind = Literal["opening", "trap", "tactic"]
type Side = Literal["white", "black"]

FOLDER: Final = Path(__file__).parent / "content"
KINDS: Final[dict[Kind, str]] = {"opening": "openings", "trap": "traps", "tactic": "tactics"}
SIDES: Final[tuple[Side, ...]] = ("white", "black")
ID: Final = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
ECO: Final = re.compile(r"[A-E][0-9]{2}")
NUMBER: Final = re.compile(r"(\d+)\.(\.\.)?(.*)")

KEYS: Final = frozenset(
    {"kind", "name", "side", "opening", "eco", "idea", "fen", "moves", "next", "practise"}
)
NEXT_KEYS: Final = frozenset({"move", "line", "says", "loses"})
PRACTISE_KEYS: Final = frozenset({"after", "answers", "prompt"})

PROMPTS: Final[dict[Kind, str]] = {
    "opening": "Play the next move of the opening.",
    "trap": "Find the move that doesn't fall into the trap.",
    "tactic": "Find the move that wins.",
}


@dataclass(frozen=True, slots=True)
class Move:
    san: str  # "Nxe5", as python-chess writes it
    uci: str  # "f3e5"
    label: str  # "5. Nxe5" or "5... Bxd1"


@dataclass(frozen=True, slots=True)
class Next:
    """A reply at the end of the line, and what follows it."""

    move: Move
    line: tuple[Move, ...]  # after the move
    says: str
    loses: bool  # the move falls into the trap, or throws the position away


@dataclass(frozen=True, slots=True)
class Practise:
    """A position to find the move in, from the entry's side."""

    ply: int  # how many moves of the line are played: 0 is the start position
    fen: str
    answers: tuple[Move, ...]  # every move counted as right
    prompt: str


@dataclass(frozen=True, slots=True)
class Entry:
    id: str  # the file's name: "legal-trap"
    path: str  # "traps/legal-trap.toml", under the content folder
    kind: Kind
    name: str
    side: Side  # the side you practise as; the board faces it
    opening: str | None
    eco: str | None
    idea: str
    start_fen: str
    moves: tuple[Move, ...]
    end_fen: str
    next: tuple[Next, ...]
    practise: tuple[Practise, ...]


@dataclass(frozen=True, slots=True)
class Content:
    entries: tuple[Entry, ...]
    problems: tuple[str, ...]


class Problem(Exception):
    """One thing wrong with an entry: a plain message, without the file's name."""


def load(folder: Path = FOLDER) -> Content:
    """Every entry under ``folder``, in kind order (openings, traps, tactics) then by file
    name, and every problem found. A file with a problem is left out."""
    entries: list[Entry] = []
    problems: list[str] = []
    if not folder.is_dir():
        return Content((), (f"{folder} isn't a folder.",))
    kinds = {plural: kind for kind, plural in KINDS.items()}
    for path in sorted(folder.iterdir()):
        if path.is_dir() and path.name not in kinds:
            problems.append(f"{path.name}/: not a kind; use {', '.join(KINDS.values())}.")
        elif path.suffix == ".toml":
            problems.append(f"{path.name}: put it in {', '.join(KINDS.values())}.")
    for plural in KINDS.values():
        for path in sorted((folder / plural).glob("*.toml")):
            rel = path.relative_to(folder).as_posix()
            try:
                entries.append(read(path, rel))
            except Problem as exc:
                problems.append(f"{rel}: {exc}")
    seen: dict[str, str] = {}
    for entry in entries:
        other = seen.setdefault(entry.name.casefold(), entry.path)
        if other != entry.path:
            problems.append(f"{entry.path}: {other} has the same name, {entry.name!r}.")
    return Content(tuple(entries), tuple(problems))


def read(path: Path, rel: str) -> Entry:
    """One entry file. ``rel`` is its path under the content folder (``traps/x.toml``), which
    gives its id and must match its kind. Raises Problem."""
    stem = Path(rel).stem
    if not ID.fullmatch(stem):
        raise Problem("name the file in lowercase letters, digits and dashes (legal-trap.toml).")
    try:
        data = tomllib.loads(path.read_text("utf-8"))
    except UnicodeDecodeError:
        raise Problem("isn't UTF-8 text.") from None
    except tomllib.TOMLDecodeError as exc:
        raise Problem(f"isn't valid TOML: {exc}") from None
    return entry(data, stem, rel)


def entry(data: Mapping[str, object], id: str, rel: str) -> Entry:
    """An entry from its parsed TOML. Raises Problem."""
    _keys(data, KEYS, "")
    kind = _choice(data, "kind", KINDS)
    folder = rel.split("/")[0]
    if folder != KINDS[kind]:
        raise Problem(f"kind is {kind!r}, so the file goes in {KINDS[kind]}/, not {folder}/.")
    name = _text(data, "name")
    side = _choice(data, "side", SIDES)
    opening = _maybe(data, "opening")
    eco = _maybe(data, "eco")
    if eco is not None and not ECO.fullmatch(eco):
        raise Problem(f"eco {eco!r} isn't an ECO code like C41.")
    idea = " ".join(_text(data, "idea").split())

    fen = _maybe(data, "fen")
    if fen is None:
        if "moves" not in data:
            raise Problem("give the moves, or a fen to start from.")
        board = chess.Board()
    else:
        try:
            board = chess.Board(fen)
        except ValueError as exc:
            raise Problem(f"fen isn't a position: {exc}") from None
        if not board.is_valid():
            raise Problem("fen isn't a legal position.")
    start_fen = board.fen()

    moves = _line(board, _maybe(data, "moves") or "", "moves")
    positions = _positions(start_fen, moves)
    end = chess.Board(positions[-1])

    nexts = tuple(_next(end, item, f"next {i}") for i, item in enumerate(_tables(data, "next"), 1))
    tables = _tables(data, "practise")
    if not tables:
        raise Problem("add at least one [[practise]] position.")
    losing = {n.move.uci for n in nexts if n.loses}
    practise = tuple(
        _practise(item, f"practise {i}", kind, side, moves, positions, losing)
        for i, item in enumerate(tables, 1)
    )
    return Entry(
        id=id,
        path=rel,
        kind=kind,
        name=name,
        side=side,
        opening=opening,
        eco=eco,
        idea=idea,
        start_fen=start_fen,
        moves=moves,
        end_fen=end.fen(),
        next=nexts,
        practise=practise,
    )


# ---------------------------------------------------------------- the parts


def _next(end: chess.Board, item: Mapping[str, object], where: str) -> Next:
    _keys(item, NEXT_KEYS, where + ": ")
    board = end.copy()
    played = _line(board, _text(item, "move", where=where), where)
    if len(played) != 1:
        raise Problem(f"{where}: move is one move; the rest goes in line.")
    line = _line(board, _maybe(item, "line", where=where) or "", where)
    loses = item.get("loses", False)
    if not isinstance(loses, bool):
        raise Problem(f"{where}: loses is true or false.")
    return Next(played[0], line, " ".join(_text(item, "says", where=where).split()), loses)


def _practise(
    item: Mapping[str, object],
    where: str,
    kind: Kind,
    side: Side,
    moves: tuple[Move, ...],
    positions: list[str],
    losing: set[str],
) -> Practise:
    _keys(item, PRACTISE_KEYS, where + ": ")
    after = _maybe(item, "after", where=where)
    if after is None:
        ply = len(moves)
    else:
        wanted = " ".join(after.split())
        plies = [i + 1 for i, m in enumerate(moves) if m.label == wanted]
        if not plies:
            labels = ", ".join(m.label for m in moves[:3])
            raise Problem(f"{where}: after {after!r} isn't a move of the line ({labels}, ...).")
        ply = plies[0]
    board = chess.Board(positions[ply])
    mover: Side = "white" if board.turn == chess.WHITE else "black"
    if mover != side:
        raise Problem(
            f"{where}: it's {mover.capitalize()} to move there, but the entry is "
            f"practised as {side.capitalize()}."
        )
    raw = item.get("answers")
    if not isinstance(raw, list) or not raw or not all(isinstance(a, str) for a in raw):
        raise Problem(f'{where}: answers is a list of moves, like ["dxe5"].')
    answers: list[Move] = []
    for text in cast(list[str], raw):
        (move,) = _line(board.copy(), text, where, alone=True)
        if move.uci in {a.uci for a in answers}:
            raise Problem(f"{where}: {move.san} is in answers twice.")
        if move.uci in losing:
            raise Problem(
                f"{where}: {move.san} is marked as losing in next, so it can't be an answer."
            )
        answers.append(move)
    if ply < len(moves) and moves[ply].uci not in {a.uci for a in answers}:
        raise Problem(
            f"{where}: the line goes on with {moves[ply].label}; add {moves[ply].san} to answers."
        )
    prompt = _maybe(item, "prompt", where=where) or PROMPTS[kind]
    return Practise(ply, board.fen(), tuple(answers), " ".join(prompt.split()))


def _line(board: chess.Board, text: str, where: str, *, alone: bool = False) -> tuple[Move, ...]:
    """Play ``text`` on ``board`` (changing it). Move numbers are optional, and checked when
    given. ``alone``: one move, no number."""
    played: list[Move] = []
    numbered: int | None = None  # the number just given, for the move after it
    for token in text.split():
        number = NUMBER.fullmatch(token)
        if number:
            if alone:
                raise Problem(f"{where}: write {token!r} without its move number.")
            n, dots, rest = int(number[1]), bool(number[2]), number[3]
            black = board.turn == chess.BLACK
            if n != board.fullmove_number or dots != black:
                raise Problem(
                    f"{where}: {token!r} should be {_number(board)}"
                    + (f" (after {played[-1].label})." if played else ".")
                )
            numbered = n
            if not rest:
                continue
            token = rest
        played.append(_move(board, token, where, played))
        numbered = None
    if numbered is not None:
        raise Problem(f"{where}: a move number with no move after it.")
    if alone and len(played) != 1:
        raise Problem(f"{where}: {text!r} should be one move.")
    return tuple(played)


def _move(board: chess.Board, token: str, where: str, played: list[Move]) -> Move:
    label = f"{_number(board)} {token}"
    after = f"after {played[-1].label}" if played else "here"
    try:
        move = board.parse_san(token)
    except chess.IllegalMoveError:
        raise Problem(f"{where}: {label} isn't legal {after}.") from None
    except chess.AmbiguousMoveError:
        raise Problem(
            f"{where}: {label} could be more than one piece {after}; say which."
        ) from None
    except ValueError:
        raise Problem(f"{where}: {token!r} isn't a move.") from None
    san = board.san(move)
    if san != token:
        raise Problem(f"{where}: write {label} as {san}.")
    board.push(move)
    return Move(san, move.uci(), label)


def _number(board: chess.Board) -> str:
    return (
        f"{board.fullmove_number}." if board.turn == chess.WHITE else f"{board.fullmove_number}..."
    )


def _positions(start_fen: str, moves: tuple[Move, ...]) -> list[str]:
    board = chess.Board(start_fen)
    fens = [board.fen()]
    for move in moves:
        board.push_uci(move.uci)
        fens.append(board.fen())
    return fens


# ---------------------------------------------------------------- fields


def _keys(data: Mapping[str, object], allowed: frozenset[str], where: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise Problem(
            f"{where}unknown field {unknown[0]!r} (there's {', '.join(sorted(allowed))})."
        )


def _text(data: Mapping[str, object], key: str, *, where: str = "") -> str:
    value = _maybe(data, key, where=where)
    if value is None:
        raise Problem(f"{where}: {key} is missing." if where else f"{key} is missing.")
    return value


def _maybe(data: Mapping[str, object], key: str, *, where: str = "") -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise Problem(
            f"{where}: {key} should be some text." if where else f"{key} should be some text."
        )
    return value.strip()


def _choice[T: str](data: Mapping[str, object], key: str, options: Iterable[T]) -> T:
    value = data.get(key)
    names = list(options)
    for name in names:
        if value == name:
            return name
    shown = " or ".join(repr(n) for n in names)
    raise Problem(f"{key} is {shown}" + ("." if value is None else f", not {value!r}."))


def _tables(data: Mapping[str, object], key: str) -> list[Mapping[str, object]]:
    value = data.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, dict) for v in value):
        raise Problem(f"{key} should be [[{key}]] tables.")
    return cast(list[Mapping[str, object]], value)
