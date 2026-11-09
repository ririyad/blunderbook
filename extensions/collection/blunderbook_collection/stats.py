"""A collection's stats (ROADMAP 12.2), worked out from the evals 12.1 stores. Pure.

Every move is judged as your own are (CLAUDE.md §7.6, ``core.detect``): its swing in the
mover's winning chances, ``??`` / ``?`` / ``?!`` by your thresholds, and never a mark for
the engine's own move. On top of that:

- **Accuracy** of a move is Lichess's formula on the mover's winning chances, in percent:
  ``103.1668 * exp(-0.04354 * (before - after)) - 3.1669``, kept within 0..100. A side's
  accuracy in a game is the average of the mean and the harmonic mean of its moves' (each
  counted as at least 1 for the harmonic mean), so one bad move costs more than a plain
  average shows. A set of games' accuracy is the mean of its games'.
- **Centipawn loss** of a move is how far the mover's eval dropped, in centipawns, with
  evals capped at +-1000 (mates count as 1000) so a lost won position doesn't swamp the
  average. ACPL is the total over the moves counted.
- **Phases**, from the position before the move: the endgame once there are six pieces or
  fewer besides kings and pawns, both sides together; otherwise the opening up to move 10,
  then the middlegame.

:func:`report` filters the games and the moves (by player, colour, result, opening and
phase) and adds everything up; :func:`players` lists who played.
"""

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Final, Literal

import chess

from blunderbook.core import detect, identity
from blunderbook.core.models import Color, Judgment, Thresholds
from blunderbook_collection.games import Position

Phase = Literal["opening", "middlegame", "endgame"]
Result = Literal["won", "lost", "drawn", "white", "black"]

PHASES: Final[tuple[Phase, ...]] = ("opening", "middlegame", "endgame")
OPENING_MOVES: Final = 10  # moves 1..10 are the opening
ENDGAME_PIECES: Final = 6  # knights, bishops, rooks and queens of both sides
CP_CAP: Final = 1000
_ECO: Final = frozenset("ABCDE")


# ---------------------------------------------------------------- one game's moves


@dataclass(frozen=True, slots=True)
class Game:
    """One stored game, as the stats need it."""

    id: int
    white: str | None
    black: str | None
    result: str | None
    eco: str | None
    opening: str | None
    date: str | None
    event: str | None
    positions: tuple[Position, ...]


@dataclass(frozen=True, slots=True)
class Move:
    """One move of a game, judged."""

    ply: int  # 0-based: the move from position ply to ply + 1
    move_no: int
    color: Color
    san: str
    swing: float
    judgment: Judgment | None
    accuracy: float  # 0..100
    cp_loss: int
    phase: Phase


def moves(game: Game, thresholds: Thresholds) -> tuple[Move, ...]:
    """Every move of ``game``, judged."""
    found: list[Move] = []
    for before, after in zip(game.positions, game.positions[1:], strict=False):
        if after.move_uci is None or after.move_san is None:
            continue
        board = chess.Board(before.fen)
        mover: Color = "white" if board.turn == chess.WHITE else "black"
        other: Color = "black" if mover == "white" else "white"
        swing = detect.swing(before.score, after.score, mover)
        flagged = before.best_uci is not None and after.move_uci != before.best_uci
        sign = 1 if mover == "white" else -1
        cp_before = sign * detect.maths_cp(before.score, mover)
        cp_after = sign * detect.maths_cp(after.score, other)
        found.append(
            Move(
                ply=before.ply,
                move_no=board.fullmove_number,
                color=mover,
                san=after.move_san,
                swing=swing,
                judgment=detect.judgment(swing, thresholds) if flagged else None,
                accuracy=move_accuracy(cp_before, cp_after),
                cp_loss=max(0, _cap(cp_before) - _cap(cp_after)),
                phase=phase(board),
            )
        )
    return tuple(found)


def win_percent(cp: float) -> float:
    """The mover's winning chances in percent: 50 is level."""
    return 50 * (1 + detect.winning_chances(cp))


def move_accuracy(cp_before: float, cp_after: float) -> float:
    """Lichess's accuracy of a move, from the mover's evals before and after it."""
    drop = win_percent(cp_before) - win_percent(cp_after)
    value = 103.1668 * math.exp(-0.04354 * drop) - 3.1669
    return min(100.0, max(0.0, value))


def game_accuracy(accuracies: Sequence[float]) -> float | None:
    """A side's accuracy in a game: the average of the mean and the harmonic mean."""
    if not accuracies:
        return None
    mean = sum(accuracies) / len(accuracies)
    harmonic = len(accuracies) / sum(1 / max(a, 1.0) for a in accuracies)
    return (mean + harmonic) / 2


def phase(board: chess.Board) -> Phase:
    pieces = sum(
        len(board.pieces(kind, color))
        for kind in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN)
        for color in chess.COLORS
    )
    if pieces <= ENDGAME_PIECES:
        return "endgame"
    return "opening" if board.fullmove_number <= OPENING_MOVES else "middlegame"


def _cap(cp: int) -> int:
    return max(-CP_CAP, min(CP_CAP, cp))


# ---------------------------------------------------------------- filters


@dataclass(frozen=True, slots=True)
class Filter:
    """Which games and moves count. With ``player``, ``color`` is the colour they played,
    ``won`` / ``lost`` are from their side, and only their moves are counted (their
    opponents' are shown next to them). Without, ``color`` counts one side's moves only,
    and ``white`` / ``black`` is the side that won."""

    player: str | None = None
    color: Color | None = None
    result: Result | None = None
    opening: str | None = None  # an ECO code or its start ("C4"), or part of the name
    phase: Phase | None = None

    def problem(self) -> str | None:
        if self.result in ("won", "lost") and self.player is None:
            return f"--result {self.result} needs --player: whose result is it?"
        return None


def _side_of(game: Game, player: str) -> Color | None:
    """The colour ``player`` had in ``game``; None when they didn't play it. (A game against
    themselves counts as White's.)"""
    name = identity.normalize_name(player)
    if game.white and identity.normalize_name(game.white) == name:
        return "white"
    if game.black and identity.normalize_name(game.black) == name:
        return "black"
    return None


def _opening_matches(game: Game, wanted: str) -> bool:
    text = wanted.strip()
    if text[:1].upper() in _ECO and text[1:].isdigit() and len(text) <= 3:
        return (game.eco or "").upper().startswith(text.upper())
    return text.casefold() in (game.opening or "").casefold()


def _outcome(result: str | None, side: Color) -> Literal["won", "drawn", "lost"] | None:
    if result == "1/2-1/2":
        return "drawn"
    if result not in ("1-0", "0-1"):
        return None
    return "won" if (result == "1-0") == (side == "white") else "lost"


def _keep(game: Game, f: Filter) -> Color | Literal[False] | None:
    """False when the game is filtered out; else the player's colour (None without one)."""
    side = _side_of(game, f.player) if f.player else None
    if f.player and side is None:
        return False
    if f.player and f.color and side != f.color:
        return False
    if f.opening and not _opening_matches(game, f.opening):
        return False
    wanted = {"white": "1-0", "black": "0-1", "drawn": "1/2-1/2"}
    if f.result in wanted:
        if game.result != wanted[f.result]:
            return False
    elif f.result is not None:  # won / lost, from the player's side
        assert side is not None
        if _outcome(game.result, side) != f.result:
            return False
    return side


# ---------------------------------------------------------------- the report


@dataclass(slots=True)
class Tally:
    """Moves added up: for a side, a phase or a game. ``games`` counts the games with
    moves counted."""

    games: int = 0
    moves: int = 0
    cp_loss: int = 0
    blunders: int = 0
    mistakes: int = 0
    inaccuracies: int = 0
    game_accuracies: list[float] = field(default_factory=list)

    @property
    def acpl(self) -> float | None:
        return self.cp_loss / self.moves if self.moves else None

    @property
    def accuracy(self) -> float | None:
        if not self.game_accuracies:
            return None
        return sum(self.game_accuracies) / len(self.game_accuracies)

    def add(self, counted: Sequence[Move]) -> None:
        self.moves += len(counted)
        self.cp_loss += sum(m.cp_loss for m in counted)
        self.blunders += sum(m.judgment == "blunder" for m in counted)
        self.mistakes += sum(m.judgment == "mistake" for m in counted)
        self.inaccuracies += sum(m.judgment == "inaccuracy" for m in counted)

    def add_game(self, counted: Sequence[Move]) -> None:
        """One game's moves. A game with none counted (another phase) isn't counted."""
        if not counted:
            return
        self.games += 1
        self.add(counted)
        accuracy = game_accuracy([m.accuracy for m in counted])
        if accuracy is not None:
            self.game_accuracies.append(accuracy)


@dataclass(frozen=True, slots=True)
class Score:
    """Results: from the player's side with one, else White's. ``unfinished`` is ``*``
    or no result."""

    won: int = 0
    drawn: int = 0
    lost: int = 0
    unfinished: int = 0


@dataclass(frozen=True, slots=True)
class GameLine:
    """One game in the report, with both sides' numbers."""

    game: Game
    player_color: Color | None  # the player's colour, with a player
    white: Tally
    black: Tally


@dataclass(frozen=True, slots=True)
class Opening:
    eco: str | None
    name: str | None
    color: Color | None  # the player's colour, with a player
    score: Score
    sides: tuple[Tally, Tally]  # as Report.sides


@dataclass(frozen=True, slots=True)
class Report:
    games: int
    score: Score
    labels: tuple[str, str]  # ("White", "Black"), or (the player, "Opponents")
    sides: tuple[Tally, Tally]  # the moves of each, after the colour and phase filters
    phases: dict[Phase, Tally]  # the moves counted: both sides, or the player's / one side's
    openings: tuple[Opening, ...]  # most games first
    lines: tuple[GameLine, ...]  # in the order given


def report(games: Iterable[Game], thresholds: Thresholds, f: Filter | None = None) -> Report:
    """The stats of ``games`` that pass ``f`` (all of them without one)."""
    f = f or Filter()
    first, second = Tally(), Tally()
    phases: dict[Phase, Tally] = {p: Tally() for p in PHASES}
    openings: dict[_OpeningKey, list[tuple[list[Move], Color, str | None]]] = {}
    lines: list[GameLine] = []
    count = 0
    for game in games:
        kept = _keep(game, f)
        if kept is False:
            continue
        count += 1
        judged = [m for m in moves(game, thresholds) if f.phase is None or m.phase == f.phase]
        by: dict[Color, list[Move]] = {
            c: [m for m in judged if m.color == c] for c in ("white", "black")
        }
        # Whose moves are "first": the player's, else White's.
        mine: Color = kept if kept is not None else "white"
        theirs: Color = "black" if mine == "white" else "white"
        if f.player is None and f.color is not None:
            mine, theirs = f.color, ("black" if f.color == "white" else "white")
        first.add_game(by[mine])
        second.add_game(by[theirs])
        counted = by[mine] if (f.player or f.color) else judged
        for p in PHASES:
            phases[p].add_game([m for m in counted if m.phase == p])
        white, black = Tally(), Tally()
        white.add_game(by["white"])
        black.add_game(by["black"])
        lines.append(GameLine(game, kept, white, black))
        openings.setdefault((game.eco, game.opening, kept), []).append((judged, mine, game.result))
    if f.player:
        shown = f.player.strip()
        for line in lines:
            assert line.player_color is not None
            name = line.game.white if line.player_color == "white" else line.game.black
            shown = name or shown
            break
        labels = (shown, "Opponents")
    elif f.color == "black":
        labels = ("Black", "White")
    else:
        labels = ("White", "Black")
    return Report(
        games=count,
        score=_score((line.game.result, line.player_color or "white") for line in lines),
        labels=labels,
        sides=(first, second),
        phases=phases,
        openings=_openings(openings),
        lines=tuple(lines),
    )


_OpeningKey = tuple[str | None, str | None, Color | None]  # ECO, name, the player's colour


def _score(pairs: Iterable[tuple[str | None, Color]]) -> Score:
    """Results from ``side``'s point of view, for each (result, side)."""
    won = drawn = lost = unfinished = 0
    for result, side in pairs:
        outcome = _outcome(result, side)
        if outcome == "won":
            won += 1
        elif outcome == "drawn":
            drawn += 1
        elif outcome == "lost":
            lost += 1
        else:
            unfinished += 1
    return Score(won, drawn, lost, unfinished)


def _openings(
    groups: dict[_OpeningKey, list[tuple[list[Move], Color, str | None]]],
) -> tuple[Opening, ...]:
    found: list[Opening] = []
    for (eco, name, color), games in groups.items():
        first, second = Tally(), Tally()
        for judged, mine, _ in games:
            first.add_game([m for m in judged if m.color == mine])
            second.add_game([m for m in judged if m.color != mine])
        score = _score((result, color or "white") for _, _, result in games)
        found.append(Opening(eco, name, color, score, (first, second)))
    found.sort(key=lambda o: (-o.sides[0].games, o.color or "", o.eco or "~", o.name or ""))
    return tuple(found)


# ---------------------------------------------------------------- players


@dataclass(frozen=True, slots=True)
class Player:
    name: str  # as first written
    games: int
    as_white: int
    as_black: int
    score: Score
    accuracy: float | None


def players(games: Iterable[Game], thresholds: Thresholds) -> tuple[Player, ...]:
    """Everyone who played, by name (ignoring case): most games first, then by name."""
    seen: dict[str, tuple[str, list[tuple[Game, Color]]]] = {}
    for game in games:
        for color, name in (("white", game.white), ("black", game.black)):
            if not name:
                continue
            key = identity.normalize_name(name)
            entry = seen.setdefault(key, (name, []))
            if not any(g.id == game.id for g, _ in entry[1]):
                side: Color = "white" if color == "white" else "black"
                entry[1].append((game, side))
    found: list[Player] = []
    for name, pairs in seen.values():
        tally = Tally()
        for game, side in pairs:
            tally.add_game([m for m in moves(game, thresholds) if m.color == side])
        found.append(
            Player(
                name=name,
                games=len(pairs),
                as_white=sum(side == "white" for _, side in pairs),
                as_black=sum(side == "black" for _, side in pairs),
                score=_score((game.result, side) for game, side in pairs),
                accuracy=tally.accuracy,
            )
        )
    found.sort(key=lambda p: (-p.games, p.name.casefold()))
    return tuple(found)
