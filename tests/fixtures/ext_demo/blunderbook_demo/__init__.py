"""A test-only extension that uses every part of the contract (CLAUDE.md §15): routes, a
page, commands and a database of its own, reading your Log through the host API only."""

from contextlib import closing
from importlib.resources import files

import typer
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from blunderbook import ext, host

router = APIRouter()
commands = typer.Typer(no_args_is_help=True)


class MarkIn(BaseModel):
    blunder_id: int
    note: str


class MarkOut(BaseModel):
    id: int
    blunder_id: int
    played_san: str
    note: str


@router.get("/marks")
def list_marks(db: host.ExtDb, log: host.Log) -> list[MarkOut]:
    marks = []
    for row in db.execute("SELECT id, blunder_id, note FROM marks ORDER BY id"):
        entry = log.entry(row["blunder_id"])
        played = entry.blunder.played_san if entry is not None else "?"
        marks.append(
            MarkOut(id=row["id"], blunder_id=row["blunder_id"], played_san=played, note=row["note"])
        )
    return marks


@router.post("/marks", status_code=201, dependencies=[Depends(host.same_origin)])
def add_mark(mark: MarkIn, db: host.ExtDb, log: host.Log) -> MarkOut:
    entry = log.entry(mark.blunder_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"No entry #{mark.blunder_id}.")
    cursor = db.execute(
        "INSERT INTO marks (blunder_id, note) VALUES (?, ?)", (mark.blunder_id, mark.note)
    )
    assert cursor.lastrowid is not None
    return MarkOut(
        id=cursor.lastrowid,
        blunder_id=mark.blunder_id,
        played_san=entry.blunder.played_san,
        note=mark.note,
    )


@router.get("/settings")
def depth() -> dict[str, int]:
    return {"engine_depth": host.settings().engine_depth}


@commands.command("count")
def count() -> None:
    """Count your marks and your Log's entries."""
    with closing(host.open_db(extension)) as conn:
        marks = conn.execute("SELECT count(*) FROM marks").fetchone()[0]
    with host.read_log() as log:
        entries = len(log.entries())
    typer.echo(f"{marks} marks \N{MIDDLE DOT} {entries} entries in your Log")


extension = ext.Extension(
    name="demo",
    title="Demo",
    host_api=ext.HOST_API,
    router=router,
    web=files(__name__) / "web",
    migrations=files(__name__) / "migrations",
    cli=commands,
)
