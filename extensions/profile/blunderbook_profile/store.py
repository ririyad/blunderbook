"""profile.db (ROADMAP 17.2, ``migrations/0001_ratings.sql``): your ratings as each site
reported them, one fetch per site per day. All of the Profile's SQL is here, with every value
a parameter."""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import cast

from blunderbook import host
from blunderbook.core.models import RATING_KINDS, Rating, RatingKind, SiteRatings, SyncSource


@dataclass(frozen=True, slots=True)
class Fetch:
    """What a site said about your ratings, and when you asked."""

    source: SyncSource
    username: str
    day: date  # local
    fetched_at: datetime  # UTC
    ratings: tuple[Rating, ...]  # in RATING_KINDS order


def save(conn: sqlite3.Connection, site: SiteRatings, *, at: datetime | None = None) -> Fetch:
    """Keep a site's answer. Asking twice on one day keeps the later answer only."""
    moment = (at or datetime.now(UTC)).astimezone(UTC)
    day = moment.astimezone().date()  # the day as you see it
    with host.transaction(conn):
        conn.execute(
            "DELETE FROM fetches WHERE source = ? AND day = ?", (site.source, day.isoformat())
        )
        cursor = conn.execute(
            "INSERT INTO fetches (source, username, day, fetched_at) VALUES (?, ?, ?, ?)",
            (site.source, site.username, day.isoformat(), moment.isoformat()),
        )
        conn.executemany(
            "INSERT INTO ratings (fetch_id, kind, rating, provisional, games, best, best_at,"
            " wins, losses, draws) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    cursor.lastrowid,
                    r.kind,
                    r.rating,
                    int(r.provisional),
                    r.games,
                    r.best,
                    None if r.best_at is None else r.best_at.astimezone(UTC).isoformat(),
                    r.wins,
                    r.losses,
                    r.draws,
                )
                for r in site.ratings
            ],
        )
    return Fetch(site.source, site.username, day, moment, _ordered(site.ratings))


def latest(conn: sqlite3.Connection, source: SyncSource) -> Fetch | None:
    """The newest answer kept for a site."""
    row = conn.execute(
        "SELECT id, source, username, day, fetched_at FROM fetches WHERE source = ?"
        " ORDER BY day DESC LIMIT 1",
        (source,),
    ).fetchone()
    return None if row is None else _fetch(conn, row)


def before(conn: sqlite3.Connection, fetch: Fetch) -> Fetch | None:
    """The answer kept before ``fetch``, for the same account: what "since" compares with.
    None when there's none, or the one before was about another account."""
    row = conn.execute(
        "SELECT id, source, username, day, fetched_at FROM fetches"
        " WHERE source = ? AND day < ? ORDER BY day DESC LIMIT 1",
        (fetch.source, fetch.day.isoformat()),
    ).fetchone()
    if row is None:
        return None
    earlier = _fetch(conn, row)
    same = earlier.username.casefold() == fetch.username.casefold()
    return earlier if same else None


def changes(now: Fetch, earlier: Fetch | None) -> dict[RatingKind, int]:
    """How far each rating moved since ``earlier``: only the kinds both have a rating in."""
    if earlier is None:
        return {}
    was = {r.kind: r.rating for r in earlier.ratings}
    return {
        r.kind: r.rating - old
        for r in now.ratings
        if r.rating is not None and (old := was.get(r.kind)) is not None
    }


def _fetch(conn: sqlite3.Connection, row: sqlite3.Row) -> Fetch:
    fetch_id, source, username, day, fetched_at = row
    found = conn.execute(
        "SELECT kind, rating, provisional, games, best, best_at, wins, losses, draws"
        " FROM ratings WHERE fetch_id = ?",
        (fetch_id,),
    ).fetchall()
    ratings = [
        Rating(
            kind=cast(RatingKind, kind),
            rating=rating,
            provisional=bool(provisional),
            games=games,
            best=best,
            best_at=None if best_at is None else datetime.fromisoformat(best_at),
            wins=wins,
            losses=losses,
            draws=draws,
        )
        for kind, rating, provisional, games, best, best_at, wins, losses, draws in found
    ]
    return Fetch(
        source=cast(SyncSource, source),
        username=username,
        day=date.fromisoformat(day),
        fetched_at=datetime.fromisoformat(fetched_at),
        ratings=_ordered(ratings),
    )


def _ordered(ratings: list[Rating] | tuple[Rating, ...]) -> tuple[Rating, ...]:
    return tuple(sorted(ratings, key=lambda r: RATING_KINDS.index(r.kind)))
