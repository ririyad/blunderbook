"""Command-line interface.

Commands arrive milestone by milestone (see the README roadmap):
engine (1.3) · init, doctor, import (1.9) · fen, backup, restore (M2) · serve (M3) ·
sync (M5) · print (M6).
"""

import os
import sqlite3
import sys
from contextlib import closing
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from blunderbook import __version__, config, importer
from blunderbook.core import engine, pgn
from blunderbook.core.models import Color
from blunderbook.db import connection, repo

app = typer.Typer(
    name="blunderbook",
    help="Your chess mistake library.",
    no_args_is_help=True,
    add_completion=False,
)

engine_app = typer.Typer(
    help="Show or set which Stockfish Blunderbook uses.",
    no_args_is_help=True,
)
app.add_typer(engine_app, name="engine")


def _show_version(value: bool) -> None:
    if value:
        typer.echo(f"blunderbook {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Show the version and exit.",
            callback=_show_version,
            is_eager=True,
        ),
    ] = False,
) -> None:
    """Your chess mistake library."""


# ---------------------------------------------------------------- engine


@engine_app.command("show")
def engine_show() -> None:
    """Show which Stockfish is used, and where that setting comes from."""
    found = _find_engine(None, _load_config())
    if found.problem is not None:
        _fail(found.problem)
    assert found.info is not None and found.path is not None and found.origin is not None
    typer.echo(found.info.name)
    typer.echo(f"Path  {found.path}")
    typer.echo(f"From  {config.ORIGIN_LABELS[found.origin]}")
    _version_notes(found.info)


@engine_app.command("set")
def engine_set(
    path: Annotated[
        str,
        typer.Argument(help="The Stockfish program, or the folder you unzipped it to."),
    ],
) -> None:
    """Check a Stockfish program and save its path to config.toml."""
    cfg = _load_config()
    try:
        program = config.resolve_engine_path(path)
    except config.EnginePathError as exc:
        _fail(f"{exc}\nNothing was saved.")
    try:
        info = engine.probe([str(program)])
    except engine.EngineError as exc:
        _fail(f"Can't use {program}: {exc}\nNothing was saved.")
    saved = config.save(replace(cfg, stockfish_path=str(program)))
    typer.echo(f"Found {info.name} at\n  {program}")
    typer.echo(f"Saved to {saved}")
    _version_notes(info)
    _env_override_note()


@engine_app.command("clear")
def engine_clear() -> None:
    """Forget the saved path and look for stockfish on PATH again."""
    cfg = _load_config()
    if not cfg.stockfish_path:
        typer.echo("No path was saved. Blunderbook looks for stockfish on PATH.")
    else:
        config.save(replace(cfg, stockfish_path=""))
        typer.echo("Cleared. Blunderbook will look for stockfish on PATH.")
    _env_override_note()


# ---------------------------------------------------------------- init


@app.command()
def init() -> None:
    """Set up config.toml (your names, where Stockfish is) and the database."""
    path = config.config_path()
    cfg = _load_config()
    if path.exists():
        typer.echo(f"Updating {path}. Press Enter to keep a value.")
    else:
        typer.echo(f"Creating {path}.")

    typer.echo("\nYour names and usernames tell Blunderbook which side you played.")
    raw_names = typer.prompt(
        "Names, separated by commas",
        default=", ".join(cfg.my_names),
        show_default=bool(cfg.my_names),
    )
    names = tuple(dict.fromkeys(n.strip() for n in raw_names.split(",") if n.strip()))
    if not names:
        typer.echo("No names set. Every game will ask which side you played.")

    typer.echo("\nStockfish: the program, or the folder you unzipped it to.")
    stockfish_path = _ask_stockfish(cfg.stockfish_path)

    saved = config.save(replace(cfg, my_names=names, stockfish_path=stockfish_path))
    typer.echo(f"\nSaved to {saved}")

    db = config.db_path()
    existed = db.exists()
    with closing(_open_database("Your settings are saved, but the database isn't ready.")):
        pass
    if existed:
        typer.echo(f"Database {db}")
    typer.echo("Next: blunderbook import FILE.pgn")


def _ask_stockfish(current: str) -> str:
    """Ask until the answer is a working Stockfish, or Enter (look on PATH)."""
    while True:
        raw = typer.prompt(
            "Stockfish path (Enter = look on PATH)",
            default=current,
            show_default=bool(current),
        ).strip()
        if not raw:
            on_path = config.locate_stockfish(config=config.Config(), env={})
            if on_path.path is None:
                typer.echo(
                    "No Stockfish on PATH yet. Install Stockfish 17 or newer, then run\n"
                    "  blunderbook engine set PATH"
                )
            else:
                _report_engine(on_path.path)
            _env_override_note()
            return ""
        current = ""  # a failed answer isn't offered again as the default
        try:
            program = config.resolve_engine_path(raw)
        except config.EnginePathError as exc:
            typer.echo(f"{exc}\nTry again, or press Enter to look on PATH.")
            continue
        try:
            info = engine.probe([str(program)])
        except engine.EngineError as exc:
            typer.echo(f"Can't use {program}: {exc}\nTry again, or press Enter to look on PATH.")
            continue
        typer.echo(f"Found {info.name} at\n  {program}")
        _version_notes(info)
        _env_override_note()
        return str(program)


def _report_engine(path: Path) -> None:
    try:
        info = engine.probe([str(path)])
    except engine.EngineError as exc:
        typer.echo(f"Found {path} on PATH, but can't use it: {exc}")
    else:
        typer.echo(f"Found {info.name} on PATH at\n  {path}")
        _version_notes(info)


# ---------------------------------------------------------------- doctor

_LABEL = 11  # column width for doctor's labels


@app.command()
def doctor(
    stockfish: Annotated[
        str | None,
        typer.Option("--stockfish", help="Check this Stockfish instead of the configured one."),
    ] = None,
) -> None:
    """Check config.toml, Stockfish and the database. Changes nothing."""
    problems = 0
    path = config.config_path()
    try:
        cfg = config.load(path)
    except config.ConfigError as exc:
        message = str(exc)  # often "Problem in <path>: ..." already
        _row("Config", message if message.startswith("Problem") else f"Problem: {message}")
        problems += 1
        cfg = config.Config()
    else:
        _row("Config", str(path) if path.exists() else "not created yet. Run blunderbook init.")

    if cfg.my_names:
        _row("Names", ", ".join(cfg.my_names))
    else:
        _row("Names", "none set. Every game will ask which side you played.")

    found = _find_engine(stockfish, cfg)
    if found.problem is not None:
        _row("Stockfish", f"Problem: {found.problem}")
        problems += 1
    else:
        assert found.info is not None and found.origin is not None
        _row("Stockfish", found.info.name)
        _row("", str(found.path))
        _row("", f"from {config.ORIGIN_LABELS[found.origin]}")
        _version_notes(found.info, indent=" " * _LABEL)
    _row(
        "Analysis",
        f"depth {cfg.engine_depth} \N{MIDDLE DOT} {_plural(cfg.engine_threads, 'thread')} "
        f"\N{MIDDLE DOT} {cfg.engine_hash_mb} MB hash",
    )
    problems += _doctor_database(config.db_path())

    typer.echo("")
    if problems:
        _fail(f"{_plural(problems, 'problem')} found.")
    typer.echo("No problems found.")


def _doctor_database(path: Path) -> int:
    """Print the Database rows; return the number of problems."""
    _row("Database", str(path))
    if not path.exists():
        _row("", "not created yet. Run blunderbook init.")
        return 0
    try:
        result = connection.check(path)
    except connection.StorageError as exc:
        _row("", f"Problem: {exc}")
        return 1
    for problem in result.problems:
        _row("", f"Problem: {problem}")
    if result.problems:
        return len(result.problems)
    _row("", f"schema {result.version} \N{MIDDLE DOT} integrity ok")
    if result.version < result.latest:
        _row("", f"Note: run blunderbook init to upgrade it to schema {result.latest}.")
    return 0


def _row(label: str, text: str) -> None:
    indented = text.replace("\n", "\n" + " " * _LABEL)
    typer.echo(f"{label:<{_LABEL}}{indented}")


# ---------------------------------------------------------------- import


class _Side(StrEnum):
    white = "white"
    black = "black"

    @property
    def color(self) -> Color:
        return "white" if self is _Side.white else "black"


@app.command("import")
def import_(
    path: Annotated[Path, typer.Argument(help="A PGN file with one or more games.")],
    side: Annotated[
        _Side | None,
        typer.Option(help="Your side, for games where your names don't match a player."),
    ] = None,
    depth: Annotated[
        int | None,
        typer.Option(min=1, help="Search depth per position. Default: engine_depth."),
    ] = None,
    stockfish: Annotated[
        str | None,
        typer.Option("--stockfish", help="Use this Stockfish for this import."),
    ] = None,
) -> None:
    """Import a PGN file: find your blunders with Stockfish and save them."""
    cfg = _load_config()
    try:
        data = path.read_bytes()
    except OSError as exc:
        _fail(f"Can't read {path}: {exc.strerror or exc}")
    decoded = pgn.decode(data)
    if decoded.encoding == "cp1252":
        typer.echo("Read as Windows-1252 (the file isn't UTF-8).")

    with closing(_open_database("Can't import: the database can't be used.")) as conn:
        my_side: Color | None = None if side is None else side.color
        queue = list(
            importer.prepare(
                decoded.text, _all_names(cfg), side=my_side, known=repo.known_fingerprints(conn)
            )
        )
        if not queue:
            _fail(f"No games found in {path}.")

        ready = [q for q in queue if q.status == "ready"]
        saved: dict[int, importer.SavedGame] = {}
        if ready:
            found = _find_engine(stockfish, cfg, probe=False)
            if found.problem is not None:
                _fail(f"Can't analyse: {found.problem}")
            assert found.path is not None
            use_depth = depth or cfg.engine_depth
            position = {q.number: i for i, q in enumerate(queue)}
            try:
                with engine.Engine.open(
                    [str(found.path)], threads=cfg.engine_threads, hash_mb=cfg.engine_hash_mb
                ) as sf:
                    typer.echo(f"Analysing with {sf.name} at depth {use_depth}.")
                    _version_notes(sf.info)
                    for k, queued in enumerate(ready, start=1):
                        progress = _Progress(f"Game {queued.number} ({k} of {len(ready)})")
                        analysed = importer.analyse(
                            queued,
                            sf,
                            depth=use_depth,
                            thresholds=cfg.thresholds,
                            progress=progress,
                        )
                        progress.done()
                        result = importer.save(conn, analysed)
                        if result is None:  # another import saved it meanwhile
                            queue[position[queued.number]] = replace(
                                queued, status="duplicate", reason=importer.ALREADY_IMPORTED
                            )
                        else:
                            saved[queued.number] = result
            except engine.EngineError as exc:
                _print_report(queue, saved)
                _fail(
                    f"Analysis stopped: {exc}\n"
                    "Import the file again to analyse the rest. Games already saved are skipped."
                )

        _print_report(queue, saved)


def _open_database(problem: str) -> sqlite3.Connection:
    """Open the database, creating it if it's missing. Close it with ``closing``."""
    path = config.db_path()
    existed = path.exists()
    try:
        conn = connection.open_db(path, create=True)
    except connection.StorageError as exc:
        _fail(f"{problem}\n{exc}")
    if not existed:
        typer.echo(f"Created the database {path}")
    return conn


def _all_names(cfg: config.Config) -> list[str]:
    return [*cfg.my_names, cfg.lichess.username, cfg.chesscom.username]


def _print_report(queue: list[importer.QueuedGame], saved: dict[int, importer.SavedGame]) -> None:
    for queued in queue:
        typer.echo("")
        typer.echo(_game_heading(queued))
        for warning in queued.warnings:
            typer.echo(f"  Note: {warning}")
        if queued.status in ("error", "duplicate"):
            typer.echo(f"  {queued.reason}")
        elif queued.status == "needs_side":
            typer.echo("  Which side were you? Run again with --side white or --side black,")
            typer.echo("  or add your name to my_names in config.toml.")
        elif queued.number in saved:
            _print_blunders(saved[queued.number])
        else:
            typer.echo("  Not analysed.")
    typer.echo("")
    typer.echo(importer.summary(queue, saved.values()))


def _game_heading(queued: importer.QueuedGame) -> str:
    parts = [f"Game {queued.number}", queued.players]
    if queued.date:
        parts.append(queued.date)
    if queued.source is not None:
        parts.append(queued.source.label)
    if queued.side is not None:
        chosen = " (from --side)" if queued.side_from == "option" else ""
        parts.append(f"you played {queued.side.capitalize()}{chosen}")
    return " \N{MIDDLE DOT} ".join(parts)


def _print_blunders(saved: importer.SavedGame) -> None:
    result = saved.analysed
    if not result.blunders:
        typer.echo("  No blunders found.")
        return
    game = result.queued.game
    assert game is not None
    if not game.has_clocks:
        typer.echo("  No clock times in this PGN.")
    for blunder, entry_id in zip(result.blunders, saved.blunder_ids, strict=True):
        f, h = blunder.finding, blunder.hints
        typer.echo(f"  {f.ply.label}??  Best was {f.best_san}: {f.best_line_san}")
        if f.refutation_san:
            typer.echo(f"      Refutation: {f.refutation_san}")
        details = [f"Swing {f.swing:.2f}"]
        if h.clock_left_s is not None:
            details.append(f"{_seconds(h.clock_left_s)} left")
        if h.time_spent_s is not None:
            details.append(f"{_seconds(h.time_spent_s)} on the move")
        details.append(f"entry #{entry_id}")
        typer.echo("      " + " \N{MIDDLE DOT} ".join(details))
        if h.causes:
            typer.echo(f"      Suggested: {', '.join(h.causes)}")


def _seconds(value: float) -> str:
    whole = int(value)
    if whole >= 60:
        return f"{whole // 60}:{whole % 60:02d}"
    return f"{value:g} s"


class _Progress:
    """Positions done / total, redrawn on one line when the output is a terminal."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.live = sys.stderr.isatty()

    def __call__(self, done: int, total: int) -> None:
        if self.live:
            sys.stderr.write(f"\r{self.label}: {100 * done // total}%")
            sys.stderr.flush()

    def done(self) -> None:
        if self.live:
            sys.stderr.write("\r\033[K")
            sys.stderr.flush()


# ---------------------------------------------------------------- helpers


@dataclass(frozen=True, slots=True)
class _FoundEngine:
    path: Path | None = None
    origin: config.Origin | None = None
    info: engine.EngineInfo | None = None
    problem: str | None = None


def _find_engine(flag: str | None, cfg: config.Config, *, probe: bool = True) -> _FoundEngine:
    """Locate Stockfish (same lookup everywhere) and, with ``probe``, check it runs."""
    location = config.locate_stockfish(flag, cfg, config_dir=config.config_path().parent)
    if location.path is None or location.origin is None:
        return _FoundEngine(problem=location.problem or config.NOT_FOUND)
    if not probe:
        return _FoundEngine(location.path, location.origin)
    try:
        info = engine.probe([str(location.path)])
    except engine.EngineError as exc:
        return _FoundEngine(
            location.path, location.origin, problem=f"Can't use {location.path}: {exc}"
        )
    return _FoundEngine(location.path, location.origin, info)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _load_config() -> config.Config:
    try:
        return config.load(config.config_path())
    except config.ConfigError as exc:
        _fail(str(exc))


def _fail(message: str) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(1)


def _version_notes(info: engine.EngineInfo, indent: str = "") -> None:
    if info.outdated:
        typer.echo(
            f"{indent}Note: Blunderbook expects Stockfish {engine.MIN_STOCKFISH_MAJOR} or "
            "newer. Older versions can judge positions differently."
        )
    elif info.dev_build:
        typer.echo(
            f"{indent}Note: this looks like a development build, so its version can't be checked."
        )


def _env_override_note() -> None:
    value = os.environ.get(config.STOCKFISH_ENV, "").strip()
    if value:
        typer.echo(
            f"Note: {config.STOCKFISH_ENV} is set ({value}), so it's used instead of "
            "config.toml until you unset it."
        )
