"""Your rating over time, read from the games you imported (ROADMAP 17.2). Pure: no database,
no network. A synced game carries your rating in its headers, so the history needs nothing
but your Log.

Only Lichess and Chess.com games count, and only those with your rating, a date and a time
control: a rating on one site says nothing about the other, or about another speed.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Final, get_args

from blunderbook.core.models import GameRow, Speed, SyncSource

SITES: Final[tuple[SyncSource, ...]] = ("lichess", "chesscom")
SPEEDS: Final[tuple[Speed, ...]] = get_args(Speed)  # bullet, blitz, rapid, classical


@dataclass(frozen=True, slots=True)
class Played:
    """One of your games on a site, with the rating you had in it."""

    game_id: int
    source: SyncSource
    speed: Speed
    day: date
    rating: int
    blunders: int  # your entries in it judged a blunder


@dataclass(frozen=True, slots=True)
class Month:
    month: str  # "2026-11"
    rating: int  # in the month's last game
    games: int
    blunders: int

    @property
    def blunders_per_game(self) -> float:
        return self.blunders / self.games


@dataclass(frozen=True, slots=True)
class Line:
    """One site and speed, month by month, oldest first."""

    source: SyncSource
    speed: Speed
    months: tuple[Month, ...]


@dataclass(frozen=True, slots=True)
class Latest:
    """Your rating in the newest game of one site and speed."""

    source: SyncSource
    speed: Speed
    rating: int
    day: date
    game_id: int


@dataclass(frozen=True, slots=True)
class ChartMonth:
    """One month of one speed, both sites side by side."""

    month: str  # "2026-11"
    ratings: dict[SyncSource, int]  # your rating in each site's last game of the month
    games: int  # on both sites; 0 in a month you didn't play
    blunders: int

    @property
    def blunders_per_game(self) -> float | None:
        return self.blunders / self.games if self.games else None


@dataclass(frozen=True, slots=True)
class Chart:
    """One speed, for the tab's chart: every month from your first game to your last, the
    months you didn't play included, so time runs evenly along it."""

    speed: Speed
    games: int
    months: tuple[ChartMonth, ...]


def played(rows: Iterable[GameRow]) -> list[Played]:
    """The games that say what your rating was, oldest first."""
    found: list[Played] = []
    for row in rows:
        game = row.game
        rating = game.white_elo if game.my_color == "white" else game.black_elo
        if game.source == "lichess":
            source: SyncSource = "lichess"
        elif game.source == "chesscom":
            source = "chesscom"
        else:
            continue
        if rating is None or game.played_on is None or game.speed is None:
            continue
        found.append(Played(game.id, source, game.speed, game.played_on, rating, row.blunders))
    # The same day: in the order they were saved (a sync saves oldest first).
    return sorted(found, key=lambda g: (g.day, g.game_id))


def lines(rows: Iterable[GameRow]) -> list[Line]:
    """Your rating month by month, for each site and speed you have games in: sites in
    their fixed order, then bullet to classical."""
    by_line: dict[tuple[SyncSource, Speed], dict[str, list[Played]]] = {}
    for game in played(rows):
        months = by_line.setdefault((game.source, game.speed), {})
        months.setdefault(_key(game.day), []).append(game)
    found: list[Line] = []
    for source in SITES:
        for speed in SPEEDS:
            months = by_line.get((source, speed), {})
            if months:
                found.append(Line(source, speed, tuple(_month(m, months[m]) for m in months)))
    return found


def charts(rows: Iterable[GameRow]) -> list[Chart]:
    """Your rating over time for each speed you have games in, bullet to classical."""
    by_speed: dict[Speed, dict[str, list[Played]]] = {}
    for game in played(rows):
        by_speed.setdefault(game.speed, {}).setdefault(_key(game.day), []).append(game)
    found: list[Chart] = []
    for speed in SPEEDS:
        months = by_speed.get(speed)
        if not months:
            continue
        found.append(
            Chart(
                speed=speed,
                games=sum(len(games) for games in months.values()),
                months=tuple(
                    _chart_month(month, months.get(month, []))
                    for month in _span(min(months), max(months))
                ),
            )
        )
    return found


def latest(rows: Iterable[GameRow]) -> list[Latest]:
    """Your rating in the newest game of each site and speed, in the same order."""
    newest: dict[tuple[SyncSource, Speed], Played] = {}
    for game in played(rows):
        newest[(game.source, game.speed)] = game  # oldest first: the last one stays
    return [
        Latest(source, speed, g.rating, g.day, g.game_id)
        for source in SITES
        for speed in SPEEDS
        if (g := newest.get((source, speed))) is not None
    ]


def _month(month: str, games: list[Played]) -> Month:
    return Month(
        month=month,
        rating=games[-1].rating,
        games=len(games),
        blunders=sum(g.blunders for g in games),
    )


def _chart_month(month: str, games: list[Played]) -> ChartMonth:
    ratings: dict[SyncSource, int] = {}
    for game in games:  # oldest first: each site's last game of the month stays
        ratings[game.source] = game.rating
    return ChartMonth(
        month=month,
        ratings={site: ratings[site] for site in SITES if site in ratings},
        games=len(games),
        blunders=sum(g.blunders for g in games),
    )


def _key(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def _span(first: str, last: str) -> list[str]:
    """Every month from ``first`` to ``last`` ("2026-09"), both included."""
    year, month = int(first[:4]), int(first[5:])
    found: list[str] = []
    while (key := f"{year:04d}-{month:02d}") <= last:
        found.append(key)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return found
