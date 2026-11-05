from datetime import date, timedelta

import pytest

from blunderbook.core import retest
from blunderbook.core.retest import Schedule

TODAY = date(2026, 11, 5)


def days(n: int) -> date:
    return TODAY + timedelta(days=n)


# ---------------------------------------------------------------- scheduling


@pytest.mark.parametrize(
    ("streak_before", "interval"),
    [(0, 1), (1, 3), (2, 7), (3, 14), (4, 30), (5, 60), (6, 60), (40, 60)],
)
def test_a_solve_climbs_the_interval_ladder(streak_before: int, interval: int) -> None:
    assert retest.after_attempt(streak_before, True, TODAY) == Schedule(
        "solved", streak_before + 1, days(interval)
    )


def test_solving_every_time_gives_the_documented_intervals() -> None:
    streak, gaps = 0, []
    for _ in range(8):
        schedule = retest.after_attempt(streak, True, TODAY)
        streak = schedule.streak
        gaps.append((schedule.due_on - TODAY).days)
    assert gaps == [1, 3, 7, 14, 30, 60, 60, 60]


@pytest.mark.parametrize("streak_before", [0, 1, 5, 12])
def test_a_miss_resets_the_streak_and_comes_back_tomorrow(streak_before: int) -> None:
    assert retest.after_attempt(streak_before, False, TODAY) == Schedule("missed", 0, days(1))


def test_a_miss_at_the_end_of_a_month_comes_back_the_next_day() -> None:
    schedule = retest.after_attempt(3, False, date(2026, 12, 31))
    assert schedule.due_on == date(2027, 1, 1)


def test_a_negative_streak_is_refused() -> None:
    with pytest.raises(ValueError, match="0 or more"):
        retest.after_attempt(-1, True, TODAY)


def test_next_interval_needs_a_solved_streak() -> None:
    assert retest.next_interval(1) == 1
    assert retest.next_interval(6) == 60
    with pytest.raises(ValueError, match="1 or more"):
        retest.next_interval(0)


# ---------------------------------------------------------------- accept matching

ACCEPT = ("e2e3", "d1c2", "a2a3")


@pytest.mark.parametrize("move", ["e2e3", "d1c2", "a2a3", " E2E3 "])
def test_an_accepted_move_solves_it(move: str) -> None:
    assert retest.is_solved(move, ACCEPT)


@pytest.mark.parametrize("move", ["c3d5", "e2e4", "", "e2", "e2e"])
def test_any_other_move_doesnt(move: str) -> None:
    assert not retest.is_solved(move, ACCEPT)


def test_giving_up_never_solves_it() -> None:
    assert not retest.is_solved(None, ACCEPT)


def test_nothing_accepted_means_nothing_solves_it() -> None:
    assert not retest.is_solved("e2e3", ())


@pytest.mark.parametrize(
    ("move", "accept"),
    [
        ("e7e8", ("e7e8q",)),  # promotion defaults to a queen
        ("e7e8q", ("e7e8q",)),
        ("e7e8q", ("e7e8",)),
        ("b2b1", ("b2b1q",)),  # Black promotes too
    ],
)
def test_a_promotion_matches_by_its_squares(move: str, accept: tuple[str, ...]) -> None:
    assert retest.is_solved(move, accept)


def test_matching_is_by_squares_only_as_specified() -> None:
    # CLAUDE.md §7.8: the first 4 UCI characters. An underpromotion to the accepted square
    # counts as the answer too.
    assert retest.is_solved("e7e8n", ("e7e8q",))


# ---------------------------------------------------------------- queue order


def test_the_queue_puts_the_oldest_due_date_first() -> None:
    older = retest.queue_key(days(-3), date(2026, 1, 1), 1, 0)
    newer = retest.queue_key(days(0), date(2026, 11, 1), 9, 0)
    assert sorted([newer, older]) == [older, newer]


def test_on_the_same_due_date_the_most_recent_game_comes_first() -> None:
    items = {
        "old game": retest.queue_key(TODAY, date(2026, 9, 1), 5, 10),
        "new game": retest.queue_key(TODAY, date(2026, 11, 2), 3, 10),
        "no date": retest.queue_key(TODAY, None, 8, 10),
    }
    order = sorted(items, key=items.__getitem__)
    assert order == ["new game", "old game", "no date"]


def test_same_date_falls_back_to_the_newest_game_then_move_order() -> None:
    items = {
        "game 4, ply 20": retest.queue_key(TODAY, None, 4, 20),
        "game 7, ply 30": retest.queue_key(TODAY, None, 7, 30),
        "game 7, ply 12": retest.queue_key(TODAY, None, 7, 12),
    }
    order = sorted(items, key=items.__getitem__)
    assert order == ["game 7, ply 12", "game 7, ply 30", "game 4, ply 20"]
