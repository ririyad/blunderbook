"""Blunder maths (CLAUDE.md §7.6): winning chances, swing, judgment, flagging, accepted moves,
and the move lines shown as "Best was" and "Refutation".

Engine scores arrive as :class:`Eval` from White's point of view. Everything here is pure:
the engine wrapper (1.7) feeds it.
"""

import math
from collections.abc import Iterable, Sequence
from itertools import islice
from typing import Final

import chess

from blunderbook.core.models import Color, Eval, Judgment, Thresholds

WIN_K: Final = 0.00368208  # Lichess winning-chances constant
MATE_CP: Final = 10_000  # mates count as this many centipawns, for the maths only
MISSED_WIN_CAP: Final = 1_000  # evals are capped at +-10 pawns when looking for missed wins
BEST_LINE_PLIES: Final = 6
REFUTATION_PLIES: Final = 5


def winning_chances(cp: float) -> float:
    """``2 / (1 + exp(-0.00368208 * cp)) - 1``: from -1 (lost) to 1 (won), 0 is level."""
    return 2 / (1 + math.exp(-WIN_K * cp)) - 1


def maths_cp(score: Eval, turn: Color) -> int:
    """A White-POV score as centipawns for the maths. Mates count as +-10000.

    ``turn`` is the side to move in the scored position. It's only needed for ``mate 0``
    (that side is already checkmated), which carries no sign of its own.
    """
    if score.mate is None:
        assert score.cp is not None
        return score.cp
    if score.mate > 0:
        return MATE_CP
    if score.mate < 0:
        return -MATE_CP
    return -MATE_CP if turn == "white" else MATE_CP


def _other(color: Color) -> Color:
    return "black" if color == "white" else "white"


def _sign(color: Color) -> int:
    return 1 if color == "white" else -1


def swing(before: Eval, after: Eval, mover: Color) -> float:
    """How much the mover's winning chances dropped, from 0 to 1.

    ``(w_mover(before) - w_mover(after)) / 2``, where ``before`` scores the position the
    mover faced and ``after`` the position after their move (the opponent to move). A move
    the engine likes better than its own choice gives 0, not a negative number.
    """
    sign = _sign(mover)
    w_before = winning_chances(sign * maths_cp(before, mover))
    w_after = winning_chances(sign * maths_cp(after, _other(mover)))
    return max(0.0, (w_before - w_after) / 2)


def chances(score: Eval, turn: Color, me: Color) -> float:
    """``me``'s winning chances in a scored position, as the Log's eval bar shows them: from
    0 (lost) to 1 (won), 0.5 is level. That's ``(1 + w) / 2`` from ``me``'s side, so a move's
    swing is the drop in this number. ``turn`` is the side to move in that position."""
    return (1 + winning_chances(_sign(me) * maths_cp(score, turn))) / 2


def judgment(swing: float, thresholds: Thresholds) -> Judgment | None:
    """``blunder`` / ``mistake`` / ``inaccuracy`` by threshold, or None below all three."""
    if swing >= thresholds.blunder:
        return "blunder"
    if swing >= thresholds.mistake:
        return "mistake"
    if swing >= thresholds.inaccuracy:
        return "inaccuracy"
    return None


def mover_mates(score: Eval, mover: Color) -> bool:
    """``score`` (White POV) is a forced mate for ``mover``: mate in N, N > 0, their way."""
    if score.mate is None or score.mate == 0:
        return False
    return score.mate > 0 if mover == "white" else score.mate < 0


def missed_win(before: Eval, after: Eval, mover: Color, thresholds: Thresholds) -> bool:
    """A missed win (CLAUDE.md §7.6): the mover had a forced mate before the move and not
    after it, or they were ``missed_win_cp`` or more ahead and their eval dropped by that
    much again, both capped at +-1000 cp (a mate counts as 1000). ``missed_win_cp = 0``
    turns missed wins off. Whether the move was the engine's own is for the caller to
    check."""
    if thresholds.missed_win_cp <= 0:
        return False
    if mover_mates(before, mover) and not mover_mates(after, mover):
        return True
    sign = _sign(mover)
    cap = MISSED_WIN_CAP
    was = max(-cap, min(cap, sign * maths_cp(before, mover)))
    now = max(-cap, min(cap, sign * maths_cp(after, _other(mover))))
    line = thresholds.missed_win_cp
    return was >= line and was - now >= line


def is_flagged(
    swing: float,
    played_uci: str,
    best_uci: str | None,
    thresholds: Thresholds,
    flag_at: Judgment = "blunder",
) -> bool:
    """A move is logged when its swing reaches the ``flag_at`` line and it isn't the
    engine's best move. Imports flag from the blunder line; a FEN entry from the inaccuracy
    line (CLAUDE.md §9). No best move (the engine gave none) means no flag."""
    line = {
        "blunder": thresholds.blunder,
        "mistake": thresholds.mistake,
        "inaccuracy": thresholds.inaccuracy,
    }[flag_at]
    return best_uci is not None and played_uci != best_uci and swing >= line


def accepted_moves(
    lines: Sequence[tuple[str, Eval]],
    mover: Color,
    best_uci: str,
    margin_cp: int,
    *,
    played_uci: str | None = None,
) -> tuple[str, ...]:
    """Moves a re-test accepts: the best move, then every MultiPV move whose score for the
    mover is within ``margin_cp`` of the best line's, in engine order.

    ``lines`` are ``(first move UCI, White-POV score)`` pairs for the position before the
    mover's move. Mates count as +-10000, so when the best line mates, every mating move is
    accepted. ``played_uci`` (the move that was flagged) is never accepted, even if a
    deeper look rates it close: the re-test shouldn't pass the move you blundered with.
    """
    sign = _sign(mover)
    scores = [sign * maths_cp(score, mover) for _, score in lines]
    top = max(scores, default=0)
    accepted = [best_uci]
    for (uci, _), cp in zip(lines, scores, strict=True):
        if top - cp <= margin_cp and uci not in accepted and uci != played_uci:
            accepted.append(uci)
    return tuple(accepted)


def line_san(fen: str, moves: Iterable[chess.Move], plies: int) -> str:
    """The first ``plies`` moves of an engine line as SAN with move numbers.

    ``"6. e3 Be7 7. Bd3"`` from White, ``"5... Nxe5 6. Be2"`` from Black. Stops early at
    the end of the line or at a move that isn't legal (a stale or broken PV).
    """
    board = chess.Board(fen)
    parts: list[str] = []
    for move in islice(moves, plies):
        if not board.is_legal(move):
            break
        san = board.san(move)
        if board.turn == chess.WHITE:
            parts.append(f"{board.fullmove_number}. {san}")
        elif not parts:
            parts.append(f"{board.fullmove_number}... {san}")
        else:
            parts.append(san)
        board.push(move)
    return " ".join(parts)


def best_line_san(fen_before: str, pv: Iterable[chess.Move]) -> str:
    """The "Best was" line: the first 6 plies of the best line, from the position before."""
    return line_san(fen_before, pv, BEST_LINE_PLIES)


def refutation_san(fen_after: str, pv: Iterable[chess.Move]) -> str | None:
    """The "Refutation": the first 5 plies of the engine line after my move, None if empty."""
    return line_san(fen_after, pv, REFUTATION_PLIES) or None
