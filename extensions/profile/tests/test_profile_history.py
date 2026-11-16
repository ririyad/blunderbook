"""Your rating over time, from your games (ROADMAP 17.2): pure, no database."""

from datetime import date

from blunderbook_profile import history
from blunderbook_profile.history import Chart, ChartMonth, Latest, Line, Month, Played
from profile_fakes import cfg_file, row  # noqa: F401  (fixtures)


def test_played_takes_your_side_of_site_games_oldest_first() -> None:
    rows = [
        row(3, "lichess", "blitz", date(2026, 11, 2), 1640, me="black", blunders=2),
        row(1, "lichess", "blitz", date(2026, 10, 30), 1620),
        row(2, "chesscom", "rapid", date(2026, 11, 2), 1655),
    ]
    assert history.played(rows) == [
        Played(1, "lichess", "blitz", date(2026, 10, 30), 1620, 0),
        Played(2, "chesscom", "rapid", date(2026, 11, 2), 1655, 0),
        Played(3, "lichess", "blitz", date(2026, 11, 2), 1640, 2),  # Black's rating, not 2400
    ]


def test_games_that_cant_say_are_left_out() -> None:
    rows = [
        row(1, "otb", "classical", date(2026, 11, 1), 1800),  # not a site rating
        row(2, "pgn", "blitz", date(2026, 11, 1), 1800),
        row(3, "lichess", "blitz", date(2026, 11, 1), None),  # no rating ("?", provisional)
        row(4, "lichess", "blitz", None, 1600),  # no date
        row(5, "lichess", None, date(2026, 11, 1), 1600),  # no time control
    ]
    assert history.played(rows) == []
    assert history.lines(rows) == []
    assert history.latest(rows) == []


def test_lines_month_by_month() -> None:
    rows = [
        row(1, "lichess", "blitz", date(2026, 9, 3), 1600, blunders=1),
        row(2, "lichess", "blitz", date(2026, 9, 28), 1612, blunders=2),
        row(3, "lichess", "blitz", date(2026, 11, 1), 1647),  # nothing in October
        row(4, "lichess", "blitz", date(2026, 11, 1), 1640, blunders=1),  # later that day
        row(5, "lichess", "bullet", date(2026, 11, 4), 1512),
        row(6, "chesscom", "blitz", date(2026, 11, 5), 1502, blunders=3),
    ]
    assert history.lines(reversed(rows)) == [  # newest first, as the Log lists them
        Line("lichess", "bullet", (Month("2026-11", 1512, 1, 0),)),
        Line(
            "lichess",
            "blitz",
            (Month("2026-09", 1612, 2, 3), Month("2026-11", 1640, 2, 1)),
        ),
        Line("chesscom", "blitz", (Month("2026-11", 1502, 1, 3),)),
    ]


def test_blunders_per_game() -> None:
    assert Month("2026-09", 1612, 2, 3).blunders_per_game == 1.5
    assert Month("2026-09", 1612, 4, 0).blunders_per_game == 0


def test_latest_is_your_newest_game_of_each() -> None:
    rows = [
        row(1, "lichess", "blitz", date(2026, 9, 3), 1600),
        row(2, "lichess", "blitz", date(2026, 11, 1), 1647),
        row(3, "chesscom", "rapid", date(2026, 10, 7), 1655),
        row(4, "lichess", "rapid", date(2026, 8, 1), 1790),
    ]
    assert history.latest(rows) == [
        Latest("lichess", "blitz", 1647, date(2026, 11, 1), 2),
        Latest("lichess", "rapid", 1790, date(2026, 8, 1), 4),
        Latest("chesscom", "rapid", 1655, date(2026, 10, 7), 3),
    ]


def test_charts_put_both_sites_side_by_side_and_keep_empty_months() -> None:
    rows = [
        row(1, "lichess", "blitz", date(2026, 9, 3), 1600, blunders=1),
        row(2, "lichess", "blitz", date(2026, 9, 28), 1612, blunders=2),
        row(3, "chesscom", "blitz", date(2026, 9, 30), 1490),
        row(4, "lichess", "blitz", date(2026, 11, 1), 1647),  # nothing in October
        row(5, "chesscom", "rapid", date(2026, 12, 30), 1655, blunders=1),
        row(6, "chesscom", "rapid", date(2027, 2, 1), 1661),  # across a new year
    ]
    assert history.charts(reversed(rows)) == [
        Chart(
            speed="blitz",
            games=4,
            months=(
                ChartMonth("2026-09", {"lichess": 1612, "chesscom": 1490}, 3, 3),
                ChartMonth("2026-10", {}, 0, 0),
                ChartMonth("2026-11", {"lichess": 1647}, 1, 0),
            ),
        ),
        Chart(
            speed="rapid",
            games=2,
            months=(
                ChartMonth("2026-12", {"chesscom": 1655}, 1, 1),
                ChartMonth("2027-01", {}, 0, 0),
                ChartMonth("2027-02", {"chesscom": 1661}, 1, 0),
            ),
        ),
    ]
    assert history.charts([]) == []


def test_a_month_you_didnt_play_has_no_blunders_per_game() -> None:
    assert ChartMonth("2026-10", {}, 0, 0).blunders_per_game is None
    assert ChartMonth("2026-09", {"lichess": 1612}, 3, 3).blunders_per_game == 1
    assert ChartMonth("2026-09", {"lichess": 1612}, 4, 0).blunders_per_game == 0


def test_sites_and_speeds_keep_their_order() -> None:
    assert history.SITES == ("lichess", "chesscom")
    assert history.SPEEDS == ("bullet", "blitz", "rapid", "classical")
