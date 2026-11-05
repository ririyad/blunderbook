"""JSON shapes of the API (CLAUDE.md §10). Dates are local ``YYYY-MM-DD``, timestamps UTC.

Evals are White POV, exactly as stored: ``{"cp": 36}`` or ``{"mate": -2}``.
"""

from datetime import date, datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict

from blunderbook.core.models import CAUSES, Color, Judgment, Source, Speed, Status


def known_cause(cause: str) -> str:
    if cause not in CAUSES:
        raise ValueError(f"Unknown cause: {cause!r}. Choose from the fixed list.")
    return cause


Cause = Annotated[str, AfterValidator(known_cause)]


class EntrySummary(BaseModel):
    """One row of the Log list."""

    id: int
    source: Source
    my_color: Color
    move_no: int
    played_san: str
    judgment: Judgment
    status: Status
    due_on: date
    opponent: str | None
    played_on: date | None
    speed: Speed | None
    tc_label: str | None  # "3+2"; None when the time control is unknown


class MoveOut(BaseModel):
    """One move of the game, for the step controls."""

    ply: int  # 0-based; the entry's ply is the move you played
    move_no: int
    color: Color
    san: str
    uci: str
    fen: str  # the position after this move


class GameOut(BaseModel):
    id: int
    source: Source
    site_label: str | None  # "Lichess", "Over the board · Dhaka Chess Club", "FEN entry"
    white: str | None
    black: str | None
    white_elo: int | None
    black_elo: int | None
    my_color: Color
    opponent: str | None
    result: str | None  # "1-0" | "0-1" | "1/2-1/2" | "*"
    played_on: date | None
    time_control: str | None  # the raw header, "180+2"
    tc_label: str | None  # "3+2"
    speed: Speed | None
    opening: str | None
    eco: str | None
    has_clocks: bool
    engine_name: str | None
    engine_depth: int | None
    start_fen: str
    moves: list[MoveOut]  # the whole mainline; empty if the stored PGN can't be read


class EntryOut(BaseModel):
    """One entry with its game, as the Log's detail panel shows it."""

    id: int
    ply: int
    move_no: int
    fen_before: str
    played_uci: str
    played_san: str
    best_uci: str
    best_san: str
    best_line_san: str
    refutation_san: str | None
    eval_before: dict[str, int]
    eval_after: dict[str, int]
    chances_before: float  # your winning chances, 0..1, before and after your move
    chances_after: float
    swing: float
    judgment: Judgment
    clock_left_s: float | None
    time_spent_s: float | None
    auto_causes: list[str]  # suggestions only
    causes: list[str]  # confirmed by you
    other_cause: str | None
    thinking: str
    lesson: str
    status: Status
    streak: int
    due_on: date
    created_at: datetime
    updated_at: datetime
    game: GameOut


class NotesIn(BaseModel):
    """Your part of an entry. A field left out (or null) is left as it is. ``causes`` replaces
    the confirmed list; ``other_cause: ""`` clears it. Text is kept exactly as sent."""

    model_config = ConfigDict(extra="forbid")

    causes: list[Cause] | None = None
    other_cause: str | None = None
    thinking: str | None = None
    lesson: str | None = None


# ---------------------------------------------------------------- re-test


class RetestItem(BaseModel):
    """One position to re-test. It never carries the answer: no best move, accepted moves,
    the move you played, the lines or your lesson (CLAUDE.md §10)."""

    id: int
    fen: str  # the position before your move
    my_color: Color  # the side to move, and the way the board faces
    move_no: int
    legal_uci: list[str]  # every legal move, for tap-to-move
    source: Source
    site_label: str | None
    opponent: str | None
    played_on: date | None
    due_on: date


class RetestQueue(BaseModel):
    items: list[RetestItem]  # oldest due date first, then the most recent game
    total: int  # all entries, for "Practise all anyway"
    next_due_on: date | None  # the first re-test after today, when nothing is due


class AttemptIn(BaseModel):
    """Your move, or ``null`` when you gave up ("I don't know — show me")."""

    model_config = ConfigDict(extra="forbid")

    move_uci: str | None
    used_hint: bool = False


class AttemptOut(BaseModel):
    """The answer, sent only after you tried."""

    id: int
    solved: bool
    move_uci: str | None  # your move as recorded (a bare promotion becomes a queen)
    move_san: str | None
    best_uci: str
    best_san: str
    best_line_san: str
    played_uci: str  # what you played in the game
    played_san: str
    refutation_san: str | None
    judgment: Judgment
    lesson: str
    status: Status
    streak: int
    due_on: date
    next_in_days: int


class HintOut(BaseModel):
    from_square: str  # "e2": where the best move starts
