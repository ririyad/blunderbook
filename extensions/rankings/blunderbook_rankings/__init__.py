"""The Rankings extension (CLAUDE.md §15, ROADMAP M16): the FIDE, Lichess and Chess.com top
lists, kept in rankings.db and never in your Log.

It goes online only when you ask: ``blunderbook rankings update`` (and, from 16.3, the
tab's Update button). Nothing checks or downloads on its own.

16.1 has the database, FIDE's lists (:mod:`blunderbook_rankings.fide`) and two commands,
``update`` and ``status``; 16.2 adds the Lichess and Chess.com leaderboards.
"""

import sqlite3
import sys
from contextlib import closing
from datetime import date, datetime
from enum import StrEnum
from importlib.resources import files
from typing import Annotated, NoReturn

import typer

from blunderbook import ext, host
from blunderbook_rankings import chesscom, fide, lichess, net, store, update

commands = typer.Typer(no_args_is_help=True)

DOT = " \N{MIDDLE DOT} "
FIDE_SIZE = "about 35 MB"
STALE = "A newer FIDE list is usually out after the 1st: blunderbook rankings update fide"


class _Source(StrEnum):
    all = "all"
    fide = "fide"
    lichess = "lichess"
    chesscom = "chesscom"


@commands.command("update")
def update_(
    source: Annotated[
        _Source, typer.Argument(help="Which lists to download: fide, lichess, chesscom or all.")
    ] = _Source.all,
) -> None:
    """Download the latest lists. Only what changed since last time is downloaded."""
    try:
        contact = host.settings().chesscom_contact
        done = host.daily_backup()
    except host.HostError as exc:
        _fail(str(exc))
    for taken in done.taken:
        typer.echo(f"Daily backup: {taken}")
    for problem in done.problems:
        typer.echo(f"Warning: {problem}", err=True)

    wanted = update.SOURCES if source is _Source.all else (source.value,)
    failed = False
    progress = _Progress()
    with closing(_open()) as conn, net.client() as http:
        for name in wanted:
            try:
                outcome = update.one(
                    conn,
                    http,
                    name,
                    progress=progress,
                    stop=lambda: False,
                    wait=_wait,
                    today=_today(),
                    contact=contact,
                )
            except KeyboardInterrupt, net.Stopped:
                progress.clear()
                typer.echo(f"Stopped. The {update.NAMES[name]} lists weren't changed.", err=True)
                raise typer.Exit(130) from None
            progress.clear()
            if outcome.error is None:
                typer.echo(outcome.message)
            else:
                failed = True
                typer.echo(
                    f"{outcome.message}\nThe {update.NAMES[name]} lists you had are kept.",
                    err=True,
                )
    if failed:
        raise typer.Exit(1)


@commands.command("status")
def status() -> None:
    """When each list was last downloaded, and how many players are kept."""
    with closing(_open()) as conn:
        rows = {name: store.source(conn, name) for name in update.SOURCES}
        fide_counts = store.fide_counts(conn)
        boards = {name: store.board_counts(conn, name) for name in ("lichess", "chesscom")}

    fide_row = rows["fide"]
    if fide_row is None or fide_row.list_month is None:
        typer.echo(
            f"FIDE: not downloaded yet. Run: blunderbook rankings update fide ({FIDE_SIZE})."
        )
    else:
        kept = DOT.join(f"{c.speed} {c.players:,}" for c in fide_counts)
        line = f"FIDE: {fide.month_label(fide_row.list_month)} lists"
        if kept:
            line += f"{DOT}{kept} players kept"
        typer.echo(line + _downloaded(fide_row))
        if update.stale(fide_row.list_month, _today()):
            typer.echo(STALE)
    _error(fide_row)

    for name, top in (("lichess", lichess.TOP), ("chesscom", chesscom.TOP)):
        row = rows[name]
        title = update.NAMES[name]
        if not boards[name]:
            typer.echo(f"{title}: not downloaded yet. Run: blunderbook rankings update {name}")
        else:
            count = len(boards[name])
            noun = "leaderboard" if count == 1 else "leaderboards"
            typer.echo(f"{title}: {count} {noun}, top {top}" + _downloaded(row))
        _error(row)


def _downloaded(row: store.SourceRow | None) -> str:
    if row is None or not row.fetched_at:
        return ""
    return f"{DOT}downloaded {_when(row.fetched_at)}"


def _error(row: store.SourceRow | None) -> None:
    if row is not None and row.last_error:
        when = _when(row.checked_at) if row.checked_at else "last time"
        title = update.NAMES[row.source]
        typer.echo(f"{title}: the update on {when} failed: {row.last_error}")


def _today() -> date:
    return date.today()


def _open() -> sqlite3.Connection:
    try:
        return host.open_db(extension)
    except (host.HostError, host.StorageError) as exc:
        _fail(f"Can't use the rankings database.\n{exc}")


def _wait(seconds: float) -> None:
    typer.echo(f"The server asked to slow down: waiting {seconds:.0f} s.", err=True)
    net.sleeper(lambda: False)(seconds)


def _when(timestamp: str) -> str:
    """An ISO UTC time as your local "12 Nov 2026 14:03"."""
    try:
        local = datetime.fromisoformat(timestamp).astimezone()
    except ValueError:
        return timestamp
    return f"{local.day} {local:%b %Y %H:%M}"


class _Progress:
    """What it's doing and its percentage, redrawn on one line when stderr is a terminal."""

    def __init__(self) -> None:
        self.live = sys.stderr.isatty()
        self.shown = False

    def __call__(self, label: str, done: float) -> None:
        if self.live:
            sys.stderr.write(f"\r\033[K{label}: {int(100 * done)}%")
            sys.stderr.flush()
            self.shown = True

    def clear(self) -> None:
        if self.shown:
            sys.stderr.write("\r\033[K")
            sys.stderr.flush()
            self.shown = False


def _fail(message: str) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(1)


extension = ext.Extension(
    name="rankings",
    title="Rankings",
    host_api=ext.HOST_API,
    migrations=files(__name__) / "migrations",
    cli=commands,
)
