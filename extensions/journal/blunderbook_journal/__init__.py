"""The Journal extension (CLAUDE.md §15, ROADMAP M19): fast chess notes in Markdown, kept in
journal.db. In Reading mode every PGN, FEN and move in a sentence plays on a board.

It never goes online. Your Log is only read, for ``[[log 12]]`` and ``[[game 40]]`` links.

The parts: the database (:mod:`blunderbook_journal.store`), what a save reads from a note's
text (:mod:`blunderbook_journal.notes`), the tree Reading mode draws
(:mod:`blunderbook_journal.doc`, :mod:`blunderbook_journal.moves`), the Markdown export
(:mod:`blunderbook_journal.archive`), the tab's routes (:mod:`blunderbook_journal.routes`)
and page (``web/``), and four commands: ``new``, ``list``, ``show`` and ``export``.
"""

import os
import sqlite3
import sys
from contextlib import closing
from datetime import datetime
from importlib.resources import files
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from blunderbook import ext, host
from blunderbook_journal import archive, routes, store

commands = typer.Typer(no_args_is_help=True)

DOT = " \N{MIDDLE DOT} "
UNTITLED = "Untitled"


@commands.command("new")
def new(
    text: Annotated[str | None, typer.Argument(help="The note, in Markdown.")] = None,
    file: Annotated[
        Path | None,
        typer.Option("--file", help="Take the note from a Markdown file instead."),
    ] = None,
) -> None:
    """Write a new note: from TEXT, from --file, or piped in."""
    if text is not None and file is not None:
        _fail("Give the text or --file, not both.")
    if file is not None:
        try:
            body = file.read_text(encoding="utf-8-sig")
        except OSError as exc:
            _fail(f"Can't read {file}: {exc.strerror or exc}")
        except UnicodeDecodeError:
            _fail(f"{file} isn't UTF-8 text.")
    elif text is not None:
        body = text
    elif not sys.stdin.isatty():
        body = sys.stdin.read()
    else:
        _fail('Give the note: blunderbook journal new "# Title ..." or --file NOTE.md')
    if not body.strip():
        _fail("The note is empty.")
    _backup()
    with closing(_open()) as conn:
        note = store.create(conn, body)
    typer.echo(f"Note #{note.id}: {note.title or UNTITLED}{_tags(note.tags)}")


@commands.command("list")
def list_notes(
    search: Annotated[str, typer.Option("--search", "-s", help="Words to find in the notes.")] = "",
    tag: Annotated[str, typer.Option("--tag", "-t", help="Only the notes with this tag.")] = "",
) -> None:
    """List your notes, pinned first, then the latest edited."""
    with closing(_open()) as conn:
        found = store.summaries(conn, q=search, tag=tag)
        total = conn.execute("SELECT count(*) FROM notes").fetchone()[0]
    if not found:
        typer.echo(
            "No notes match."
            if total
            else 'No notes yet. Write one: blunderbook journal new "# Title"'
        )
        return
    width = len(str(max(s.id for s in found)))
    for summary in found:
        parts = [summary.title or UNTITLED]
        if summary.pinned:
            parts.append("pinned")
        if summary.tags:
            parts.append(" ".join(f"#{t}" for t in summary.tags))
        parts.append(_day(summary.updated_at))
        typer.echo(f"#{summary.id:<{width}}  {DOT.join(parts)}")
    shown = f"{len(found)} of {total} notes" if len(found) != total else f"{total} notes"
    typer.echo(shown if total != 1 else "1 note")


@commands.command("show")
def show(note_id: Annotated[int, typer.Argument(metavar="ID", help="The note's number.")]) -> None:
    """Print a note's text, as you wrote it."""
    with closing(_open()) as conn:
        note = store.get(conn, note_id)
    if note is None:
        _fail(f"No note #{note_id}. See them with: blunderbook journal list")
    typer.echo(note.body, nl=not note.body.endswith("\n"))


@commands.command("export")
def export(
    folder: Annotated[Path, typer.Argument(help="Where the .md files go; made if missing.")],
) -> None:
    """Write every note to FOLDER as a Markdown file, named by its number and title.
    Exporting again replaces those files and touches nothing else there."""
    with closing(_open()) as conn:
        everything = store.every_note(conn)
    if not everything:
        typer.echo("No notes yet: nothing to export.")
        return
    try:
        folder.mkdir(parents=True, exist_ok=True)
        for note in everything:
            path = folder / archive.file_name(note)
            path.write_text(note.body, encoding="utf-8", newline="")
            stamp = note.updated_at.timestamp()
            os.utime(path, (stamp, stamp))
    except OSError as exc:
        _fail(f"Can't write to {folder}: {exc.strerror or exc}")
    count = len(everything)
    typer.echo(f"Exported {count} {'note' if count == 1 else 'notes'} to {folder}")


def _tags(found: tuple[str, ...]) -> str:
    return DOT + " ".join(f"#{t}" for t in found) if found else ""


def _day(moment: datetime) -> str:
    local = moment.astimezone()
    return f"{local.day} {local:%b %Y}"


def _backup() -> None:
    try:
        done = host.daily_backup()
    except host.HostError as exc:
        _fail(str(exc))
    for taken in done.taken:
        typer.echo(f"Daily backup: {taken}")
    for problem in done.problems:
        typer.echo(f"Warning: {problem}", err=True)


def _open() -> sqlite3.Connection:
    try:
        return host.open_db(extension)
    except (host.HostError, host.StorageError) as exc:
        _fail(f"Can't use the journal database.\n{exc}")


def _fail(message: str) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(1)


extension = ext.Extension(
    name="journal",
    title="Journal",
    host_api=ext.HOST_API,
    router=routes.router,
    web=files(__name__) / "web",
    migrations=files(__name__) / "migrations",
    cli=commands,
)
