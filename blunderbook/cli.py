"""Command-line interface.

Commands arrive milestone by milestone (see the README roadmap):
engine (1.3) · init, doctor, import (1.9) · fen (2.4) · backup, restore (2.5) ·
serve (3.4) · sync (M5) · print (M6).
"""

import errno
import os
import socket
import sqlite3
import sys
from contextlib import closing, suppress
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from blunderbook import __version__, config, importer
from blunderbook.core import detect, engine, pgn
from blunderbook.core.models import Color, Judgment, SavedIds, Totals
from blunderbook.db import backup, connection, repo

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
    """Set up config.toml (your names, Stockfish, the backup folder) and the database."""
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

    backup_dir = _ask_backup_folder(cfg.backup.dir)

    cfg = replace(
        cfg,
        my_names=names,
        stockfish_path=stockfish_path,
        backup=replace(cfg.backup, dir=backup_dir),
    )
    saved = config.save(cfg)
    typer.echo(f"\nSaved to {saved}")

    db = config.db_path()
    existed = db.exists()
    with closing(_open_database("Your settings are saved, but the database isn't ready.", cfg)):
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


def _ask_backup_folder(current: str) -> str:
    """Ask until the answer is a folder that can be used, or Enter (the default folder)."""
    typer.echo("\nBackups: daily copies of your database. Press Enter to keep them in")
    typer.echo(f"  {config.default_backup_folder()}")
    typer.echo("or give a folder. One your cloud drive syncs keeps a copy off this computer.")
    if os.name == "nt" and os.environ.get("ONEDRIVE"):  # Windows names are case-blind
        typer.echo("OneDrive is set up here, so %OneDrive%\\Blunderbook works.")
    while True:
        raw = typer.prompt("Backup folder", default=current, show_default=bool(current))
        setting = config.backup_dir_setting(raw)
        if not setting:
            return ""
        current = ""  # a failed answer isn't offered again as the default
        try:
            folder = config.backup_folder(config.Config(backup=config.BackupConfig(dir=setting)))
        except config.ConfigError as exc:
            typer.echo(f"{exc}\nTry again, or press Enter for the default.")
            continue
        if folder == config.db_path().parent:
            typer.echo("That's the database's own folder. Pick another, or press Enter.")
            continue
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            typer.echo(f"Can't create {folder}: {exc.strerror or exc}")
            typer.echo("Try again, or press Enter for the default.")
            continue
        typer.echo(f"Backups go to {folder}")
        return setting


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
    backup_problems, warnings = _doctor_backups(cfg)
    problems += backup_problems

    typer.echo("")
    if problems:
        _fail(f"{_plural(problems, 'problem')} found.")
    if warnings:
        typer.echo(f"No problems found. {_plural(warnings, 'warning')}.")
    else:
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


def _doctor_backups(cfg: config.Config) -> tuple[int, int]:
    """Print the Backups rows; return the numbers of problems and warnings."""
    try:
        folder = config.backup_folder(cfg)
    except config.ConfigError as exc:
        _row("Backups", f"Problem: {exc}")
        return 1, 0
    _row("Backups", str(folder))
    warnings = 0
    if cfg.backup.dir and not folder.is_dir():
        _row("", "Warning: this folder doesn't exist. Check [backup] dir in config.toml.")
        warnings += 1
    else:
        try:
            found = backup.list_backups(folder)
        except backup.BackupError as exc:
            _row("", f"Problem: {exc}")
            return 1, 0
        if not found:
            has_db = config.db_path().exists()
            _row("", "none yet. Run blunderbook backup to take one." if has_db else "none yet.")
        else:
            last = found[-1]
            age = datetime.now(UTC) - last.taken_at
            _row(
                "",
                f"last {_local_time(last.taken_at)} ({_ago(age)}) \N{MIDDLE DOT} "
                f"{_plural(len(found), 'backup')} kept",
            )
            if age > backup.STALE_AFTER:
                _row("", f"Warning: the last backup is {age.days} days old.")
                _row("", "Run blunderbook backup.")
                warnings += 1
    if not cfg.backup.auto:
        _row("", "Daily backups are off ([backup] auto in config.toml).")
    return 0, warnings


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

    _daily_backup(cfg)
    with closing(_open_database("Can't import: the database can't be used.", cfg)) as conn:
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


def _open_database(problem: str, cfg: config.Config) -> sqlite3.Connection:
    """Open the database, creating it if it's missing. A database with data is backed up
    before it's upgraded. Close it with ``closing``."""
    path = config.db_path()
    existed = path.exists()

    def before_migrate() -> None:
        try:
            snapshot = backup.take(
                path, config.backup_folder(cfg), keep=cfg.backup.keep, reason="pre-migrate"
            )
        except (config.ConfigError, backup.BackupError) as exc:
            raise connection.StorageError(
                f"Can't back up the database before upgrading it, so it wasn't upgraded: {exc}"
            ) from exc
        typer.echo(f"Backed up the database before upgrading it:\n  {snapshot.backup.path}")

    try:
        conn = connection.open_db(path, create=True, before_migrate=before_migrate)
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
        _print_entry(blunder, entry_id)


_MARKS: dict[Judgment, str] = {"blunder": "??", "mistake": "?", "inaccuracy": "?!"}


def _print_entry(found: importer.FoundBlunder, entry_id: int) -> None:
    f, h = found.finding, found.hints
    typer.echo(f"  {f.ply.label}{_MARKS[f.judgment]}  Best was {f.best_san}: {f.best_line_san}")
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


# ---------------------------------------------------------------- fen


@app.command()
def fen(
    position: Annotated[
        str,
        typer.Argument(metavar="FEN", help="The position before your move, as FEN, in quotes."),
    ],
    move: Annotated[
        str,
        typer.Option("--move", help="The move you played: UCI like e2e4, or SAN like Nf3."),
    ],
    opponent: Annotated[str | None, typer.Option(help="Who you played.")] = None,
    on: Annotated[
        str | None,
        typer.Option("--date", metavar="YYYY-MM-DD", help="When you played. Default: today."),
    ] = None,
    stockfish: Annotated[
        str | None,
        typer.Option("--stockfish", help="Use this Stockfish for this entry."),
    ] = None,
) -> None:
    """Log one position and the move you played, for games you have no PGN of.

    You're the side to move. It's logged as a blunder, mistake or inaccuracy, by its cost.
    """
    cfg = _load_config()
    played_on = _date_option(on)
    try:
        queued = importer.prepare_fen(
            position,
            move,
            me=cfg.my_names[0] if cfg.my_names else None,
            opponent=opponent,
            played_on=played_on,
        )
    except importer.FenError as exc:
        _fail(str(exc))
    assert queued.game is not None and queued.fingerprint is not None and queued.side
    label = queued.game.plies[0].label

    _daily_backup(cfg)
    problem = "Can't log the position: the database can't be used."
    with closing(_open_database(problem, cfg)) as conn:
        earlier = repo.find_saved(conn, queued.fingerprint)
        if earlier is not None:
            typer.echo(_already_logged(label, earlier))
            return
        found = _find_engine(stockfish, cfg, probe=False)
        if found.problem is not None:
            _fail(f"Can't analyse: {found.problem}")
        assert found.path is not None
        try:
            with engine.Engine.open(
                [str(found.path)], threads=cfg.engine_threads, hash_mb=cfg.engine_hash_mb
            ) as sf:
                typer.echo(f"Analysing with {sf.name} at depth {cfg.engine_depth}.")
                _version_notes(sf.info)
                analysed = importer.analyse(
                    queued,
                    sf,
                    depth=cfg.engine_depth,
                    thresholds=cfg.thresholds,
                    flag_at="inaccuracy",
                )
        except engine.EngineError as exc:
            _fail(f"Analysis stopped: {exc}\nNothing was logged.")

        if not analysed.blunders:
            evals = analysed.analysis.evals
            swing = detect.swing(evals[0], evals[1], queued.side)
            if swing >= cfg.thresholds.inaccuracy:  # not flagged, so it was the best move
                typer.echo(f"{label} is Stockfish's own choice here. Nothing was logged.")
            else:
                typer.echo(
                    f"{label} isn't a mistake by Stockfish's measure (swing {swing:.2f}; "
                    f"inaccuracies start at {cfg.thresholds.inaccuracy:.2f}). Nothing was logged."
                )
            return
        saved = importer.save(conn, analysed)
        if saved is None:  # logged meanwhile by another command
            earlier = repo.find_saved(conn, queued.fingerprint)
            assert earlier is not None
            typer.echo(_already_logged(label, earlier))
            return

    (blunder,) = analysed.blunders
    (entry_id,) = saved.blunder_ids
    parts = [importer.FEN_LABEL, queued.players]
    if queued.date:
        parts.append(queued.date)
    parts.append(f"you played {queued.side.capitalize()}")
    typer.echo("")
    typer.echo(" \N{MIDDLE DOT} ".join(parts))
    _print_entry(blunder, entry_id)
    judgment = blunder.finding.judgment
    article = "an" if judgment == "inaccuracy" else "a"
    typer.echo("")
    typer.echo(f"Logged {label}{_MARKS[judgment]} as {article} {judgment}: entry #{entry_id}.")


def _date_option(value: str | None) -> date:
    if value is None:
        return date.today()
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        _fail(f"--date needs a date like 2026-11-05, not {value!r}.")


def _already_logged(label: str, earlier: SavedIds) -> str:
    where = f" (entry #{earlier.blunder_ids[0]})" if earlier.blunder_ids else ""
    return f"You've already logged {label} in this position{where}. Nothing was added."


# ---------------------------------------------------------------- serve

HOST = "127.0.0.1"  # this computer only: nothing else on the network can reach it (§10)
DEFAULT_PORT = 8732


@app.command()
def serve(
    port: Annotated[
        int, typer.Option(min=1, max=65535, help="The port on 127.0.0.1 to serve on.")
    ] = DEFAULT_PORT,
) -> None:
    """Start the web app on this computer: read your blunders and write your notes.

    It answers on 127.0.0.1 only. Press Ctrl+C to stop it.
    """
    cfg = _load_config()
    sock = _listen(port)  # first: a busy port changes nothing
    try:
        _daily_backup(cfg)
        with closing(_open_database("Can't start: the database can't be used.", cfg)):
            pass  # created or upgraded (backed up first) now, not halfway through a request

        import uvicorn  # here, so the other commands start quickly

        from blunderbook.api.app import create_app

        server = uvicorn.Server(
            uvicorn.Config(
                create_app(config.db_path()),
                log_level="warning",
                access_log=False,
                timeout_graceful_shutdown=5,
            )
        )
        typer.echo(f"Blunderbook is running at http://{HOST}:{port}/")
        typer.echo("Open that address in your browser. Press Ctrl+C to stop.")
        with suppress(KeyboardInterrupt):  # uvicorn stops cleanly, then raises Ctrl+C again
            server.run(sockets=[sock])
    finally:
        sock.close()
    typer.echo("Stopped.")


def _listen(port: int) -> socket.socket:
    """Take ``port`` on 127.0.0.1, or say plainly why it can't be had."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            # Windows lets a second program share a port unless the first one says no.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            # Elsewhere this only allows a quick restart; two servers still can't share it.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((HOST, port))
    except OSError as exc:
        sock.close()
        other = port + 1 if port < 65535 else port - 1
        code = getattr(exc, "winerror", None) or exc.errno
        if code in (errno.EADDRINUSE, _WSAEADDRINUSE):
            _fail(
                f"Port {port} is already in use. Is Blunderbook already running?\n"
                f"Stop it, or use another port: blunderbook serve --port {other}"
            )
        if code == _WSAEACCES:
            _fail(
                f"Windows won't let Blunderbook use port {port}: another program holds it, "
                f"or it's reserved.\nUse another port: blunderbook serve --port {other}"
            )
        _fail(f"Can't serve on {HOST}:{port}: {exc.strerror or exc}")
    return sock


_WSAEADDRINUSE = 10048  # Windows socket error codes
_WSAEACCES = 10013


# ---------------------------------------------------------------- backup, restore


@app.command("backup")
def backup_(
    to: Annotated[
        Path | None,
        typer.Option("--to", metavar="FOLDER", help="Back up to this folder this time."),
    ] = None,
) -> None:
    """Back up the database now. Only the newest are kept (keep in config.toml)."""
    cfg = _load_config()
    folder = _backup_folder(cfg) if to is None else Path(os.path.abspath(to.expanduser()))
    try:
        snapshot = backup.take(config.db_path(), folder, keep=cfg.backup.keep)
    except backup.BackupError as exc:
        _fail(str(exc))
    typer.echo(f"Backed up the database to\n  {snapshot.backup.path}")
    if snapshot.removed:
        typer.echo(
            f"Deleted {_plural(len(snapshot.removed), 'older backup')}, keeping the newest "
            f"{cfg.backup.keep}."
        )


@app.command()
def restore(
    file: Annotated[
        Path,
        typer.Argument(
            metavar="FILE",
            help="A backup file. A file name on its own is looked up in the backup folder.",
        ),
    ],
    yes: Annotated[bool, typer.Option("--yes", help="Don't ask to confirm.")] = False,
) -> None:
    """Replace the database with a backup, after checking it.

    Your current database is backed up first, as a -pre-restore copy.
    """
    cfg = _load_config()
    folder = _backup_folder(cfg)
    path = _find_backup(file, folder)
    db = config.db_path()
    try:
        backup.check_file(path)
    except backup.BackupError as exc:
        _fail(f"Can't restore {path}: {exc}\nNothing was changed.")

    _row("Backup", str(path))
    _row("", _describe_backup(path))
    _row("Database", str(db))
    _row("", _describe_database(db))
    if not yes:
        typer.echo("\nStop the web app (blunderbook serve) first if it's running.")
        try:
            go = typer.confirm("Replace your database with this backup?", default=False)
        except typer.Abort:
            go = False
        if not go:
            _fail("Nothing was changed.")

    try:
        result = backup.restore(path, db, folder)
    except backup.BackupError as exc:
        _fail(f"Can't restore {path}: {exc}")
    typer.echo("")
    if result.safety is not None:
        typer.echo(f"Saved a copy of your database first:\n  {result.safety.path}")
    if result.upgraded:
        typer.echo(f"Upgraded the backup from schema {result.version} to {result.upgraded[-1]}.")
    totals = _totals(db)
    held = "" if totals is None else f": {_describe_totals(totals)}"
    typer.echo(f"Restored {path.name}{held}.")


def _daily_backup(cfg: config.Config) -> None:
    """The automatic backup before a command that changes data. It never stops the command."""
    if not cfg.backup.auto:
        return
    try:
        snapshot = backup.auto(config.db_path(), config.backup_folder(cfg), keep=cfg.backup.keep)
    except (config.ConfigError, backup.BackupError) as exc:
        typer.echo(f"Warning: the daily backup didn't work: {exc}", err=True)
        return
    if snapshot is not None:
        typer.echo(f"Daily backup: {snapshot.backup.path}")


def _backup_folder(cfg: config.Config) -> Path:
    try:
        return config.backup_folder(cfg)
    except config.ConfigError as exc:
        _fail(str(exc))


def _find_backup(file: Path, folder: Path) -> Path:
    """``file`` as given, or a bare file name found in the backup folder."""
    if file.exists():
        return file
    bare = file.name == str(file)
    if bare and (folder / file.name).exists():
        return folder / file.name
    where = f", here or in the backup folder {folder}" if bare else ""
    _fail(f"No file called {file}{where}.\nNothing was changed.")


def _describe_backup(path: Path) -> str:
    parts = []
    named = backup.parse_name(path)
    if named is not None:
        age = datetime.now(UTC) - named.taken_at
        parts.append(f"taken {_local_time(named.taken_at)} ({_ago(age)})")
    totals = _totals(path)
    if totals is not None:
        parts.append(_describe_totals(totals))
    return " \N{MIDDLE DOT} ".join(parts) or "a Blunderbook database"


def _describe_database(db: Path) -> str:
    if not db.exists():
        return "not created yet"
    totals = _totals(db)
    return "can't be read" if totals is None else f"now holds {_describe_totals(totals)}"


def _totals(path: Path) -> Totals | None:
    try:
        with closing(connection.connect(path, mode="ro")) as conn:
            return repo.totals(conn)
    except connection.StorageError, sqlite3.Error:
        return None


def _describe_totals(totals: Totals) -> str:
    return f"{_plural(totals.games, 'game')} \N{MIDDLE DOT} {_plural(totals.entries, 'entry')}"


def _local_time(moment: datetime) -> str:
    return f"{moment.astimezone():%Y-%m-%d %H:%M}"


def _ago(age: timedelta) -> str:
    minutes = int(age.total_seconds() // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{_plural(minutes, 'minute')} ago"
    if minutes < 48 * 60:
        return f"{_plural(minutes // 60, 'hour')} ago"
    return f"{_plural(age.days, 'day')} ago"


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
    if n == 1:
        return f"{n} {word}"
    if word.endswith("y") and word[-2:-1] not in ("a", "e", "o", "u"):
        return f"{n} {word[:-1]}ies"
    return f"{n} {word}s"


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
