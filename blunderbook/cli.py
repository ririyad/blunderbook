"""Command-line interface.

Commands arrive milestone by milestone (see the README roadmap):
init, doctor, import (M1) · fen (M2) · serve (M3) · sync (M6) · print (M7).
"""

from typing import Annotated

import typer

from blunderbook import __version__

app = typer.Typer(
    name="blunderbook",
    help="Your chess mistake library.",
    no_args_is_help=True,
    add_completion=False,
)


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
