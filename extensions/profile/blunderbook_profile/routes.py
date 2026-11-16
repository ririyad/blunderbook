"""The Profile's routes, mounted at ``/api/ext/profile`` (ROADMAP 17.3): your ratings as they
were last fetched, your rating in your newest games, and the "Refresh ratings" button.

Only the refresh goes online, and only the Blunderbook page may call it
(``host.same_origin``). It asks through ``host.fetch_ratings``: each site's own adapter makes
the requests. Opening the tab never asks a site.
"""

import sqlite3
import threading
from datetime import date, datetime
from typing import Final, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from blunderbook import host
from blunderbook.core.models import RatingKind, Speed, SyncSource
from blunderbook_profile import history, store
from blunderbook_profile.labels import KIND_NAMES, NO_ACCOUNTS, SITE_NAMES, kind_name

router = APIRouter()

# One refresh at a time: a second press, or another window, waits for the first.
_refreshing: Final = threading.Lock()
BUSY: Final = "Your ratings are being fetched already."


class RatingOut(BaseModel):
    kind: RatingKind
    label: str  # "Blitz", "Correspondence"
    rating: int | None  # None: the site only gives your highest (Chess.com's puzzles)
    provisional: bool
    change: int | None  # since the fetch before; None when there's nothing to compare
    games: int | None
    best: int | None
    best_at: datetime | None
    wins: int | None
    losses: int | None
    draws: int | None


class FetchOut(BaseModel):
    username: str  # the account that was asked about
    fetched_at: datetime
    since: date | None  # the day `change` compares with
    ratings: list[RatingOut]


class GameRatingOut(BaseModel):
    speed: Speed
    label: str
    rating: int
    played_on: date
    game_id: int  # for a link to #games/<id>


class SiteOut(BaseModel):
    source: SyncSource
    title: str  # "Lichess"
    username: str  # from config.toml; "" when it isn't set
    fetched: FetchOut | None  # None: never fetched
    from_games: list[GameRatingOut]  # your newest game of each speed on this site
    problem: str | None = None  # why the refresh just now didn't work for this site


class ProfileOut(BaseModel):
    sites: list[SiteOut]
    warnings: list[str] = []  # a daily backup that didn't work


class RefreshIn(BaseModel):
    site: Literal["all", "lichess", "chesscom"] = "all"


@router.get("")
def profile(db: host.ExtDb, log: host.Log) -> ProfileOut:
    """What's kept and what your games say. Asks no site."""
    return _profile(db, log, _accounts())


@router.post("/refresh", dependencies=[Depends(host.same_origin)])
def refresh(body: RefreshIn, db: host.ExtDb, log: host.Log) -> ProfileOut:
    """Ask the sites for your ratings now, keep the answers, and say what's kept. A site
    that can't be asked has a ``problem``; the other is still asked and kept."""
    accounts = _accounts()
    wanted = history.SITES if body.site == "all" else (body.site,)
    chosen = [name for name in wanted if accounts[name]]
    if not chosen:
        if body.site == "all":
            raise HTTPException(409, NO_ACCOUNTS)
        raise HTTPException(
            409, f"Set your {SITE_NAMES[wanted[0]]} username under [{wanted[0]}] in config.toml."
        )
    if not _refreshing.acquire(blocking=False):
        raise HTTPException(409, BUSY)
    try:
        try:
            warnings = list(host.daily_backup().problems)
        except host.HostError as exc:
            raise HTTPException(503, str(exc)) from None
        problems: dict[SyncSource, str] = {}
        for name in chosen:
            try:
                answer = host.fetch_ratings(name)
            except host.HostError as exc:
                problems[name] = str(exc)
                continue
            store.save(db, answer)
    finally:
        _refreshing.release()
    found = _profile(db, log, accounts)
    for site in found.sites:
        site.problem = problems.get(site.source)
    found.warnings = warnings
    return found


def _accounts() -> dict[SyncSource, str]:
    try:
        return host.accounts()
    except host.HostError as exc:
        raise HTTPException(503, str(exc)) from None


def _profile(
    db: sqlite3.Connection, log: host.LogReader, accounts: dict[SyncSource, str]
) -> ProfileOut:
    newest = history.latest(log.games())
    return ProfileOut(
        sites=[
            SiteOut(
                source=name,
                title=SITE_NAMES[name],
                username=accounts[name],
                fetched=_fetched(db, name),
                from_games=[
                    GameRatingOut(
                        speed=g.speed,
                        label=KIND_NAMES[g.speed],
                        rating=g.rating,
                        played_on=g.day,
                        game_id=g.game_id,
                    )
                    for g in newest
                    if g.source == name
                ],
            )
            for name in history.SITES
        ]
    )


def _fetched(db: sqlite3.Connection, name: SyncSource) -> FetchOut | None:
    fetch = store.latest(db, name)
    if fetch is None:
        return None
    earlier = store.before(db, fetch)
    moved = store.changes(fetch, earlier)
    return FetchOut(
        username=fetch.username,
        fetched_at=fetch.fetched_at,
        since=None if earlier is None else earlier.day,
        ratings=[
            RatingOut(
                kind=r.kind,
                label=kind_name(name, r.kind),
                rating=r.rating,
                provisional=r.provisional,
                change=moved.get(r.kind),
                games=r.games,
                best=r.best,
                best_at=r.best_at,
                wins=r.wins,
                losses=r.losses,
                draws=r.draws,
            )
            for r in fetch.ratings
        ],
    )
