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
        months.setdefault(f"{game.day.year:04d}-{game.day.month:02d}", []).append(game)
    found: list[Line] = []
    for source in SITES:
        for speed in SPEEDS:
            months = by_line.get((source, speed), {})
            if months:
                found.append(Line(source, speed, tuple(_month(m, months[m]) for m in months)))
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
