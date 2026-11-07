"""Extensions for the extension tests (CLAUDE.md §15). Loaded through hand-made entry
points such as ``EntryPoint("sample", "ext_samples:sample", ext.GROUP)``."""

from pathlib import Path

import typer
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from blunderbook import ext, host

commands = typer.Typer(no_args_is_help=True)


@commands.command("hello")
def hello() -> None:
    """Say hello."""
    typer.echo("Hello from the sample extension.")


sample = ext.Extension(name="sample", title="Sample", host_api=ext.HOST_API, cli=commands)
other = ext.Extension(name="other", title="Other", host_api=ext.HOST_API)
reserved = ext.Extension(name="log", title="Log", host_api=ext.HOST_API)
bad_name = ext.Extension(name="Bad1", title="Bad", host_api=ext.HOST_API)
old_api = ext.Extension(name="old", title="Old", host_api=ext.HOST_API + 1)
not_an_extension = {"name": "plain"}

# An extension with routes, a page and a database of its own (9.2, 9.3), using only the
# host API.
NOTES = Path(__file__).parent / "fixtures" / "ext_notes"
NOTES_MIGRATIONS = NOTES / "migrations"
router = APIRouter()


class NoteIn(BaseModel):
    text: str


@router.get("/notes")
def list_notes(db: host.ExtDb) -> list[dict[str, object]]:
    return [dict(row) for row in db.execute("SELECT id, text FROM notes ORDER BY id")]


@router.post("/notes", status_code=201, dependencies=[Depends(host.same_origin)])
def add_note(note: NoteIn, db: host.ExtDb) -> dict[str, object]:
    cursor = db.execute("INSERT INTO notes (text) VALUES (?)", (note.text,))
    return {"id": cursor.lastrowid, "text": note.text}


@router.get("/log")
def log_count(log: host.Log) -> dict[str, int]:
    return {"entries": len(log.entries())}


@router.delete("/log")
def try_to_change_the_log(log: host.Log) -> None:
    log._conn.execute("DELETE FROM blunders")  # must fail: the Log is read-only


notes = ext.Extension(
    name="notes",
    title="Notes",
    host_api=ext.HOST_API,
    router=router,
    web=NOTES / "web",
    migrations=NOTES_MIGRATIONS,
)
no_view = ext.Extension(name="noview", title="No view", host_api=ext.HOST_API, web=NOTES)
no_migrations = ext.Extension(
    name="nomigrations", title="X", host_api=ext.HOST_API, migrations=NOTES / "missing"
)
