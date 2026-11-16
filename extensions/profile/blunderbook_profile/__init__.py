"""The Profile extension (CLAUDE.md §15, ROADMAP M17): your ratings on Lichess and Chess.com,
kept in profile.db and never in your Log.

It goes online only when you ask: ``blunderbook profile refresh`` (and, from 17.3, the tab's
button). Each site's own adapter asks, through ``host.fetch_ratings``; nothing here makes a
request. Your rating over time is read from the games you imported
(:mod:`blunderbook_profile.history`) and needs no network at all.

17.2 has the database (:mod:`blunderbook_profile.store`), the history and two commands,
``refresh`` and ``show``. The tab comes next.
"""

import sqlite3
from contextlib import closing
from datetime import date, datetime
from enum import StrEnum
from importlib.resources import files
from typing import Annotated, Final, NoReturn

import typer

from blunderbook import ext, host
from blunderbook.core.models import Rating, RatingKind, SyncSource
from blunderbook_profile import history, store

commands = typer.Typer(no_args_is_help=True)

DOT = " \N{MIDDLE DOT} "
SITE_NAMES: Final[dict[SyncSource, str]] = {"lichess": "Lichess", "chesscom": "Chess.com"}
KIND_NAMES: Final[dict[RatingKind, str]] = {
    "bullet": "Bullet",
    "blitz": "Blitz",
    "rapid": "Rapid",
    "classical": "Classical",
    "daily": "Daily",
    "puzzle": "Puzzles",
}
NO_ACCOUNTS: Final = (
    "No usernames yet: set yours under [lichess] or [chesscom] in config.toml,\n"
    "or run blunderbook init."
)


class _Site(StrEnum):
    all = "all"
    lichess = "lichess"
    chesscom = "chesscom"


@commands.command("refresh")
def refresh(
    site: Annotated[
        _Site,
        typer.Argument(help="lichess, chesscom, or all: each site with a username in config.toml."),
    ] = _Site.all,
) -> None:
    """Ask Lichess and Chess.com for your ratings now, and keep them."""
    try:
        accounts = host.accounts()
    except host.HostError as exc:
        _fail(str(exc))
    wanted: list[SyncSource] = list(history.SITES) if site is _Site.all else [_source(site)]
    chosen = [name for name in wanted if accounts[name]]
    if site is not _Site.all and not chosen:
        _fail(f"Set your {SITE_NAMES[wanted[0]]} username under [{wanted[0]}] in config.toml.")
    if not chosen:
        _fail(NO_ACCOUNTS)
    try:
        done = host.daily_backup()
    except host.HostError as exc:
        _fail(str(exc))
    for taken in done.taken:
        typer.echo(f"Daily backup: {taken}")
    for problem in done.problems:
        typer.echo(f"Warning: {problem}", err=True)

    failed = False
    with closing(_open()) as conn:
        for name in chosen:
            try:
                answer = host.fetch_ratings(name)
            except host.HostError as exc:
                failed = True
                typer.echo(f"{exc}\nThe {SITE_NAMES[name]} ratings you had are kept.", err=True)
                continue
            fetch = store.save(conn, answer)
            _print(fetch, store.before(conn, fetch))
    if failed:
        raise typer.Exit(1)


@commands.command("show")
def show() -> None:
    """Your ratings as they were last fetched, and your rating in your newest games. Asks
    no site."""
    try:
        accounts = host.accounts()
    except host.HostError as exc:
        _fail(str(exc))
    with closing(_open()) as conn:
        kept = {name: store.latest(conn, name) for name in history.SITES}
        earlier = {name: store.before(conn, f) for name, f in kept.items() if f is not None}
    for name in history.SITES:
        fetch = kept[name]
        if fetch is not None:
            _print(fetch, earlier[name])
        elif accounts[name]:
            typer.echo(
                f"{SITE_NAMES[name]} ({accounts[name]}): not fetched yet. "
                f"Run: blunderbook profile refresh {name}"
            )
        else:
            typer.echo(f"{SITE_NAMES[name]}: no username under [{name}] in config.toml.")
    _from_games()


def _print(fetch: store.Fetch, earlier: store.Fetch | None) -> None:
    """One site: a line for it, then a line per kind of play."""
    typer.echo(
        f"{SITE_NAMES[fetch.source]} ({fetch.username}){DOT}fetched {_when(fetch.fetched_at)}"
    )
    if not fetch.ratings:
        typer.echo("  No ratings yet.")
        return
    moved = store.changes(fetch, earlier)
    for rating in fetch.ratings:
        parts = [_now(rating)]
        if earlier is not None and moved.get(rating.kind):
            parts.append(f"{moved[rating.kind]:+d} since {_day(earlier.day)}")
        if rating.best is not None:
            parts.append(f"best {rating.best}")
        if None not in (rating.wins, rating.losses, rating.draws):
            parts.append(f"{rating.wins} W / {rating.losses} L / {rating.draws} D")
        typer.echo(f"  {kind_name(fetch.source, rating.kind):<15}{DOT.join(parts)}")


def _now(rating: Rating) -> str:
    """ "1647", "1702?" while it's provisional, and a dash when the site gives no current one."""
    if rating.rating is None:
        return "\N{EM DASH}"
    return f"{rating.rating}{'?' if rating.provisional else ''}"


def _from_games() -> None:
    """Your rating in your newest game of each site and speed, from your Log."""
    try:
        with host.read_log() as log:
            newest = history.latest(log.games())
    except host.StorageError:
        return  # no Log yet: nothing to add
    if not newest:
        return
    typer.echo("From your games:")
    for found in newest:
        label = f"{SITE_NAMES[found.source]} {KIND_NAMES[found.speed].lower()}"
        typer.echo(f"  {label:<20}{found.rating}{DOT}{_day(found.day)}")


def kind_name(source: SyncSource, kind: RatingKind) -> str:
    """What a kind of play is called. Lichess calls daily chess correspondence."""
    if source == "lichess" and kind == "daily":
        return "Correspondence"
    return KIND_NAMES[kind]


def _source(site: _Site) -> SyncSource:
    return "lichess" if site is _Site.lichess else "chesscom"


def _open() -> sqlite3.Connection:
    try:
        return host.open_db(extension)
    except (host.HostError, host.StorageError) as exc:
        _fail(f"Can't use the profile database.\n{exc}")


def _when(moment: datetime) -> str:
    """A UTC time as your local "16 Nov 2026 09:12"."""
    local = moment.astimezone()
    return f"{local.day} {local:%b %Y %H:%M}"


def _day(day: date) -> str:
    return f"{day.day} {day:%b %Y}"


def _fail(message: str) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(1)


extension = ext.Extension(
    name="profile",
    title="Profile",
    host_api=ext.HOST_API,
    migrations=files(__name__) / "migrations",
    cli=commands,
)
