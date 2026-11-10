"""Command-line interface.

Commands arrive milestone by milestone (see the README roadmap):
engine (1.3) · init, doctor, import (1.9) · fen (2.4) · backup, restore (2.5) ·
serve (3.4) · sync (6.4) · print (7.1) · ai (8.1) · ext (9.1) · update, ext install.

`run()` is the program's entry point: it adds the commands of the extensions turned on
in config.toml, then runs the app.
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

from blunderbook import __version__, config, ext, importer, printing, sources, update
from blunderbook.core import engine, pgn
from blunderbook.core.models import Batch, Color, SyncSource, Totals
from blunderbook.core.source import game_time
from blunderbook.db import backup, connection, repo
from blunderbook.sources.base import SyncError, redact

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

ai_app = typer.Typer(
    help="Set up the optional AI explanations (OpenRouter, your own key).",
    no_args_is_help=True,
)
app.add_typer(ai_app, name="ai")

ext_app = typer.Typer(
    help="List, install, turn on or turn off extensions (separately installed packages).",
    no_args_is_help=True,
)
app.add_typer(ext_app, name="ext")


def run() -> None:
    """The `blunderbook` program: the app plus the commands of extensions that are on."""
    add_extension_commands()
    app()


def add_extension_commands() -> None:
    """Add `blunderbook <name> ...` for each extension that's on and has commands. A broken
    config or extension is left to the command (and `doctor`) to report."""
    try:
        cfg = config.load(config.config_path())
    except config.ConfigError:
        return
    for extension in ext.load(cfg.extensions.enabled).extensions:
        if extension.cli is not None:
            app.add_typer(extension.cli, name=extension.name, help=extension.title)


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


# ---------------------------------------------------------------- ai


@ai_app.command("show")
def ai_show() -> None:
    """Show whether AI explanations are on, the model, and whether a key is set."""
    cfg = _load_config()
    typer.echo(f"AI explanations  {'on' if cfg.ai.enabled else 'off'}")
    typer.echo(f"Model            {cfg.ai.model or 'not set'}")
    typer.echo(f"OpenRouter key   {'set' if cfg.ai.key else 'not set'}")
    problem = config.ai_problem(cfg)
    if cfg.ai.enabled and problem is not None:
        typer.echo(f"\n{problem}")


@ai_app.command("set-key")
def ai_set_key() -> None:
    """Save your OpenRouter API key to config.toml. It's typed hidden, so it isn't in your
    shell history. Press Enter on an empty line to remove the key."""
    cfg = _load_config()
    key = typer.prompt(
        "OpenRouter key (hidden; Enter alone removes it)",
        default="",
        show_default=False,
        hide_input=True,
    ).strip()
    saved = config.save(replace(cfg, ai=replace(cfg.ai, key=key)))
    if key:
        typer.echo(f"Key saved to {saved}")
        if not cfg.ai.model:
            typer.echo("Next: blunderbook ai model NAME")
        elif not cfg.ai.enabled:
            typer.echo("Next: blunderbook ai on")
    else:
        typer.echo(f"Key removed from {saved}")


@ai_app.command("model")
def ai_model(
    name: Annotated[
        str,
        typer.Argument(help="An OpenRouter model id, as listed on openrouter.ai/models."),
    ],
) -> None:
    """Save the model that writes the explanations."""
    cfg = _load_config()
    model = name.strip()
    if not model:
        _fail("The model name is empty. Nothing was saved.")
    saved = config.save(replace(cfg, ai=replace(cfg.ai, model=model)))
    typer.echo(f"Model {model} saved to {saved}")
    if not cfg.ai.key:
        typer.echo("Next: blunderbook ai set-key")
    elif not cfg.ai.enabled:
        typer.echo("Next: blunderbook ai on")


@ai_app.command("on")
def ai_on() -> None:
    """Show the "Explain this blunder" button on the page."""
    cfg = _load_config()
    turned_on = replace(cfg, ai=replace(cfg.ai, enabled=True))
    problem = config.ai_problem(turned_on)
    if problem is not None:
        _fail(f"{problem}\nAI explanations stay off.")
    config.save(turned_on)
    typer.echo(f"AI explanations are on, with {cfg.ai.model}.")
    typer.echo('Nothing is sent until you press "Explain this blunder" on the page.')


@ai_app.command("off")
def ai_off() -> None:
    """Hide the AI button. Your key, model and saved explanations stay."""
    cfg = _load_config()
    if cfg.ai.enabled:
        config.save(replace(cfg, ai=replace(cfg.ai, enabled=False)))
    typer.echo("AI explanations are off. Saved explanations still show in the Log.")


# ---------------------------------------------------------------- ext


@ext_app.command("list")
def ext_list() -> None:
    """Show the extensions installed on this computer, and which are on."""
    cfg = _load_config()
    found = ext.installed()
    on = set(cfg.extensions.enabled)
    if not found and not on:
        typer.echo("No extensions installed.")
        return
    loaded = ext.load(cfg.extensions.enabled)
    titles = {e.name: e.title for e in loaded.extensions}
    for item in found:
        state = "on" if item.name in on else "off"
        version = f" {item.version}" if item.version else ""
        title = f" \N{MIDDLE DOT} {titles[item.name]}" if item.name in titles else ""
        typer.echo(f"{item.name:<12}{state:<5}{item.package or '?'}{version}{title}")
    for problem in loaded.problems:
        typer.echo(f"Problem: {problem}")


@ext_app.command("enable")
def ext_enable(name: Annotated[str, typer.Argument(help="The extension's name.")]) -> None:
    """Turn an installed extension on. Restart `blunderbook serve` to see its tab."""
    cfg = _load_config()
    point = ext.find(name)
    if point is None:
        _fail(f"No extension called {name} is installed. Nothing was changed.")
    extension, problem = ext.load_one(point)
    if problem is not None or extension is None:
        _fail(f"{problem}\nNothing was changed.")
    if name in cfg.extensions.enabled:
        typer.echo(f"The {name} extension ({extension.title}) is already on.")
        return
    enabled = (*cfg.extensions.enabled, name)
    config.save(replace(cfg, extensions=replace(cfg.extensions, enabled=enabled)))
    typer.echo(f"Turned on {name} ({extension.title}).")
    typer.echo("Restart blunderbook serve to see it on the page.")


@ext_app.command("disable")
def ext_disable(name: Annotated[str, typer.Argument(help="The extension's name.")]) -> None:
    """Turn an extension off. Its data stays, and comes back if you turn it on again."""
    cfg = _load_config()
    if name not in cfg.extensions.enabled:
        typer.echo(f"The {name} extension isn't on.")
        return
    enabled = tuple(n for n in cfg.extensions.enabled if n != name)
    config.save(replace(cfg, extensions=replace(cfg.extensions, enabled=enabled)))
    typer.echo(f"Turned off {name}. Its data stays; restart blunderbook serve.")


@ext_app.command("install")
def ext_install(name: Annotated[str, typer.Argument(help="The extension's name.")]) -> None:
    """Install an extension from the extensions folder of Blunderbook's git folder, and
    turn it on. Your other extensions stay installed."""
    if ext.find(name) is not None:
        typer.echo(f"The {name} extension is already installed.")
        ext_enable(name)
        return
    try:
        folder = update.source()
        here = update.available(folder)
        if not ext.NAME.fullmatch(name) or name not in here:
            listed = ", ".join(here) if here else "none"
            _fail(f"There's no extensions/{name} folder. Extensions here: {listed}.")
        uv = update.program("uv")
        command = update.uv_command(
            uv, folder, [*update.extension_specs(), str(folder / "extensions" / name)]
        )
        code = update.reinstall(command, done=f"Installed the {name} extension.", enable=name)
    except update.UpdateError as exc:
        _fail(f"{exc}")
    if update.WINDOWS:
        typer.echo(f"Installing {name} in a new window. It starts when this command ends.")
    raise typer.Exit(code)


# ---------------------------------------------------------------- update


@app.command("update")
def update_(
    check: Annotated[
        bool, typer.Option("--check", help="Only say what's new. Changes nothing.")
    ] = False,
) -> None:
    """Update Blunderbook and its extensions to the newest version of its git folder."""
    try:
        folder = update.source()
        uv = None if check else update.program("uv")
        pending = update.check(folder)
        for line in update.report(pending):
            typer.echo(line)
        if check:
            if pending.new:
                typer.echo("Run blunderbook update to install them.")
            return
        assert uv is not None
        if pending.new:
            typer.echo(f"Updated {folder} to {update.apply(folder)}.")
        else:
            typer.echo("Reinstalling it as it is, in case an earlier update didn't finish.")
        head = pending.upstream if pending.new else pending.head
        command = update.uv_command(uv, folder, update.extension_specs())
        code = update.reinstall(command, done=f"Blunderbook is up to date ({head}).")
    except update.UpdateError as exc:
        _fail(f"{exc}")
    if update.WINDOWS:
        typer.echo("Reinstalling in a new window. It starts when this command ends.")
    elif code != 0:
        typer.echo("The reinstall failed. Run blunderbook update again.", err=True)
    raise typer.Exit(code)


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
    lichess, chesscom = _ask_sync_accounts(cfg)

    cfg = replace(
        cfg,
        my_names=names,
        stockfish_path=stockfish_path,
        backup=replace(cfg.backup, dir=backup_dir),
        lichess=lichess,
        chesscom=chesscom,
    )
    saved = config.save(cfg)
    typer.echo(f"\nSaved to {saved}")

    db = config.db_path()
    existed = db.exists()
    with closing(_open_database("Your settings are saved, but the database isn't ready.", cfg)):
        pass
    if existed:
        typer.echo(f"Database {db}")
    typer.echo(
        "Next: blunderbook import FILE.pgn"
        + (" or blunderbook sync" if (cfg.lichess.username or cfg.chesscom.username) else "")
    )


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


def _ask_sync_accounts(cfg: config.Config) -> tuple[config.LichessConfig, config.ChesscomConfig]:
    """Your Lichess and Chess.com usernames, for `blunderbook sync` (both optional). They
    also tell Blunderbook which side you played."""
    typer.echo("\nSync (optional): your usernames, for blunderbook sync. Enter skips one.")
    lichess = _ask_text("Lichess username", cfg.lichess.username)
    chesscom = _ask_text("Chess.com username", cfg.chesscom.username)
    contact = cfg.chesscom.contact
    if chesscom:
        typer.echo(
            "Chess.com asks apps to say how to reach the person using them: an email address\n"
            "or a web page. It goes in each request to Chess.com, and nowhere else."
        )
        while True:
            contact = _ask_text("Contact for Chess.com", contact)
            if contact.isprintable():
                break
            typer.echo("Give it on one line.")
            contact = ""
    if lichess:
        typer.echo("A Lichess token is optional (it only downloads faster): token under [lichess].")
    return (
        replace(cfg.lichess, username=lichess),
        replace(cfg.chesscom, username=chesscom, contact=contact),
    )


def _ask_text(label: str, current: str) -> str:
    return str(typer.prompt(label, default=current, show_default=bool(current))).strip()


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
    problems += _doctor_ai(cfg)
    problems += _doctor_extensions(cfg)

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


def _doctor_ai(cfg: config.Config) -> int:
    """Print the AI row; return the number of problems. Never calls OpenRouter."""
    if not cfg.ai.enabled:
        _row("AI", "off")
        return 0
    problem = config.ai_problem(cfg)
    if problem is not None:
        _row("AI", f"Problem: {problem}")
        return 1
    _row("AI", f"on \N{MIDDLE DOT} {cfg.ai.model} \N{MIDDLE DOT} OpenRouter key set")
    return 0


def _doctor_extensions(cfg: config.Config) -> int:
    """Print the Extensions rows; return the number of problems."""
    if not cfg.extensions.enabled:
        _row("Extensions", "none on")
        return 0
    loaded = ext.load(cfg.extensions.enabled)
    label = "Extensions"
    for extension in loaded.extensions:
        _row(label, f"{extension.name} \N{MIDDLE DOT} {extension.title}")
        label = ""
    for problem in loaded.problems:
        _row(label, f"Problem: {problem}")
        label = ""
    return len(loaded.problems)


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
                decoded.text,
                config.all_names(cfg),
                side=my_side,
                known=repo.known_fingerprints(conn),
            )
        )
        if not queue:
            _fail(f"No games found in {path}.")

        try:
            queue, saved, error = _analyse(
                conn,
                cfg,
                queue,
                stockfish=stockfish,
                depth=depth,
                batch=importer.file_batch(path.name),
            )
        except _NoEngine as exc:
            _fail(str(exc))
        _print_report(queue, saved)
        if error is not None:
            _fail(
                f"Analysis stopped: {error}\n"
                "Import the file again to analyse the rest. Games already saved are skipped."
            )


class _NoEngine(Exception):
    """Some game is ready to analyse, but there's no Stockfish to use."""


def _analyse(
    conn: sqlite3.Connection,
    cfg: config.Config,
    queue: list[importer.QueuedGame],
    *,
    stockfish: str | None = None,
    depth: int | None = None,
    batch: Batch | None = None,
) -> tuple[list[importer.QueuedGame], dict[int, importer.SavedGame], str | None]:
    """Analyse and save the ready games, each as soon as it's done. Returns the queue, the
    saved games and the engine's error (None when all went well). Raises _NoEngine."""
    if not any(q.status == "ready" for q in queue):
        return queue, {}, None
    found = _find_engine(stockfish, cfg, probe=False)
    if found.problem is not None:
        raise _NoEngine(f"Can't analyse: {found.problem}")
    assert found.path is not None
    use_depth = depth or cfg.engine_depth
    saved: dict[int, importer.SavedGame] = {}
    error: str | None = None
    try:
        with engine.Engine.open(
            [str(found.path)], threads=cfg.engine_threads, hash_mb=cfg.engine_hash_mb
        ) as sf:
            typer.echo(f"Analysing with {sf.name} at depth {use_depth}.")
            _version_notes(sf.info)
            result = importer.run(
                conn,
                queue,
                sf,
                depth=use_depth,
                thresholds=cfg.thresholds,
                progress_for=lambda q, k, n: _Progress(f"Game {q.number} ({k} of {n})"),
                batch=batch,
            )
            queue, saved, error = list(result.queue), result.saved, result.error
    except engine.EngineError as exc:  # it couldn't start, or failed as it closed
        error = str(exc)
    return queue, saved, error


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


def _print_report(
    queue: list[importer.QueuedGame],
    saved: dict[int, importer.SavedGame],
    *,
    list_duplicates: bool = True,
) -> None:
    for queued in queue:
        if queued.status == "duplicate" and not list_duplicates:
            continue  # a sync downloads games you have again; the summary counts them
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


_MARKS = importer.MARKS


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
    details.append(
        f"entry #{entry_id}, missed win" if f.judgment == "missed" else f"entry #{entry_id}"
    )
    typer.echo("      " + " \N{MIDDLE DOT} ".join(details))
    if h.causes:
        typer.echo(f"      Suggested: {', '.join(h.causes)}")


def _seconds(value: float) -> str:
    whole = int(value)
    if whole >= 60:
        return f"{whole // 60}:{whole % 60:02d}"
    return f"{value:g} s"


class _Progress:
    """Positions done / total, redrawn on one line when the output is a terminal. Used as
    ``with _Progress(label) as report:``; the line is cleared at the end."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.live = sys.stderr.isatty()

    def __enter__(self) -> _Progress:
        return self

    def __exit__(self, *exc: object) -> None:
        self.done()

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

    You're the side to move. It's logged as a blunder, mistake, inaccuracy or missed win,
    by its cost.
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

    _daily_backup(cfg)
    problem = "Can't log the position: the database can't be used."
    with closing(_open_database(problem, cfg)) as conn:
        earlier = importer.find_logged(conn, queued)
        if earlier is not None:
            typer.echo(earlier.message)
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
                outcome = importer.log_fen(
                    conn, queued, sf, depth=cfg.engine_depth, thresholds=cfg.thresholds
                )
        except engine.EngineError as exc:
            _fail(f"Analysis stopped: {exc}\nNothing was logged.")

    if outcome.saved is None or outcome.entry_id is None:
        typer.echo(outcome.message)
        return
    (blunder,) = outcome.saved.analysed.blunders
    parts = [importer.FEN_LABEL, queued.players]
    if queued.date:
        parts.append(queued.date)
    parts.append(f"you played {queued.side.capitalize()}")
    typer.echo("")
    typer.echo(" \N{MIDDLE DOT} ".join(parts))
    _print_entry(blunder, outcome.entry_id)
    typer.echo("")
    typer.echo(outcome.message)


def _date_option(value: str | None) -> date:
    if value is None:
        return date.today()
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        _fail(f"--date needs a date like 2026-11-05, not {value!r}.")


# ---------------------------------------------------------------- serve

HOST = "127.0.0.1"  # this computer only: nothing else on the network can reach it (§10)
DEFAULT_PORT = 8732


@app.command()
def serve(
    port: Annotated[
        int, typer.Option(min=1, max=65535, help="The port on 127.0.0.1 to serve on.")
    ] = DEFAULT_PORT,
    open_: Annotated[
        bool, typer.Option("--open", help="Open the page in your browser once it's running.")
    ] = False,
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
        extensions = _serve_extensions(cfg)

        import uvicorn  # here, so the other commands start quickly

        from blunderbook.api.app import create_app

        server = uvicorn.Server(
            uvicorn.Config(
                create_app(config.db_path(), extensions),
                log_level="warning",
                access_log=False,
                timeout_graceful_shutdown=5,
            )
        )
        url = f"http://{HOST}:{port}/"
        typer.echo(f"Blunderbook is running at {url}")
        if open_:
            sock.listen()  # the browser's first request waits here until the server is up
            if _open_browser(url):
                typer.echo("Opened it in your browser. Press Ctrl+C to stop.")
            else:
                typer.echo("Couldn't open a browser. Open that address yourself.")
                typer.echo("Press Ctrl+C to stop.")
        else:
            typer.echo("Open that address in your browser. Press Ctrl+C to stop.")
        with suppress(KeyboardInterrupt):  # uvicorn stops cleanly, then raises Ctrl+C again
            server.run(sockets=[sock])
    finally:
        sock.close()
    typer.echo("Stopped.")


def _serve_extensions(cfg: config.Config) -> tuple[ext.Extension, ...]:
    """The extensions that are on and usable, their databases created or upgraded now. One
    that can't be loaded, or whose database can't be used, is a warning: the app runs
    without it."""
    loaded = ext.load(cfg.extensions.enabled)
    for problem in loaded.problems:
        _warn(problem)
    usable: list[ext.Extension] = []
    for extension in loaded.extensions:
        if ext.store(extension) is not None:

            def upgraded(path: Path, name: str = extension.name) -> None:
                typer.echo(f"Backed up the {name} extension's database before upgrading it:")
                typer.echo(f"  {path}")

            try:
                with closing(ext.open_db(extension, cfg, on_backup=upgraded)):
                    pass
            except connection.StorageError as exc:
                _warn(f"The {extension.name} extension is left out. {exc}")
                continue
        usable.append(extension)
    if usable:
        typer.echo("Extensions: " + ", ".join(e.title for e in usable))
    return tuple(usable)


def _warn(problem: str) -> None:
    typer.echo(f"Warning: {problem[0].lower()}{problem[1:]}", err=True)


def _open_browser(url: str) -> bool:
    import webbrowser

    try:
        return webbrowser.open(url)
    except webbrowser.Error:
        return False


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


# ---------------------------------------------------------------- print


@app.command("print")
def print_(
    out: Annotated[
        Path, typer.Option("--out", help="The .html file to write. Open it and print it on A4.")
    ],
    ids: Annotated[
        str | None,
        typer.Option(help="Only these entries, by number, in this order: --ids 3,12."),
    ] = None,
    due: Annotated[bool, typer.Option("--due", help="Only entries due for a re-test.")] = False,
) -> None:
    """Write your entries as an A4 page to print, two per page, like the paper Blunder Log."""
    if ids is not None and due:
        _fail("Use --ids or --due, not both.")
    wanted = _entry_ids(ids) if ids is not None else None
    cfg = _load_config()
    if not config.db_path().exists():
        _fail("Nothing to print yet: import a PGN first (blunderbook import FILE.pgn).")
    with closing(_open_database("Can't print: the database can't be used.", cfg)) as conn:
        if wanted is not None:
            entries = []
            for blunder_id in wanted:
                entry = repo.get_entry(conn, blunder_id)
                if entry is None:
                    _fail(f"No entry #{blunder_id}. Nothing was written.")
                entries.append(entry)
        else:
            entries = repo.list_entries(conn, due_by=date.today() if due else None)
    if not entries:
        _fail("Nothing is due for a re-test." if due else "No entries to print yet.")

    page = printing.render(entries, today=date.today())
    if not out.parent.is_dir():
        _fail(f"There's no folder {out.parent}. Nothing was written.")
    partial = out.with_name(out.name + ".partial")
    try:
        partial.write_text(page, "utf-8")
        partial.replace(out)
    except OSError as exc:
        partial.unlink(missing_ok=True)
        _fail(f"Can't write {out}: {exc.strerror or exc}")
    pages = -(-len(entries) // printing.PER_PAGE)
    typer.echo(f"Wrote {_plural(len(entries), 'entry')} ({_plural(pages, 'page')}) to {out}")
    typer.echo("Open it in your browser and print it on A4.")


def _entry_ids(raw: str) -> list[int]:
    """``"3, 12,3"`` -> ``[3, 12]``."""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts or not all(p.isdigit() for p in parts):
        _fail("--ids takes entry numbers separated by commas, e.g. --ids 3,12.")
    return list(dict.fromkeys(int(p) for p in parts))


# ---------------------------------------------------------------- sync


class _SyncSite(StrEnum):
    lichess = "lichess"
    chesscom = "chesscom"
    all = "all"


@app.command()
def sync(
    site: Annotated[
        _SyncSite,
        typer.Argument(help="lichess, chesscom, or all: each site with a username in config.toml."),
    ] = _SyncSite.all,
) -> None:
    """Download your new games from Lichess and Chess.com, then import them."""
    cfg = _load_config()
    choices: dict[_SyncSite, list[SyncSource]] = {
        _SyncSite.lichess: ["lichess"],
        _SyncSite.chesscom: ["chesscom"],
        _SyncSite.all: ["lichess", "chesscom"],
    }
    names = choices[site]
    chosen = [name for name in names if sources.username(name, cfg)]
    if site is not _SyncSite.all and not chosen:
        label = sources.SITES[names[0]]
        _fail(f"Set your {label} username under [{names[0]}] in config.toml.")
    if not chosen:
        _fail(
            "Nothing to sync: set your username under [lichess] or [chesscom] in config.toml,\n"
            "or run blunderbook init."
        )
    _daily_backup(cfg)
    failed = False
    with closing(_open_database("Can't sync: the database can't be used.", cfg)) as conn:
        for name in chosen:
            failed |= not _sync_site(conn, cfg, name)
    if failed:
        raise typer.Exit(1)


def _sync_site(conn: sqlite3.Connection, cfg: config.Config, name: SyncSource) -> bool:
    """Download one site's new games and import them. A problem is recorded in
    `sync_state.last_error` and printed; games saved before it stay. Returns False then."""
    label, user = sources.SITES[name], sources.username(name, cfg)
    state = repo.get_sync_state(conn, name)
    since = None
    if state is not None and state.username.casefold() == user.casefold():
        since = state.last_synced
    typer.echo("")
    if since is None:
        typer.echo(f"{label} ({user}): all your games.")
    else:
        typer.echo(f"{label} ({user}): games since {_local_time(since)}.")

    def failed(problem: str) -> bool:
        message = redact(problem, cfg.lichess.token)
        repo.record_sync(conn, name, username=user, error=message)
        typer.echo(f"{label}: {message}", err=True)
        return False

    texts: list[str] = []
    try:
        adapter = sources.adapter_for(name, cfg)
        with _Counting(f"{label}: downloading") as count:
            for text in adapter.fetch_new_pgn(since):
                texts.append(text)
                count(len(texts))
    except SyncError as exc:
        return failed(f"{exc} Nothing was imported from {label}.")
    if not texts:
        typer.echo("No new games.")
        repo.record_sync(conn, name, username=user)
        return True
    typer.echo(f"Downloaded {_plural(len(texts), 'game')}.")

    queue = list(
        importer.prepare(
            "\n\n".join(texts), config.all_names(cfg), known=repo.known_fingerprints(conn)
        )
    )
    try:
        queue, saved, error = _analyse(conn, cfg, queue, batch=importer.sync_batch(label))
    except _NoEngine as exc:
        return failed(f"{exc} Nothing was imported from {label}.")
    _print_report(queue, saved, list_duplicates=False)
    if error is not None:
        return failed(
            f"Analysis stopped: {error} Run the sync again to analyse the rest. "
            "Games already saved are skipped."
        )
    times = [t for q in queue if (t := game_time(q.headers)) is not None]
    repo.record_sync(conn, name, username=user, newest=max(times, default=None))
    return True


class _Counting:
    """Games downloaded so far, redrawn on one line when the output is a terminal."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.live = sys.stderr.isatty()

    def __enter__(self) -> _Counting:
        return self

    def __exit__(self, *exc: object) -> None:
        if self.live:
            sys.stderr.write("\r\033[K")
            sys.stderr.flush()

    def __call__(self, n: int) -> None:
        if self.live:
            sys.stderr.write(f"\r{self.label}: {_plural(n, 'game')}")
            sys.stderr.flush()


# ---------------------------------------------------------------- backup, restore


@app.command("backup")
def backup_(
    to: Annotated[
        Path | None,
        typer.Option("--to", metavar="FOLDER", help="Back up to this folder this time."),
    ] = None,
) -> None:
    """Back up the database now, and the databases of extensions that are on. Only the
    newest are kept (keep in config.toml)."""
    cfg = _load_config()
    folder = _backup_folder(cfg) if to is None else Path(os.path.abspath(to.expanduser()))
    for store, db in ext.databases(cfg):
        if store is not connection.CORE and not db.is_file():
            continue  # an extension that hasn't made its database yet
        try:
            snapshot = backup.take(db, folder, keep=cfg.backup.keep, store=store)
        except backup.BackupError as exc:
            _fail(str(exc) if store is connection.CORE else f"{store.label}: {exc}")
        what = "the database" if store is connection.CORE else f"{store.label}'s database"
        typer.echo(f"Backed up {what} to\n  {snapshot.backup.path}")
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
    store, db = _restore_target(path, cfg)
    try:
        backup.check_file(path, store)
    except backup.BackupError as exc:
        _fail(f"Can't restore {path}: {exc}\nNothing was changed.")

    _row("Backup", str(path))
    _row("", _describe_backup(path))
    _row("Database", str(db))
    _row("", _describe_database(db, store))
    if not yes:
        typer.echo("\nStop the web app (blunderbook serve) first if it's running.")
        try:
            go = typer.confirm("Replace your database with this backup?", default=False)
        except typer.Abort:
            go = False
        if not go:
            _fail("Nothing was changed.")

    try:
        result = backup.restore(path, db, folder, store=store)
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


def _restore_target(path: Path, cfg: config.Config) -> tuple[connection.Store, Path]:
    """Whose database a backup belongs to, from its name: Blunderbook's own, or that of an
    extension that's on. A file with another name is taken as Blunderbook's, and checked."""
    named = backup.parse_name(path)
    if named is None or named.store == connection.CORE.name:
        return connection.CORE, config.db_path()
    for store, db in ext.databases(cfg)[1:]:
        if store.name == named.store:
            return store, db
    _fail(
        f"{path.name} is a backup of the {named.store} extension's database, and that "
        f"extension isn't on. Turn it on first: blunderbook ext enable {named.store}\n"
        "Nothing was changed."
    )


def _daily_backup(cfg: config.Config) -> None:
    """The automatic backups before a command that changes data: Blunderbook's database and
    those of extensions that are on. They never stop the command."""
    if not cfg.backup.auto:
        return
    done = ext.daily_backups(cfg)
    for path in done.taken:
        typer.echo(f"Daily backup: {path}")
    for problem in done.problems:
        _warn(problem)


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


def _describe_database(db: Path, store: connection.Store = connection.CORE) -> str:
    if not db.exists():
        return "not created yet"
    if store is not connection.CORE:
        return f"holds {store.label}'s data now"
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
    note = engine.version_note(info)
    if note is not None:
        typer.echo(f"{indent}Note: {note}")


def _env_override_note() -> None:
    value = os.environ.get(config.STOCKFISH_ENV, "").strip()
    if value:
        typer.echo(
            f"Note: {config.STOCKFISH_ENV} is set ({value}), so it's used instead of "
            "config.toml until you unset it."
        )
