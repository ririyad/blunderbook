"""What an AI explanation of one mistake is given, and the prompt (CLAUDE.md §7.10).

The model never analyses the position. It gets Stockfish's lines plus facts python-chess
works out here (each capture along a line, pieces left attacked, checkmates, material), and
is told to explain only those. Everything here is pure: ``ai.py`` sends the prompt.

Only what's in :class:`Mistake` can be sent, and it has no field for player names, ratings,
dates, the site, or your notes (thinking, lesson, confirmed causes). :func:`mistake` copies
the allowed fields out of an entry.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Final

import chess

from blunderbook.core import detect, hints, timecontrol
from blunderbook.core.models import JUDGMENT_NOUN, Color, Entry, Eval, Judgment, TimeControl

PROMPT_VERSION: Final = 2  # stored with each explanation; bump when the prompt changes

MARK: Final[dict[Judgment, str]] = {
    "blunder": "??",
    "mistake": "?",
    "inaccuracy": "?!",
    "missed": "",
}
PIECE_NAMES: Final = {
    chess.PAWN: "pawn",
    chess.KNIGHT: "knight",
    chess.BISHOP: "bishop",
    chess.ROOK: "rook",
    chess.QUEEN: "queen",
    chess.KING: "king",
}

SYSTEM: Final = """\
You explain one chess mistake to the player who made it, so they understand why it was bad.

Rules:
- Use only the moves and facts given. They come from the Stockfish engine and from the \
python-chess library, and they are correct.
- Don't add moves, variations or tactics that aren't listed. Don't work out new lines.
- Say what the move allowed, using Stockfish's line after it, and what the best move does \
instead. If the facts don't show why the best move is better, say what they show and stop.
- If the move is a missed win, the player is still ahead after it: say what the best move \
would have won, and don't call their move a losing one.
- Write 3 or 4 plain sentences in the second person ("You played..."). Use the moves in \
standard notation as given.
- No markdown, no headings, no lists, no exclamation marks. Don't scold, and don't tell \
them what they were thinking."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Mistake:
    """One logged move: everything an explanation may use, and nothing else."""

    fen_before: str
    my_color: Color
    played_uci: str
    best_uci: str
    best_line_san: str
    refutation_san: str | None
    eval_before: Eval
    eval_after: Eval
    judgment: Judgment
    clock_left_s: float | None = None
    time_spent_s: float | None = None
    time_control: str | None = None  # e.g. "3+2 blitz"
    opening: str | None = None  # e.g. "Queen's Gambit Declined (D51)"
    auto_causes: tuple[str, ...] = ()  # the app's suggestions, never your confirmed causes


def mistake(entry: Entry) -> Mistake:
    """The parts of an entry an explanation may use."""
    b, g = entry.blunder, entry.game
    tc_text = None
    if g.tc_base_s is not None and g.tc_inc_s is not None:
        tc = TimeControl(g.tc_base_s, g.tc_inc_s)
        tc_text = f"{timecontrol.label(tc)} {timecontrol.speed(tc)}"
    opening = g.opening
    if opening and g.eco:
        opening = f"{opening} ({g.eco})"
    return Mistake(
        fen_before=b.fen_before,
        my_color=g.my_color,
        played_uci=b.played_uci,
        best_uci=b.best_uci,
        best_line_san=b.best_line_san,
        refutation_san=b.refutation_san,
        eval_before=b.eval_before,
        eval_after=b.eval_after,
        judgment=b.judgment,
        clock_left_s=b.clock_left_s,
        time_spent_s=b.time_spent_s,
        time_control=tc_text,
        opening=opening,
        auto_causes=b.auto_causes,
    )


# ---------------------------------------------------------------- facts


@dataclass(frozen=True, slots=True)
class LineFacts:
    """An engine line played out on the board."""

    text: str  # the moves as read, with move numbers: "6... Nxd5 7. Bxd8 Bb4+"
    captures: tuple[str, ...]  # "Nxd5 takes your knight on d5"
    material: int  # your material balance at the end, minus before your move
    ending: str | None  # "checkmate" / "stalemate" when the line ends the game
    unsettled: bool  # the last move captures or checks, so an exchange may go on


@dataclass(frozen=True, slots=True)
class Facts:
    side: str  # "White" / "Black"
    move: str  # "6. Nxd5"
    played_san: str
    best_san: str
    best_move_notes: tuple[str, ...]  # "it captures their pawn on d5", "it gives check"
    eval_before: str  # in words, from your side
    eval_after: str
    after_move: tuple[str, ...]  # board facts right after your move
    game_over: str | None  # your move ended the game ("stalemate")
    refutation: LineFacts | None  # Stockfish's line after your move
    best_line: LineFacts | None  # the best move and what follows


def facts(m: Mistake) -> Facts:
    me = chess.WHITE if m.my_color == "white" else chess.BLACK
    before = chess.Board(m.fen_before)
    played = chess.Move.from_uci(m.played_uci)
    best = chess.Move.from_uci(m.best_uci)
    after = before.copy(stack=False)
    after.push(played)
    return Facts(
        side="White" if me == chess.WHITE else "Black",
        move=_move_label(before, played),
        played_san=before.san(played),
        best_san=before.san(best),
        best_move_notes=_move_notes(before, best, me),
        eval_before=eval_words(m.eval_before, m.my_color, m.my_color),
        eval_after=eval_words(m.eval_after, _other(m.my_color), m.my_color),
        after_move=_after_move(after, m),
        game_over=_ending(after),
        refutation=_line(m.fen_before, after, m.refutation_san, me),
        best_line=_line(m.fen_before, before, m.best_line_san, me),
    )


def read_line(board: chess.Board, text: str) -> Iterator[chess.Move]:
    """The moves of a stored SAN line (``"6. e3 Be7 7. Bd3"``), played on a copy of
    ``board``. Move numbers are skipped. Stops at the first token that isn't a legal move."""
    board = board.copy(stack=False)
    for token in text.split():
        if token.rstrip(".").isdigit():
            continue
        try:
            move = board.parse_san(token)
        except ValueError:
            return
        yield move
        board.push(move)


def eval_words(score: Eval, turn: Color, me: Color) -> str:
    """A White-POV score from ``me``'s side, in words: "+0.36, about equal (52% winning
    chances)", "they have mate in 1". ``turn`` is the side to move in that position."""
    if score.mate is not None:
        if score.mate == 0:
            return "checkmate, you lost" if turn == me else "checkmate, you won"
        mine = (score.mate > 0) == (me == "white")
        n = abs(score.mate)
        return f"you have mate in {n}" if mine else f"they have mate in {n}"
    assert score.cp is not None
    cp = score.cp if me == "white" else -score.cp
    pct = round(100 * detect.chances(score, turn, me))
    return f"{cp / 100:+.2f}, {_standing(pct)} ({pct}% winning chances)"


def _standing(pct: int) -> str:
    if pct >= 85:
        return "winning for you"
    if pct >= 60:
        return "better for you"
    if pct > 40:
        return "about equal"
    if pct > 15:
        return "better for them"
    return "losing for you"


def _other(color: Color) -> Color:
    return "black" if color == "white" else "white"


def _move_label(board: chess.Board, move: chess.Move) -> str:
    dots = "." if board.turn == chess.WHITE else "..."
    return f"{board.fullmove_number}{dots} {board.san(move)}"


def _whose(color: chess.Color, me: chess.Color) -> str:
    return "your" if color == me else "their"


def _captured(board: chess.Board, move: chess.Move) -> tuple[chess.Piece, chess.Square] | None:
    if board.is_en_passant(move):
        square = move.to_square + (-8 if board.turn == chess.WHITE else 8)
    elif board.is_capture(move):
        square = move.to_square
    else:
        return None
    piece = board.piece_at(square)
    return None if piece is None else (piece, square)


def _move_notes(board: chess.Board, move: chess.Move, me: chess.Color) -> tuple[str, ...]:
    notes: list[str] = []
    taken = _captured(board, move)
    if taken is not None:
        piece, square = taken
        notes.append(
            f"it captures {_whose(piece.color, me)} {PIECE_NAMES[piece.piece_type]} "
            f"on {chess.square_name(square)}"
        )
    if move.promotion:
        notes.append(f"it promotes to a {PIECE_NAMES[move.promotion]}")
    if board.gives_check(move):
        notes.append("it gives check")
    return tuple(notes)


def _line(fen_before: str, start: chess.Board, text: str | None, me: chess.Color) -> LineFacts:
    """``text`` played out from ``start``, with material compared with ``fen_before``."""
    board = start.copy(stack=False)
    parts: list[str] = []
    captures: list[str] = []
    unsettled = False
    for move in read_line(start, text or ""):
        if board.turn == chess.WHITE:
            parts.append(f"{board.fullmove_number}.")
        elif not parts:
            parts.append(f"{board.fullmove_number}...")
        san = board.san(move)
        parts.append(san)
        taken = _captured(board, move)
        if taken is not None:
            piece, square = taken
            captures.append(
                f"{san} takes {_whose(piece.color, me)} {PIECE_NAMES[piece.piece_type]} "
                f"on {chess.square_name(square)}"
            )
        unsettled = taken is not None or board.gives_check(move)
        board.push(move)
    material = hints.material_balance(board, me) - hints.material_balance(
        chess.Board(fen_before), me
    )
    return LineFacts(" ".join(parts), tuple(captures), material, _ending(board), unsettled)


def _ending(board: chess.Board) -> str | None:
    if board.is_checkmate():
        return "checkmate"
    if board.is_stalemate():
        return "stalemate"
    if board.is_insufficient_material():
        return "a draw by insufficient material"
    return None


def _after_move(board: chess.Board, m: Mistake) -> tuple[str, ...]:
    """Your pieces left attacked after your move: by a cheaper piece, with no defender, or
    more times than defended. Counts direct attacks only (no pins or x-rays)."""
    me = chess.WHITE if m.my_color == "white" else chess.BLACK
    found: list[str] = []
    if board.is_check():
        found.append("Their king is in check.")
    for square, piece in sorted(board.piece_map().items()):
        if piece.color != me or piece.piece_type == chess.KING:
            continue
        attackers = board.attackers(not me, square)
        if not attackers:
            continue
        defenders = len(board.attackers(me, square))
        value = hints.PIECE_VALUES[piece.piece_type]
        cheapest = min(_value(board, s) for s in attackers)
        name = f"Your {PIECE_NAMES[piece.piece_type]} on {chess.square_name(square)}"
        if cheapest < value:
            attacker = board.piece_at(min(attackers, key=lambda s: _value(board, s)))
            assert attacker is not None
            found.append(f"{name} is attacked by their {PIECE_NAMES[attacker.piece_type]}.")
        elif not defenders:
            found.append(f"{name} is attacked and not defended.")
        elif len(attackers) > defenders:
            found.append(
                f"{name} is attacked {_times(len(attackers))} and defended {_times(defenders)}."
            )
    if hints.missed_their_threat(m.eval_after, m.my_color):
        found.append("They now have a forced mate.")
    return tuple(found)


def _value(board: chess.Board, square: chess.Square) -> int:
    piece = board.piece_at(square)
    assert piece is not None
    return 100 if piece.piece_type == chess.KING else hints.PIECE_VALUES[piece.piece_type]


def _times(n: int) -> str:
    return {1: "once", 2: "twice"}.get(n, f"{n} times")


# ---------------------------------------------------------------- prompt


@dataclass(frozen=True, slots=True)
class Prompt:
    system: str
    user: str


def build_prompt(m: Mistake) -> Prompt:
    """The two messages sent to the model. The user message is the facts, in plain text."""
    f = facts(m)
    lines = [
        f"You played {f.side}. Your move was {f.move}{MARK[m.judgment]}, "
        f"{JUDGMENT_NOUN[m.judgment]}.",
        f"Position before your move (FEN): {m.fen_before}",
    ]
    if m.opening:
        lines.append(f"Opening: {m.opening}")
    clock = _clock_line(m)
    if clock:
        lines.append(clock)
    lines += ["", f"Evaluation before your move: {f.eval_before}."]
    lines.append(f"Evaluation after your move: {f.eval_after}.")

    lines += ["", f"After your move {f.played_san}:"]
    if f.game_over:
        lines.append(f"- The game ends: {f.game_over}.")
    lines += [f"- {fact}" for fact in f.after_move] or ["- None of your pieces is attacked."]
    if f.refutation is not None and f.refutation.text:
        lines += ["", "Stockfish's line after your move:", f.refutation.text]
        lines += _line_details(f.refutation)

    best = f"Stockfish's best move instead: {f.best_san}"
    if f.best_move_notes:
        best += f" ({', '.join(f.best_move_notes)})"
    lines += ["", best + "."]
    if f.best_line is not None and f.best_line.text:
        lines += ["Stockfish's best line:", f.best_line.text]
        lines += _line_details(f.best_line)

    if m.auto_causes:
        lines += ["", f"The app suggests, unconfirmed: {', '.join(m.auto_causes)}."]
    return Prompt(SYSTEM, "\n".join(lines))


def _line_details(line: LineFacts) -> list[str]:
    out = [f"- {c}." for c in line.captures]
    if line.ending:
        out.append(f"- The line ends in {line.ending}.")
    else:
        text = (
            "- Your material at the end of this line, compared with before your move: "
            + _material(line.material)
        )
        if line.unsettled:
            text += " (the line stops in the middle of an exchange or a check)"
        out.append(text + ".")
    return out


def _material(n: int) -> str:
    if n == 0:
        return "the same"
    unit = "point" if abs(n) == 1 else "points"
    return f"{abs(n)} {unit} {'up' if n > 0 else 'down'}"


def _clock_line(m: Mistake) -> str | None:
    parts: list[str] = []
    if m.time_control:
        parts.append(f"Time control: {m.time_control}.")
    if m.clock_left_s is not None:
        parts.append(f"Your clock after the move: {_clock(m.clock_left_s)}.")
    if m.time_spent_s is not None:
        parts.append(f"Time you spent on it: {round(m.time_spent_s)} s.")
    return " ".join(parts) or None


def _clock(seconds: float) -> str:
    t = round(seconds)
    h, m, s = t // 3600, t % 3600 // 60, t % 60
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"
