"""Patterns aggregation (CLAUDE.md §7.9), on hand-made entries: no database, no engine."""

from datetime import UTC, date, datetime, timedelta
from typing import Any

from blunderbook.core import patterns
from blunderbook.core.models import (
    CAUSES,
    AttemptStats,
    Blunder,
    Entry,
    Eval,
    Game,
)
from blunderbook.core.patterns import CauseCount, SourceCount, SpeedCount

TODAY = date(2026, 11, 5)
NOW = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)
START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def entry(n: int, **fields: Any) -> Entry:
    """Entry ``n``, with its own game. Game fields and blunder fields can both be given."""
    game_fields = {
        k: fields.pop(k) for k in ("source", "speed", "my_color", "white", "black") if k in fields
    }
    game = Game(
        id=n,
        fingerprint=f"fp{n}",
        source=game_fields.get("source", "lichess"),
        my_color=game_fields.get("my_color", "white"),
        start_fen=START,
        pgn="1. e4 *",
        engine_name="Stockfish 17.1",
        engine_depth=16,
        white=game_fields.get("white", "Rashed"),
        black=game_fields.get("black", f"opponent{n}"),
        speed=game_fields.get("speed", "blitz"),
        analysis_status="done",
        imported_at=NOW,
    )
    blunder = Blunder(
        id=n,
        game_id=n,
        ply=0,
        move_no=n,
        fen_before=START,
        played_uci="f2f3",
        played_san="f3",
        best_uci="e2e4",
        best_san="e4",
        best_line_san="1. e4",
        accept_uci=("e2e4",),
        eval_before=Eval(cp=20),
        eval_after=Eval(cp=-300),
        swing=0.3,
        judgment=fields.pop("judgment", "blunder"),
        clock_left_s=fields.pop("clock_left_s", None),
        time_spent_s=fields.pop("time_spent_s", None),
        auto_causes=tuple(fields.pop("auto_causes", ())),
        causes=tuple(fields.pop("causes", ())),
        other_cause=None,
        thinking="",
        lesson="",
        status=fields.pop("status", "new"),
        streak=0,
        due_on=fields.pop("due_on", TODAY),
        created_at=NOW,
        updated_at=NOW,
    )
    assert not fields, f"unknown fields: {fields}"
    return Entry(blunder, game)


def compute(entries: list[Entry], attempts: dict[int, AttemptStats] | None = None) -> Any:
    return patterns.compute(entries, attempts or {}, TODAY)


def test_nothing_logged_yet() -> None:
    found = compute([])
    assert found.total == 0
    assert found.by_source == ()
    assert (found.due, found.retests_done, found.retested, found.solved) == (0, 0, 0, 0)
    assert found.solved_pct is None
    assert (found.timed, found.fast, found.with_clock, found.low_clock) == (0, 0, 0, 0)
    assert found.causes == ()
    assert found.biggest_leak is None
    assert found.by_speed == ()
    assert found.history == ()


# ---------------------------------------------------------------- causes


def test_confirmed_causes_win_over_suggestions() -> None:
    found = compute(
        [
            # Confirmed: its suggestions don't count.
            entry(1, causes=["Hung a piece"], auto_causes=["Moved too fast", "Time trouble"]),
            # Nothing confirmed yet: its suggestions count, striped.
            entry(2, auto_causes=["Moved too fast", "Hung a piece"]),
            entry(3, causes=["Hung a piece", "Wrong plan"]),
            entry(4),  # no causes at all
        ]
    )
    assert found.causes == (
        CauseCount("Hung a piece", confirmed=2, suggested=1),
        CauseCount("Moved too fast", confirmed=0, suggested=1),
        CauseCount("Wrong plan", confirmed=1, suggested=0),
    )


def test_causes_keep_the_fixed_order_not_the_count_order() -> None:
    found = compute(
        [entry(i, causes=["Other"]) for i in range(1, 4)] + [entry(9, causes=["Hung a piece"])]
    )
    assert [c.cause for c in found.causes] == ["Hung a piece", "Other"]
    assert [c.cause for c in found.causes] == [c for c in CAUSES if c in {"Hung a piece", "Other"}]


def test_the_biggest_leak_counts_confirmed_and_suggested() -> None:
    found = compute(
        [
            entry(1, causes=["Time trouble"]),
            entry(2, auto_causes=["Missed their threat"]),
            entry(3, auto_causes=["Missed their threat"]),
        ]
    )
    assert found.biggest_leak == "Missed their threat"


def test_a_tied_leak_goes_to_the_earlier_cause() -> None:
    found = compute([entry(1, causes=["Wrong plan"]), entry(2, causes=["Missed my tactic"])])
    assert found.biggest_leak == "Missed my tactic"


# ---------------------------------------------------------------- tiles


def test_entries_per_source_in_a_fixed_order() -> None:
    found = compute(
        [
            entry(1, source="fen"),
            entry(2, source="chesscom"),
            entry(3, source="lichess"),
            entry(4, source="chesscom"),
        ]
    )
    assert found.total == 4
    assert found.by_source == (
        SourceCount("lichess", 1),
        SourceCount("chesscom", 2),
        SourceCount("fen", 1),
    )


def test_due_counts_today_and_earlier_new_ones_included() -> None:
    found = compute(
        [
            entry(1),  # new, due today
            entry(2, status="missed", due_on=TODAY - timedelta(days=3)),
            entry(3, status="solved", due_on=TODAY + timedelta(days=1)),
        ]
    )
    assert found.due == 2


def test_solved_share_is_among_re_tested_entries() -> None:
    found = compute(
        [
            entry(1, status="solved"),
            entry(2, status="solved"),
            entry(3, status="missed"),
            entry(4),  # never re-tested: not counted
        ]
    )
    assert (found.retested, found.solved, found.solved_pct) == (3, 2, 67)


def test_clock_tiles_only_count_entries_with_clock_data() -> None:
    found = compute(
        [
            entry(1, time_spent_s=3.0, clock_left_s=120.0),  # fast (3 s counts)
            entry(2, time_spent_s=3.1, clock_left_s=29.9),  # low clock
            entry(3, time_spent_s=0.5, clock_left_s=30.0),  # fast; 30 s isn't under 30
            entry(4, clock_left_s=8.0),  # clock left, time spent unknown
            entry(5),  # no clock data (OTB)
        ]
    )
    assert (found.timed, found.fast) == (3, 2)
    assert (found.with_clock, found.low_clock) == (4, 2)


def test_by_speed_fastest_first_unknown_last() -> None:
    found = compute(
        [
            entry(1, speed="rapid"),
            entry(2, speed=None),
            entry(3, speed="bullet"),
            entry(4, speed="rapid"),
        ]
    )
    assert found.by_speed == (
        SpeedCount("bullet", 1),
        SpeedCount("rapid", 2),
        SpeedCount(None, 1),
    )


# ---------------------------------------------------------------- re-test history


def test_history_lists_re_tested_entries_most_recent_first() -> None:
    entries = [
        entry(1, status="solved", my_color="black", white="kotha", black="Rashed"),
        entry(2),
        entry(3, status="missed", judgment="mistake"),
    ]
    attempts = {
        1: AttemptStats(2, NOW - timedelta(days=2)),
        3: AttemptStats(1, NOW - timedelta(hours=1)),
    }
    found = compute(entries, attempts)
    assert found.retests_done == 3
    assert [r.id for r in found.history] == [3, 1]
    first, second = found.history
    assert (first.status, first.judgment, first.attempts) == ("missed", "mistake", 1)
    assert (second.my_color, second.opponent, second.attempts) == ("black", "kotha", 2)
    assert second.last_attempted_at == NOW - timedelta(days=2)
