"""The Library extension (CLAUDE.md §15, ROADMAP M11): openings, traps and tactics to study
and practise. Each is a TOML file under ``content/`` (see :mod:`blunderbook_library.content`).

So far (11.1) it has its content and two commands: ``blunderbook library check`` and
``blunderbook library list``. The page, practise and links to your Log come next.
"""

from collections import Counter
from pathlib import Path
from typing import Annotated

import typer

from blunderbook import ext
from blunderbook_library import content

commands = typer.Typer(no_args_is_help=True)

DOT = " \N{MIDDLE DOT} "


@commands.command("check")
def check(
    folder: Annotated[
        Path | None,
        typer.Argument(help="A content folder to check instead of the Library's own."),
    ] = None,
) -> None:
    """Check every entry: its fields, and that every line and answer is legal."""
    found = content.load(folder or content.FOLDER)
    for problem in found.problems:
        typer.echo(problem)
    fine = len(found.entries)
    if found.problems:
        count = len(found.problems)
        typer.echo(f"{fine} {_s(fine, 'entry', 'entries')} fine{DOT}{count} {_s(count, 'problem')}")
        raise typer.Exit(1)
    kinds = Counter(e.kind for e in found.entries)
    parts = [f"{kinds[k]} {plural}" for k, plural in content.KINDS.items()]
    typer.echo(f"Checked {fine} {_s(fine, 'entry', 'entries')}: {DOT.join(parts)}")
    typer.echo("Every line is legal, and every practise answer is a legal move.")


@commands.command("list")
def list_entries() -> None:
    """List the Library's entries."""
    found = content.load()
    for entry in found.entries:
        where = DOT.join(x for x in (entry.opening, entry.eco) if x)
        line = f"{entry.path:34} {entry.name}{DOT}{entry.side.capitalize()}"
        typer.echo(line + (DOT + where if where else ""))
    if found.problems:
        typer.echo(f"Left out {len(found.problems)}: run blunderbook library check")


def _s(n: int, one: str, many: str | None = None) -> str:
    return one if n == 1 else (many or one + "s")


extension = ext.Extension(
    name="library",
    title="Library",
    host_api=ext.HOST_API,
    cli=commands,
)
