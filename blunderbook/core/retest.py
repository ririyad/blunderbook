"""Re-test scheduling (CLAUDE.md §7.8): when an entry comes back, whether a move solves it,
the order of the queue, and reading the move you make on the board.

Pure: the API reads entries, calls these, and writes the result.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Final

import chess

from blunderbook.core.models import Status

INTERVALS: Final[tuple[int, ...]] = (1, 3, 7, 14, 30, 60)  # days, by streak
UCI_SQUARES: Final = 4  # "e7e8q"[:4]: the from- and to-square, without the promotion


@dataclass(frozen=True, slots=True)
class Schedule:
    """An entry's re-test state after an attempt."""

    status: Status
    streak: int
    due_on: date


def next_interval(streak: int) -> int:
    """Days until the next re-test after a solve that brought the streak to ``streak``."""
    if streak < 1:
        raise ValueError(f"A solved entry has a streak of 1 or more, not {streak}.")
    return INTERVALS[min(streak - 1, len(INTERVALS) - 1)]


def after_attempt(streak: int, solved: bool, today: date) -> Schedule:
    """The schedule after an attempt. ``streak`` is the entry's streak before it.

    Solved: the streak goes up and the entry comes back after the next interval.
    Missed or gave up: the streak goes back to 0 and the entry comes back tomorrow.
    Using the hint doesn't change this in v1.
    """
    if streak < 0:
        raise ValueError(f"A streak is 0 or more, not {streak}.")
    if solved:
        streak += 1
        return Schedule("solved", streak, today + timedelta(days=next_interval(streak)))
    return Schedule("missed", 0, today + timedelta(days=1))


def is_solved(move_uci: str | None, accept_uci: Iterable[str]) -> bool:
    """Whether a re-test move solves the entry: its first 4 UCI characters (from- and
    to-square) match an accepted move's. ``None`` means you gave up.

    A promotion is matched by its squares, so ``e7e8`` (a queen by default) and ``e7e8q``
    are the same answer.
    """
    if move_uci is None:
        return False
    squares = _squares(move_uci)
    if len(squares) != UCI_SQUARES:
        return False
    return any(_squares(accepted) == squares for accepted in accept_uci)


def _squares(uci: str) -> str:
    return uci.strip().lower()[:UCI_SQUARES]


def queue_key(
    due_on: date, played_on: date | None, game_id: int, ply: int
) -> tuple[int, int, int, int, int]:
    """Sort key for the re-test queue: oldest due date first, then the most recent game
    (an unknown date after the known ones, then the newest game first, as in the Log),
    then a game's entries in move order."""
    by_date = (0, -played_on.toordinal()) if played_on is not None else (1, 0)
    return (due_on.toordinal(), *by_date, -game_id, ply)


# ---------------------------------------------------------------- the board


def legal_uci(fen: str) -> list[str]:
    """Every legal move in the position, as UCI, for tap-to-move. A promotion is listed once
    per piece (``e7e8q``, ``e7e8r``, ...)."""
    return [move.uci() for move in chess.Board(fen).legal_moves]


def read_move(fen: str, uci: str) -> chess.Move | None:
    """The legal move ``uci`` names in the position, or None. A pawn move to the last rank
    without a piece (``e7e8``) promotes to a queen."""
    text = uci.strip().lower()
    try:
        move = chess.Move.from_uci(text)
    except chess.InvalidMoveError:
        return None
    board = chess.Board(fen)
    if move.promotion is None and not board.is_legal(move):
        move = chess.Move(move.from_square, move.to_square, promotion=chess.QUEEN)
    return move if board.is_legal(move) else None


def from_square(uci: str) -> str:
    """The hint: the square the move starts from (``e2`` for ``e2e3``)."""
    return uci[:2]
