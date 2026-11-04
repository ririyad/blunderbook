"""Command-line interface.

Commands arrive milestone by milestone (see the README roadmap):
engine (1.3) · init, doctor, import (1.9) · fen (M2) · serve (M3) · sync (M6) · print (M7).
"""

import os
from dataclasses import replace
from typing import Annotated, NoReturn

import typer

from blunderbook import __version__, config
from blunderbook.core import engine

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
    cfg = _load_config()
    location = config.locate_stockfish(config=cfg, config_dir=config.config_path().parent)
    if location.path is None or location.origin is None:
        _fail(location.problem or config.NOT_FOUND)
    try:
        info = engine.probe([str(location.path)])
    except engine.EngineError as exc:
        _fail(f"Can't use {location.path}: {exc}")
    typer.echo(info.name)
    typer.echo(f"Path  {location.path}")
    typer.echo(f"From  {config.ORIGIN_LABELS[location.origin]}")
    _version_notes(info)


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


# ---------------------------------------------------------------- helpers


def _load_config() -> config.Config:
    try:
        return config.load(config.config_path())
    except config.ConfigError as exc:
        _fail(str(exc))


def _fail(message: str) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(1)


def _version_notes(info: engine.EngineInfo) -> None:
    if info.outdated:
        typer.echo(
            f"Note: Blunderbook expects Stockfish {engine.MIN_STOCKFISH_MAJOR} or newer. "
            "Older versions can judge positions differently."
        )
    elif info.dev_build:
        typer.echo("Note: this looks like a development build, so its version can't be checked.")


def _env_override_note() -> None:
    value = os.environ.get(config.STOCKFISH_ENV, "").strip()
    if value:
        typer.echo(
            f"Note: {config.STOCKFISH_ENV} is set ({value}), so it's used instead of "
            "config.toml until you unset it."
        )
