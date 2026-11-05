"""The Patterns page's numbers (CLAUDE.md §7.9): what causes your blunders, where they
happen, and how the re-tests are going.

Pure: it counts entries the database already read.
"""

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final

from blunderbook.core.models import (
    CAUSES,
    AttemptStats,
    Color,
    Entry,
    Judgment,
    Source,
    Speed,
    Status,
)

SOURCES: Final[tuple[Source, ...]] = ("lichess", "chesscom", "otb", "pgn", "fen")
SPEEDS: Final[tuple[Speed, ...]] = ("bullet", "blitz", "rapid", "classical")
FAST_S: Final = 3.0  # "played in 3 seconds or less"
LOW_CLOCK_S: Final = 30.0  # "under 30 seconds left"


@dataclass(frozen=True, slots=True)
class CauseCount:
    cause: str
    confirmed: int  # entries where you confirmed it
    suggested: int  # entries with nothing confirmed yet, where it's suggested

    @property
    def total(self) -> int:
        return self.confirmed + self.suggested


@dataclass(frozen=True, slots=True)
class SourceCount:
    source: Source
    count: int


@dataclass(frozen=True, slots=True)
class SpeedCount:
    speed: Speed | None  # None: the time control is unknown
    count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class Retested:
    """One re-tested entry, for the Re-test history list."""

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


@dataclass(frozen=True, slots=True, kw_only=True)
class Patterns:
    total: int
    by_source: tuple[SourceCount, ...]  # sources with entries, in SOURCES order
    due: int  # due today or earlier, new ones included
    retests_done: int  # attempts so far
    retested: int  # entries re-tested at least once (status isn't "new")
    solved: int  # of those, currently solved
    solved_pct: int | None  # rounded; None before the first re-test
    timed: int  # entries with the time spent on the move
    fast: int  # of those, played in 3 s or less
    with_clock: int  # entries with the clock left
    low_clock: int  # of those, under 30 s left
    causes: tuple[CauseCount, ...]  # causes that occur, in CAUSES order
    biggest_leak: str | None  # the cause with the highest total; the earlier one on a tie
    by_speed: tuple[SpeedCount, ...]  # speeds with entries, fastest first, unknown last
    history: tuple[Retested, ...]  # most recently re-tested first


def compute(
    entries: Iterable[Entry], attempts: Mapping[int, AttemptStats], today: date
) -> Patterns:
    """The Patterns page for ``entries``. ``attempts`` holds each re-tested entry's stats,
    by entry id. ``today`` is the local date, for what's due."""
    entries = list(entries)
    blunders = [e.blunder for e in entries]

    confirmed: Counter[str] = Counter()
    suggested: Counter[str] = Counter()
    for b in blunders:
        if b.causes:
            confirmed.update(b.causes)
        else:
            suggested.update(b.auto_causes)
    causes = tuple(
        CauseCount(c, confirmed[c], suggested[c]) for c in CAUSES if confirmed[c] + suggested[c]
    )
    leak = max(causes, key=lambda c: c.total, default=None)  # max keeps the first on a tie

    sources = Counter(e.game.source for e in entries)
    speeds = Counter(e.game.speed for e in entries)
    retested = [b for b in blunders if b.status != "new"]
    solved = sum(b.status == "solved" for b in retested)
    timed = [b.time_spent_s for b in blunders if b.time_spent_s is not None]
    clocks = [b.clock_left_s for b in blunders if b.clock_left_s is not None]

    history = [
        Retested(
            id=e.blunder.id,
            move_no=e.blunder.move_no,
            my_color=e.game.my_color,
            played_san=e.blunder.played_san,
            judgment=e.blunder.judgment,
            opponent=e.game.black if e.game.my_color == "white" else e.game.white,
            status=e.blunder.status,
            due_on=e.blunder.due_on,
            attempts=stats.count,
            last_attempted_at=stats.last_at,
        )
        for e in entries
        if (stats := attempts.get(e.blunder.id)) is not None
    ]
    history.sort(key=lambda r: (r.last_attempted_at, r.id), reverse=True)

    return Patterns(
        total=len(entries),
        by_source=tuple(SourceCount(s, sources[s]) for s in SOURCES if sources[s]),
        due=sum(b.due_on <= today for b in blunders),
        retests_done=sum(s.count for s in attempts.values()),
        retested=len(retested),
        solved=solved,
        solved_pct=round(100 * solved / len(retested)) if retested else None,
        timed=len(timed),
        fast=sum(t <= FAST_S for t in timed),
        with_clock=len(clocks),
        low_clock=sum(c < LOW_CLOCK_S for c in clocks),
        causes=causes,
        biggest_leak=None if leak is None else leak.cause,
        by_speed=tuple(SpeedCount(s, speeds[s]) for s in (*SPEEDS, None) if speeds[s]),
        history=tuple(history),
    )
