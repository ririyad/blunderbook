"""The Rankings tab's routes (ROADMAP 16.3), at ``/api/ext/rankings``.

Every route reads rankings.db only, except ``POST /update``, the tab's Update button: it
goes online, so only the Blunderbook page may call it (``host.same_origin``).
"""

import sqlite3
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated, Final, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict

from blunderbook import host
from blunderbook_rankings import chesscom, fide, jobs, lichess, store, update
from blunderbook_rankings.jobs import JobStatus


def _open_db() -> sqlite3.Connection:
    """rankings.db, for the update's thread."""
    from blunderbook_rankings import extension  # here: the package imports this module

    return host.open_db(extension)


def _today() -> date:
    return date.today()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """One update at a time, kept with the app; stopping ``serve`` stops it."""
    running = jobs.Jobs(_open_db, lambda: _today())
    app.state.rankings_jobs = running
    try:
        yield
    finally:
        await run_in_threadpool(running.stop)


router = APIRouter(lifespan=lifespan)

ABOUT: Final = {
    "fide": "https://ratings.fide.com/",
    "lichess": "https://lichess.org/player",
    "chesscom": "https://www.chess.com/leaderboard",
}
FIDE_PROFILE: Final = "https://ratings.fide.com/profile/{}"
LIST_NAMES: Final = {"open": "Open", "women": "Women", "juniors": "Juniors", "girls": "Girls"}
SPEED_NAMES: Final = {"standard": "Standard", "rapid": "Rapid", "blitz": "Blitz"}
SIZES: Final = {"fide": "about 35 MB", "lichess": "five small lists", "chesscom": "one small list"}

Source = Literal["fide", "lichess", "chesscom"]
LichessBoard = Literal["bullet", "blitz", "rapid", "classical", "ultraBullet"]
ChesscomBoard = Literal["live_rapid", "live_blitz", "live_bullet", "daily"]


# ---------------------------------------------------------------- status


class SourceOut(BaseModel):
    source: Source
    title: str  # "FIDE"
    list_label: str | None  # FIDE: "November 2026"
    fetched_at: str | None  # when it last changed (ISO UTC); None before the first update
    checked_at: str | None
    last_error: str | None
    stale: bool  # FIDE: from an earlier month, so a newer list is probably out
    size: str  # what Update downloads: "about 35 MB"
    about_url: str  # the source's own page, for the credit line


class StatusOut(BaseModel):
    sources: list[SourceOut]
    job_id: str | None  # an update that's running, to follow it after a reload


@router.get("/status")
def get_status(db: host.ExtDb, request: Request) -> StatusOut:
    out = []
    for name in update.SOURCES:
        row = store.source(db, name)
        month = row.list_month if row else None
        out.append(
            SourceOut(
                source=name,  # type: ignore[arg-type]
                title=update.NAMES[name],
                list_label=fide.month_label(month) if month else None,
                fetched_at=row.fetched_at if row else None,
                checked_at=row.checked_at if row else None,
                last_error=row.last_error if row else None,
                stale=name == "fide" and update.stale(month, _today()),
                size=SIZES[name],
                about_url=ABOUT[name],
            )
        )
    running = _jobs(request).running()
    return StatusOut(sources=out, job_id=running.id if running else None)


# ---------------------------------------------------------------- FIDE


class FidePlayerOut(BaseModel):
    rank: int
    fide_id: int
    name: str
    title: str | None
    fed: str | None
    rating: int
    games: int | None
    born: int | None
    url: str  # the player's FIDE page


class Option(BaseModel):
    key: str
    name: str


class FideOut(BaseModel):
    month: str | None  # "2026-11"; None before the first update
    month_label: str | None
    speed: str
    category: str  # the list: open | women | juniors | girls
    fed: str | None
    speeds: list[Option]
    lists: list[Option]
    federations: list[str]  # with players kept, for the filter
    players: list[FidePlayerOut]


@router.get("/fide")
def get_fide(
    db: host.ExtDb,
    speed: fide.Speed = "standard",
    list_: Annotated[fide.Category, Query(alias="list")] = "open",
    fed: Annotated[str | None, Query(pattern="^[A-Z]{3}$")] = None,
) -> FideOut:
    """One FIDE list as kept: the world's top 100, or a federation's top 50."""
    month = store.fide_month(db, speed)
    limit = fide.FED_TOP if fed else fide.WORLD_TOP
    players: list[FidePlayerOut] = []
    federations: list[str] = []
    if month is not None:
        federations = store.federations(db, month, speed)
        rows = store.fide_top(db, month, speed, list_, fed, limit)
        for rank, p in enumerate(rows, start=1):
            players.append(
                FidePlayerOut(
                    rank=rank,
                    fide_id=p.fide_id,
                    name=p.name,
                    title=p.title,
                    fed=p.fed,
                    rating=p.rating,
                    games=p.games,
                    born=p.born,
                    url=FIDE_PROFILE.format(p.fide_id),
                )
            )
    return FideOut(
        month=month,
        month_label=fide.month_label(month) if month else None,
        speed=speed,
        category=list_,
        fed=fed,
        speeds=[Option(key=k, name=v) for k, v in SPEED_NAMES.items()],
        lists=[Option(key=k, name=v) for k, v in LIST_NAMES.items()],
        federations=federations,
        players=players,
    )


# ---------------------------------------------------------------- Lichess and Chess.com


class SitePlayerOut(BaseModel):
    rank: int
    username: str
    title: str | None
    rating: int  # Chess.com: its score
    progress: int | None  # the site's own recent change; None when it doesn't say
    url: str  # the player's profile


class BoardOut(BaseModel):
    source: Source
    board: str
    boards: list[Option]
    fetched_at: str | None
    players: list[SitePlayerOut]


@router.get("/lichess")
def get_lichess(db: host.ExtDb, board: LichessBoard = "blitz") -> BoardOut:
    return _board(db, "lichess", board, lichess.NAMES, lichess.profile)


@router.get("/chesscom")
def get_chesscom(db: host.ExtDb, board: ChesscomBoard = "live_blitz") -> BoardOut:
    return _board(db, "chesscom", board, chesscom.NAMES, chesscom.profile)


def _board(
    db: sqlite3.Connection,
    source: Source,
    board: str,
    names: dict[str, str],
    profile: Callable[[str], str],
) -> BoardOut:
    row = store.source(db, source)
    return BoardOut(
        source=source,
        board=board,
        boards=[Option(key=k, name=v) for k, v in names.items()],
        fetched_at=row.fetched_at if row else None,
        players=[
            SitePlayerOut(
                rank=p.rank,
                username=p.username,
                title=p.title,
                rating=p.rating,
                progress=p.progress,
                url=profile(p.username),
            )
            for p in store.board(db, source, board)
        ],
    )


# ---------------------------------------------------------------- the Update button


class UpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["fide", "lichess", "chesscom", "all"]


class UpdateStarted(BaseModel):
    job_id: str


class OutcomeOut(BaseModel):
    source: Source
    title: str
    changed: bool
    message: str  # "FIDE November 2026: standard, rapid and blitz lists updated."
    error: str | None  # the lists are as they were


class UpdateJobOut(BaseModel):
    id: str
    status: JobStatus
    percent: int
    label: str  # what it's doing
    outcomes: list[OutcomeOut]  # one per source finished
    notes: list[str]  # the daily backup
    error: str | None  # why it stopped


def _jobs(request: Request) -> jobs.Jobs:
    running: jobs.Jobs = request.app.state.rankings_jobs
    return running


@router.post("/update", status_code=202, dependencies=[Depends(host.same_origin)])
def start_update(body: UpdateIn, request: Request) -> UpdateStarted:
    """Start downloading the latest lists of ``source``, in the background. Only what
    changed is downloaded."""
    try:
        job = _jobs(request).start(body.source)
    except jobs.Busy as exc:
        raise HTTPException(409, str(exc)) from None
    return UpdateStarted(job_id=job.id)


@router.get("/update/{job_id}")
def update_status(job_id: str, request: Request) -> UpdateJobOut:
    job = _jobs(request).get(job_id)
    if job is None:
        raise HTTPException(404, "That update isn't known: Blunderbook was restarted since.")
    v = job.view()
    return UpdateJobOut(
        id=v.id,
        status=v.status,
        percent=v.percent,
        label=v.label,
        outcomes=[
            OutcomeOut(
                source=o.source,  # type: ignore[arg-type]
                title=update.NAMES[o.source],
                changed=o.changed,
                message=o.message,
                error=o.error,
            )
            for o in v.outcomes
        ],
        notes=list(v.notes),
        error=v.error,
    )
