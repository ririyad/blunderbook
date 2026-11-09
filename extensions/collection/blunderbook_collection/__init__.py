"""The Collection extension (CLAUDE.md §15, ROADMAP M12): anyone's games, analysed by the same
Stockfish and the same rules as your own, kept in collection.db and never in your Log.

12.1 has the database, ``blunderbook collection import FILE --into NAME`` (pass 1 for every
position of every game, :mod:`blunderbook_collection.collect`) and ``blunderbook collection
list``. Stats, the tab and import on the page come next.
"""

import sqlite3
import sys
from collections.abc import Callable
from contextlib import closing
from importlib.resources import files
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from blunderbook import ext, host
from blunderbook.core import engine, pgn
from blunderbook_collection import collect, games, store

commands = typer.Typer(no_args_is_help=True)

DOT = " \N{MIDDLE DOT} "


@commands.command("import")
def import_(
    path: Annotated[Path, typer.Argument(help="A PGN file with one or more games.")],
    into: Annotated[
        str, typer.Option("--into", help="The collection to add them to; made if it's new.")
    ],
    depth: Annotated[
        int | None,
        typer.Option(min=1, help="Search depth per position. Default: engine_depth."),
    ] = None,
) -> None:
    """Add the games of a PGN file to a collection, analysing each with Stockfish."""
    try:
        name = games.collection_name(into)
    except games.BadName as exc:
        _fail(str(exc))
    try:
        data = path.read_bytes()
    except OSError as exc:
        _fail(f"Can't read {path}: {exc.strerror or exc}")
    decoded = pgn.decode(data)
    if decoded.encoding == "cp1252":
        typer.echo("Read as Windows-1252 (the file isn't UTF-8).")
    try:
        cfg = host.settings()
        done = host.daily_backup()
    except host.HostError as exc:
        _fail(str(exc))
    for taken in done.taken:
        typer.echo(f"Daily backup: {taken}")
    for problem in done.problems:
        typer.echo(f"Warning: {problem}", err=True)

    with closing(_open()) as conn:
        queued = collect.queue(conn, decoded.text, name)
        if not queued:
            _fail(f"No games found in {path}.")
        found = store.find(conn, name)
        shown = found.name if found else name
        result = collect.add(
            conn,
            shown,
            queued,
            host.engine,
            depth=depth or cfg.engine_depth,
            progress_for=lambda q, k, n: _Progress(f"Game {q.number} ({k} of {n})"),
            on_engine=_engine_line(depth or cfg.engine_depth),
        )
        _report(result, shown)
        count = store.find(conn, shown)
    if count is not None:
        typer.echo(f"{count.name}: {count.games} {_s(count.games, 'game')}.")
    if result.stopped:
        typer.echo("Stopped. The games added so far are kept: import the file again to finish.")
        raise typer.Exit(130)
    if result.error is not None:
        _fail(
            f"Analysis stopped: {result.error}\n"
            "Import the file again to analyse the rest. Games already added are skipped."
        )


@commands.command("list")
def list_(
    name: Annotated[
        str | None, typer.Argument(help="A collection: list its games instead.")
    ] = None,
) -> None:
    """List your collections, or the games in one."""
    with closing(_open()) as conn:
        if name is None:
            rows = store.collections(conn)
            if not rows:
                typer.echo(
                    "No collections yet. Add games with: "
                    "blunderbook collection import FILE --into NAME"
                )
            for c in rows:
                typer.echo(f"{c.name}{DOT}{c.games} {_s(c.games, 'game')}")
            return
        found = store.find(conn, " ".join(name.split()))
        if found is None:
            _fail(f"No collection called {name}.")
        typer.echo(f"{found.name}{DOT}{found.games} {_s(found.games, 'game')}")
        for g in store.games(conn, found.id):
            typer.echo(_game_line(g))


# ---------------------------------------------------------------- helpers


def _open() -> sqlite3.Connection:
    try:
        return host.open_db(extension)
    except (host.HostError, host.StorageError) as exc:
        _fail(f"Can't use the collection's database.\n{exc}")


def _engine_line(depth: int) -> Callable[[engine.Engine], None]:
    def show(sf: engine.Engine) -> None:
        typer.echo(f"Analysing with {sf.name} at depth {depth}.")
        note = engine.version_note(sf.info)
        if note:
            typer.echo(f"Warning: {note}", err=True)

    return show


def _report(result: collect.Result, name: str) -> None:
    counts = {"added": 0, "skipped": 0, "errors": 0, "left": 0}
    for q in result.queue:
        where = f"Game {q.number}{DOT}{q.players}"
        if q.number in result.added:
            counts["added"] += 1
            how = "added (already analysed)" if q.status == "known" else "added"
            typer.echo(f"{where}{DOT}{how}")
        elif q.status in ("member", "duplicate"):
            counts["skipped"] += 1
            typer.echo(f"{where}{DOT}{q.reason}")
        elif q.status == "error":
            counts["errors"] += 1
            typer.echo(f"{where}{DOT}{q.reason}")
        else:
            counts["left"] += 1
            typer.echo(f"{where}{DOT}not analysed")
        for warning in q.warnings:
            typer.echo(f"  {warning}")
    if result.created:
        typer.echo(f"New collection: {name}.")
    n = len(result.queue)
    parts = [f"{n} {_s(n, 'game')} read", f"{counts['added']} added"]
    if counts["skipped"]:
        parts.append(f"{counts['skipped']} skipped")
    if counts["errors"]:
        parts.append(f"{counts['errors']} {_s(counts['errors'], 'error')}")
    if counts["left"]:
        parts.append(f"{counts['left']} not analysed")
    typer.echo(DOT.join(parts))


def _game_line(g: store.GameRow) -> str:
    who = f"{g.white or '?'} vs {g.black or '?'}"
    moves = (g.plies + 1) // 2
    parts = [who, g.result or "*"]
    when = DOT.join(x for x in (g.event, g.date) if x)
    if when:
        parts.append(when)
    if g.eco or g.opening:
        parts.append(" ".join(x for x in (g.eco, g.opening) if x))
    parts.append(f"{moves} {_s(moves, 'move')}")
    return f"  #{g.id} " + DOT.join(parts)


class _Progress:
    """Positions done / total, redrawn on one line when stderr is a terminal."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.live = sys.stderr.isatty()

    def __call__(self, done: int, total: int) -> None:
        if self.live:
            end = "\r\033[K" if done == total else ""
            sys.stderr.write(f"\r{self.label}: {100 * done // total}%{end}")
            sys.stderr.flush()


def _fail(message: str) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(1)


def _s(n: int, one: str, many: str | None = None) -> str:
    return one if n == 1 else (many or one + "s")


extension = ext.Extension(
    name="collection",
    title="Collection",
    host_api=ext.HOST_API,
    migrations=files(__name__) / "migrations",
    cli=commands,
)
