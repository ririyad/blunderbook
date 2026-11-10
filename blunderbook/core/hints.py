"""Suggested causes for a flagged move (CLAUDE.md §7.7).

These are suggestions only: the UI shows them as dashed "auto" chips and the user
confirms them. Rules that need clock data are skipped silently when it's missing.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import chess

from blunderbook.core.detect import mover_mates
from blunderbook.core.models import CAUSES, Color, Eval, Finding, ParsedGame, Ply, TimeControl

TIME_TROUBLE_SHARE: Final = 0.10  # clock left < 10% of base ...
TIME_TROUBLE_S: Final = 20  # ... or < 20 s
FAST_MOVE_S: Final = 3  # time spent <= 3 s ...
FAST_MOVE_CLOCK_SHARE: Final = 0.30  # ... while clock left > 30% of base
HUNG_PIECE_PLIES: Final = 6
HUNG_PIECE_DROP: Final = 3
MISSED_TACTIC_PLIES: Final = 6
MISSED_TACTIC_GAIN: Final = 3

PIECE_VALUES: Final = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
}


@dataclass(frozen=True, slots=True)
class Hints:
    """What the machine can say about a flagged move besides the engine lines."""

    causes: tuple[str, ...]  # suggested causes, in CAUSES order
    clock_left_s: float | None  # my clock after the move
    time_spent_s: float | None  # how long I took over it


def suggest(finding: Finding, game: ParsedGame, tc: TimeControl | None) -> Hints:
    """Suggested causes and clock facts for one flagged move of mine."""
    ply = finding.ply
    me = ply.color
    clock_left = ply.clock_s
    spent = time_spent(game, ply, tc)

    found: set[str] = set()
    if missed_my_tactic(finding, me):
        found.add("Missed my tactic")
    if time_trouble(clock_left, tc):
        found.add("Time trouble")
    if moved_too_fast(spent, clock_left, tc):
        found.add("Moved too fast")
    if missed_their_threat(finding.eval_after, me):
        found.add("Missed their threat")
    elif hung_a_piece(ply.fen_before, ply.fen_after, finding.refutation_uci, me):
        found.add("Hung a piece")

    causes = tuple(cause for cause in CAUSES if cause in found)
    return Hints(causes=causes, clock_left_s=clock_left, time_spent_s=spent)


# ---------------------------------------------------------------- clock rules


def time_spent(game: ParsedGame, ply: Ply, tc: TimeControl | None) -> float | None:
    """Seconds spent on ``ply``: my previous clock - my clock now + increment.

    For my first move it's base - clock + increment, but only in a game from the
    standard start: a game set up from a FEN starts mid-game, so that first move's time
    is unknown. None when a clock or the time control is missing, or when the clocks
    don't add up (a negative result, such as after the opponent gave you time).
    """
    if tc is None or ply.clock_s is None:
        return None
    if ply.index >= 2:
        previous = game.plies[ply.index - 2].clock_s  # plies alternate, so this one is mine
    elif game.start_fen == chess.STARTING_FEN:
        previous = float(tc.base_s)
    else:
        return None
    if previous is None:
        return None
    spent = previous - ply.clock_s + tc.inc_s
    if spent < 0:
        return None
    return round(spent, 3)  # clocks are tenths of a second; drop float noise


def time_trouble(clock_left: float | None, tc: TimeControl | None) -> bool:
    """Clock left under 10% of the base time, or under 20 s."""
    if clock_left is None or tc is None:
        return False
    return clock_left < TIME_TROUBLE_SHARE * tc.base_s or clock_left < TIME_TROUBLE_S


def moved_too_fast(spent: float | None, clock_left: float | None, tc: TimeControl | None) -> bool:
    """3 s or less on the move, with more than 30% of the base time still on the clock."""
    if spent is None or clock_left is None or tc is None:
        return False
    return spent <= FAST_MOVE_S and clock_left > FAST_MOVE_CLOCK_SHARE * tc.base_s


# ---------------------------------------------------------------- board rules


def missed_their_threat(eval_after: Eval, me: Color) -> bool:
    """After my move, the opponent has a forced mate."""
    if eval_after.mate is None or eval_after.mate == 0:
        return False
    return eval_after.mate < 0 if me == "white" else eval_after.mate > 0


def missed_my_tactic(finding: Finding, me: Color) -> bool:
    """I had a forced mate before my move and not after it, or the engine's best line (up
    to 6 plies from the position before my move) leaves me 3 or more material up compared
    with that position. ``hung_a_piece`` the other way round."""
    if mover_mates(finding.eval_before, me) and not mover_mates(finding.eval_after, me):
        return True
    color = chess.WHITE if me == "white" else chess.BLACK
    start = chess.Board(finding.ply.fen_before)
    board = _played_out(start, finding.best_pv_uci, MISSED_TACTIC_PLIES)
    gain = material_balance(board, color) - material_balance(start, color)
    return gain >= MISSED_TACTIC_GAIN


def _played_out(board: chess.Board, line: Sequence[str], plies: int) -> chess.Board:
    """``board`` after up to ``plies`` moves of ``line``, stopping at one that isn't legal."""
    board = board.copy(stack=False)
    for uci in line[:plies]:
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            break
        if not board.is_legal(move):
            break
        board.push(move)
    return board


def hung_a_piece(fen_before: str, fen_after: str, refutation: Sequence[str], me: Color) -> bool:
    """My material balance drops by 3 or more once up to 6 plies of the refutation are played.

    The balance is compared with the position before my move. The line stops early at a
    move that isn't legal. Pieces count P=1, N=B=3, R=5, Q=9.
    """
    color = chess.WHITE if me == "white" else chess.BLACK
    board = _played_out(chess.Board(fen_after), refutation, HUNG_PIECE_PLIES)
    drop = material_balance(chess.Board(fen_before), color) - material_balance(board, color)
    return drop >= HUNG_PIECE_DROP


def material_balance(board: chess.Board, color: chess.Color) -> int:
    """My material minus the opponent's, kings not counted."""
    total = 0
    for piece, value in PIECE_VALUES.items():
        total += value * (len(board.pieces(piece, color)) - len(board.pieces(piece, not color)))
    return total
