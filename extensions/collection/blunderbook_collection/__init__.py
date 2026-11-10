"""The Collection extension (CLAUDE.md §15, ROADMAP M12): anyone's games, analysed by the same
Stockfish and the same rules as your own, kept in collection.db and never in your Log.

12.1 has the database, ``blunderbook collection import FILE --into NAME`` (pass 1 for every
position of every game, :mod:`blunderbook_collection.collect`) and ``blunderbook collection
list``. 12.2 has ``stats`` and ``players`` (:mod:`blunderbook_collection.stats`). 12.3 has
the tab: its routes in :mod:`blunderbook_collection.routes` and its page in ``web/``.
Importing on the page comes next.
"""

import sqlite3
import sys
from collections.abc import Callable
from contextlib import closing
from enum import StrEnum
from importlib.resources import files
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from blunderbook import ext, host
from blunderbook.core import engine, pgn
from blunderbook.core.models import Thresholds
from blunderbook_collection import collect, games, stats, store
from blunderbook_collection.routes import router

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


class _Color(StrEnum):
    white = "white"
    black = "black"


class _Result(StrEnum):
    won = "won"
    lost = "lost"
    drawn = "drawn"
    white = "white"
    black = "black"


class _Phase(StrEnum):
    opening = "opening"
    middlegame = "middlegame"
    endgame = "endgame"


@commands.command("stats")
def stats_(
    name: Annotated[
        str | None, typer.Argument(help="A collection. Default: every collection.")
    ] = None,
    player: Annotated[
        str | None, typer.Option(help="Only this player's games, and their moves.")
    ] = None,
    color: Annotated[
        _Color | None,
        typer.Option(help="With --player, the colour they played; else one side's moves."),
    ] = None,
    result: Annotated[
        _Result | None,
        typer.Option(help="won / lost (from --player's side), drawn, or the side that won."),
    ] = None,
    opening: Annotated[
        str | None, typer.Option(help="An ECO code or its start (C4), or part of a name.")
    ] = None,
    phase: Annotated[_Phase | None, typer.Option(help="Only the moves of this phase.")] = None,
) -> None:
    """Accuracy, centipawn loss and ??/?/?! marks, by side, phase, opening and game."""
    f = stats.Filter(
        player=" ".join(player.split()) if player else None,
        color=None if color is None else ("white" if color is _Color.white else "black"),
        result=None if result is None else _RESULTS[result],
        opening=opening.strip() if opening and opening.strip() else None,
        phase=None if phase is None else _PHASES[phase],
    )
    problem = f.problem()
    if problem:
        _fail(problem)
    title, loaded = _load(name)
    if not loaded:
        _nothing(title)
        return
    report = stats.report(loaded, _thresholds(), f)
    only = _filters(f)
    if report.games == 0:
        whose = f" of {f.player}" if f.player else ""
        typer.echo(f"No games{whose} in {title}" + (f" ({only})." if only else "."))
        return
    n = report.games
    typer.echo(f"{title}{DOT}{n} {_s(n, 'game')}{DOT}{_score_text(report.score, f.player)}")
    if only:
        typer.echo(f"Only: {only}")
    typer.echo()
    head = ["", "Games", "Moves", "Accuracy", "ACPL", "??", "?", "?!"]
    rows = [
        [label, str(t.games), str(t.moves), _num(t.accuracy, 1), _num(t.acpl), *_marks(t)]
        for label, t in zip(report.labels, report.sides, strict=True)
    ]
    _table(head, rows)
    typer.echo()
    whose = report.labels[0] + "'s" if (f.player or f.color) else "both sides'"
    typer.echo(f"By phase ({whose} moves; the endgame is six pieces or fewer)")
    _table(
        ["", "Moves", "ACPL", "??", "?", "?!"],
        [
            [p.capitalize(), str(t.moves), _num(t.acpl), *_marks(t)]
            for p, t in report.phases.items()
            if t.moves or f.phase is None
        ],
    )
    typer.echo()
    typer.echo("Openings")
    a, b = (x[:1] if not f.player else x for x in report.labels)
    _table(
        ["", "Games", "Score", f"Accuracy {a} {DOT.strip()} {b}"],
        [
            [
                _opening_label(o),
                str(o.sides[0].games),
                _wdl(o.score),
                f"{_num(o.sides[0].accuracy)} {DOT.strip()} {_num(o.sides[1].accuracy)}",
            ]
            for o in report.openings
        ],
    )
    typer.echo()
    typer.echo("Games")
    _table(
        ["", "Result", "Accuracy W \u00b7 B", "ACPL W \u00b7 B", "Marks W \u00b7 B"],
        [
            [
                f"#{line.game.id} {line.game.white or '?'} vs {line.game.black or '?'}",
                line.game.result or "*",
                f"{_num(line.white.accuracy)} {DOT.strip()} {_num(line.black.accuracy)}",
                f"{_num(line.white.acpl)} {DOT.strip()} {_num(line.black.acpl)}",
                f"{_mark_text(line.white)} {DOT.strip()} {_mark_text(line.black)}",
            ]
            for line in report.lines
        ],
    )


@commands.command("players")
def players_(
    name: Annotated[
        str | None, typer.Argument(help="A collection. Default: every collection.")
    ] = None,
) -> None:
    """Everyone who played in a collection: games, colours, score and accuracy."""
    title, loaded = _load(name)
    if not loaded:
        _nothing(title)
        return
    found = stats.players(loaded, _thresholds())
    if not found:
        typer.echo(f"No player names in {title}'s games.")
        return
    typer.echo(f"{title}{DOT}{len(found)} {_s(len(found), 'player')}")
    _table(
        ["", "Games", "White", "Black", "Won", "Drawn", "Lost", "Accuracy"],
        [
            [
                p.name,
                str(p.games),
                str(p.as_white),
                str(p.as_black),
                str(p.score.won),
                str(p.score.drawn),
                str(p.score.lost),
                _num(p.accuracy, 1),
            ]
            for p in found
        ],
    )


_RESULTS: dict[_Result, stats.Result] = {
    _Result.won: "won",
    _Result.lost: "lost",
    _Result.drawn: "drawn",
    _Result.white: "white",
    _Result.black: "black",
}
_PHASES: dict[_Phase, stats.Phase] = {
    _Phase.opening: "opening",
    _Phase.middlegame: "middlegame",
    _Phase.endgame: "endgame",
}


# ---------------------------------------------------------------- helpers


def _load(name: str | None) -> tuple[str, list[stats.Game]]:
    """The collection's title and its games; every collection's without a name."""
    with closing(_open()) as conn:
        if name is None:
            return _ALL, store.load(conn)
        found = store.find(conn, " ".join(name.split()))
        if found is None:
            _fail(f"No collection called {name}.")
        return found.name, store.load(conn, found.id)


def _nothing(title: str) -> None:
    where = "" if title == _ALL else f" in {title}"
    typer.echo(f"No games{where} yet. Add games with: {_HOW}")


_ALL = "All collections"
_HOW = "blunderbook collection import FILE --into NAME"


def _thresholds() -> Thresholds:
    try:
        return host.settings().thresholds
    except host.HostError as exc:
        _fail(str(exc))


def _filters(f: stats.Filter) -> str:
    parts: list[str] = []
    if f.color:
        parts.append(
            f"as {f.color.capitalize()}" if f.player else f"{f.color.capitalize()}'s moves"
        )
    if f.result:
        parts.append(
            {
                "won": "won",
                "lost": "lost",
                "drawn": "drawn",
                "white": "White won",
                "black": "Black won",
            }[f.result]
        )
    if f.opening:
        parts.append(f"opening {f.opening}")
    if f.phase:
        parts.append(f"the {f.phase}")
    return DOT.join(parts)


def _score_text(score: stats.Score, player: str | None) -> str:
    if player:
        text = f"won {score.won}{DOT}drawn {score.drawn}{DOT}lost {score.lost}"
    else:
        text = f"White won {score.won}{DOT}drawn {score.drawn}{DOT}Black won {score.lost}"
    return text + (f"{DOT}{score.unfinished} unfinished" if score.unfinished else "")


def _wdl(score: stats.Score) -> str:
    return f"{score.won}\u2013{score.drawn}\u2013{score.lost}"


def _opening_label(o: stats.Opening) -> str:
    name = " ".join(x for x in (o.eco, o.name) if x) or "Unknown opening"
    if len(name) > 40:
        name = name[:39] + "\u2026"
    return f"As {o.color.capitalize()}: {name}" if o.color else name


def _num(value: float | None, digits: int = 0) -> str:
    return "\u2014" if value is None else f"{value:.{digits}f}"


def _marks(t: stats.Tally) -> list[str]:
    return [str(t.blunders), str(t.mistakes), str(t.inaccuracies)]


def _mark_text(t: stats.Tally) -> str:
    parts = [
        f"{n}{mark}"
        for n, mark in ((t.blunders, "??"), (t.mistakes, "?"), (t.inaccuracies, "?!"))
        if n
    ]
    return " ".join(parts) or "clean"


def _table(head: list[str], rows: list[list[str]]) -> None:
    """Columns padded to fit: the first left-aligned, the rest right-aligned."""
    widths = [max(len(r[i]) for r in [head, *rows]) for i in range(len(head))]
    for r in [head, *rows]:
        cells = [r[0].ljust(widths[0])] + [
            c.rjust(w) for c, w in zip(r[1:], widths[1:], strict=True)
        ]
        typer.echo("  ".join(cells).rstrip())


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
    router=router,
    web=files(__name__) / "web",
    migrations=files(__name__) / "migrations",
    cli=commands,
)
