"""JSON shapes of the API (CLAUDE.md §10). Dates are local ``YYYY-MM-DD``, timestamps UTC.

Evals are White POV, exactly as stored: ``{"cp": 36}`` or ``{"mate": -2}``.
"""

import datetime as dt
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


class ExplanationOut(BaseModel):
    """A saved AI explanation (CLAUDE.md §7.10)."""

    text: str
    model: str
    created_at: datetime


class ExtensionOut(BaseModel):
    """An extension that's on and has a page: the page adds a tab for it."""

    name: str  # its route (#name) and folder (/ext/name/)
    title: str  # the tab's label
    css: bool  # it has a view.css to load


class AiOut(BaseModel):
    """Whether the page shows "Explain this blunder". Never the key."""

    enabled: bool  # on, with a key and a model
    model: str | None


class PromptOut(BaseModel):
    """Exactly what "Explain this blunder" would send ("What's sent")."""

    model: str | None
    system: str
    user: str


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
    explanation: ExplanationOut | None = None


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
    move_fen: str | None  # the position after your move, to draw it; null when you gave up
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
    explanation: ExplanationOut | None = None  # after the attempt only, like the answer


class HintOut(BaseModel):
    from_square: str  # "e2": where the best move starts


# ---------------------------------------------------------------- patterns


class CauseCountOut(BaseModel):
    cause: str
    confirmed: int  # solid bar: entries where you confirmed it
    suggested: int  # striped bar: suggested on entries with nothing confirmed yet


class SourceCountOut(BaseModel):
    source: Source
    count: int


class SpeedCountOut(BaseModel):
    speed: Speed | None  # null: the time control is unknown
    count: int


class RetestedOut(BaseModel):
    id: int
    move_no: int
    my_color: Color
    played_san: str
    judgment: Judgment
    opponent: str | None
    status: Status
    due_on: date
    attempts: int
    last_attempted_at: datetime


class PatternsOut(BaseModel):
    """The Patterns page (CLAUDE.md §7.9)."""

    total: int
    by_source: list[SourceCountOut]  # sources with entries, in a fixed order
    due: int  # due today or earlier, new ones included
    retests_done: int
    retested: int  # entries re-tested at least once
    solved: int  # of those, currently solved
    solved_pct: int | None  # null before the first re-test
    timed: int  # entries with the time spent on the move
    fast: int  # of those, played in 3 s or less
    with_clock: int  # entries with the clock left
    low_clock: int  # of those, under 30 s left
    causes: list[CauseCountOut]  # causes that occur, in the fixed cause order
    biggest_leak: str | None
    by_speed: list[SpeedCountOut]  # fastest first, unknown last
    history: list[RetestedOut]  # most recently re-tested first


# ---------------------------------------------------------------- import


class EntryRefOut(BaseModel):
    id: int
    label: str  # "6. Nxd5"
    judgment: Judgment


class ImportGameOut(BaseModel):
    number: int  # its place in the text
    players: str  # "Rashed vs Karim S."
    date: str | None
    site_label: str | None
    my_color: Color | None
    # waiting | analysing | analysed | imported | not_analysed | needs_side | duplicate | error
    status: str
    reason: str | None  # why it's skipped, or what to do
    warnings: list[str]
    entries: list[EntryRefOut]  # new entries, once the import finished


class ImportJobOut(BaseModel):
    id: str
    status: str  # running | done | stopped | failed
    percent: int  # of the whole import
    game: int | None  # the game being analysed
    game_index: int  # its place among the games to analyse (1-based; 0 before the first)
    games_to_analyse: int
    done: int  # positions of that game done / total
    total: int
    engine_name: str | None
    games: list[ImportGameOut]
    summary: str  # "2 games read · 1 skipped (duplicate) · 3 blunders added"
    notes: list[str]
    error: str | None


class ImportStarted(BaseModel):
    job_id: str


class FenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fen: str
    move: str  # UCI (e2e4) or SAN (Nf3)
    opponent: str | None = None
    date: dt.date | None = None  # default: today


class FenOut(BaseModel):
    result: str  # logged | already_logged | best_move | not_a_mistake
    message: str
    entry_id: int | None
    notes: list[str]
