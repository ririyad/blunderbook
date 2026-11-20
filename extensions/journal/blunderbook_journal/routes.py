"""The Journal's routes, mounted at ``/api/ext/journal`` (ROADMAP 19.3): the notes list with
search and tags, one note with the tree Reading mode draws, and saving, pinning and
deleting.

Every route that changes something is for the Blunderbook page only (``host.same_origin``).
Your Log is only read, for the ``[[log 12]]`` and ``[[game 40]]`` links in a note.
"""

import sqlite3
from datetime import date, datetime
from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from blunderbook import host
from blunderbook.core import pgn, timecontrol
from blunderbook.core.models import Color, Entry, Game, Judgment, Speed, Status
from blunderbook_journal import store

router = APIRouter()

NO_NOTE: Final = "There's no such note. It may have been deleted."
MAX_BODY: Final = 1_000_000  # characters: a long book chapter is a tenth of this

Body = Annotated[str, Field(max_length=MAX_BODY)]


class SummaryOut(BaseModel):
    id: int
    title: str  # "" until the note has a line of text
    snippet: str
    pinned: bool
    tags: list[str]
    updated_at: datetime


class TagOut(BaseModel):
    tag: str
    notes: int


class ListOut(BaseModel):
    notes: list[SummaryOut]  # pinned first, then the latest edited (or best match)
    tags: list[TagOut]  # every tag in use, most used first
    total: int  # all your notes, whatever the search


class RefMove(BaseModel):
    san: str
    uci: str
    fen: str  # after the move


class RefOut(BaseModel):
    """A ``[[log 12]]`` or ``[[game 40]]`` in the note, as your Log has it now."""

    kind: Literal["log", "game"]
    id: int
    found: bool  # False: the entry or game isn't in your Log (any more)
    game_id: int | None = None
    opponent: str | None = None
    my_color: Color | None = None
    speed: Speed | None = None
    tc_label: str | None = None  # "3+2"
    played_on: date | None = None
    result: str | None = None  # "1-0", from the game
    # An entry: your move ("6. Nxd5"), its judgment and its re-test status.
    move: str | None = None
    judgment: Judgment | None = None
    status: Status | None = None
    due_on: date | None = None
    played_uci: str | None = None
    best_uci: str | None = None
    # The board: an entry's position before your move, or a game's start and its moves.
    fen: str | None = None
    moves: list[RefMove] = []


class NoteOut(BaseModel):
    id: int
    title: str
    body: str  # as typed
    pinned: bool
    tags: list[str]
    created_at: datetime
    updated_at: datetime
    doc: dict[str, Any]  # the tree Reading mode draws (blunderbook_journal.doc)
    refs: list[RefOut]  # each Log link in the note, once, in the order written


class NewNoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: Body = ""


class PatchIn(BaseModel):
    """Only what's sent changes."""

    model_config = ConfigDict(extra="forbid")
    body: Body | None = None
    pinned: bool | None = None


@router.get("/notes")
def notes(db: host.ExtDb, q: str = "", tag: str = "") -> ListOut:
    """The notes, as the list shows them. ``q`` searches (only its first 200 characters);
    ``tag`` keeps one tag's notes."""
    return ListOut(
        notes=[
            SummaryOut(
                id=s.id,
                title=s.title,
                snippet=s.snippet,
                pinned=s.pinned,
                tags=list(s.tags),
                updated_at=s.updated_at,
            )
            for s in store.summaries(db, q=q[:200], tag=tag)
        ],
        tags=[TagOut(tag=t, notes=n) for t, n in store.all_tags(db)],
        total=store.count(db),
    )


@router.post("/notes", status_code=201, dependencies=[Depends(host.same_origin)])
def create(body: NewNoteIn, db: host.ExtDb, log: host.Log) -> NoteOut:
    return _note_out(db, log, store.create(db, body.body).id)


@router.get("/notes/{note_id}")
def note(note_id: int, db: host.ExtDb, log: host.Log) -> NoteOut:
    return _note_out(db, log, note_id)


@router.patch("/notes/{note_id}", dependencies=[Depends(host.same_origin)])
def change(note_id: int, body: PatchIn, db: host.ExtDb, log: host.Log) -> NoteOut:
    if store.get(db, note_id) is None:
        raise HTTPException(404, NO_NOTE)
    if body.body is not None:
        store.update(db, note_id, body.body)
    if body.pinned is not None:
        store.set_pinned(db, note_id, body.pinned)
    return _note_out(db, log, note_id)


@router.delete("/notes/{note_id}", status_code=204, dependencies=[Depends(host.same_origin)])
def delete(note_id: int, db: host.ExtDb) -> Response:
    if not store.delete(db, note_id):
        raise HTTPException(404, NO_NOTE)
    return Response(status_code=204)


# ---------------------------------------------------------------- building the answer


def _note_out(db: sqlite3.Connection, log: host.LogReader, note_id: int) -> NoteOut:
    found = store.get(db, note_id)
    tree = store.document(db, note_id)
    if found is None or tree is None:
        raise HTTPException(404, NO_NOTE)
    return NoteOut(
        id=found.id,
        title=found.title,
        body=found.body,
        pinned=found.pinned,
        tags=list(found.tags),
        created_at=found.created_at,
        updated_at=found.updated_at,
        doc=tree,
        refs=[_ref(log, kind, ref_id) for kind, ref_id in _links(tree)],
    )


def _links(tree: dict[str, Any]) -> list[tuple[str, int]]:
    """Every ``[[log N]]`` / ``[[game N]]`` in the tree, once each, in the order written."""
    found: dict[tuple[str, int], None] = {}

    def spans(items: list[dict[str, Any]]) -> None:
        for span in items:
            if span.get("t") == "ref":
                found[(span["kind"], span["id"])] = None

    for block in tree.get("blocks", []):
        if block["t"] == "ref":
            found[(block["kind"], block["id"])] = None
        spans(block.get("spans", []))
        for item in block.get("items", []):
            if isinstance(item, dict) and "spans" in item:
                spans(item["spans"])
    return list(found)


def _ref(log: host.LogReader, kind: str, ref_id: int) -> RefOut:
    if kind == "log":
        entry = log.entry(ref_id)
        return (
            _entry_ref(entry) if entry is not None else RefOut(kind="log", id=ref_id, found=False)
        )
    game = log.game(ref_id)
    if game is None or game.source == "fen":  # a FEN entry isn't a game (CLAUDE.md §5)
        return RefOut(kind="game", id=ref_id, found=False)
    return RefOut(
        kind="game",
        id=ref_id,
        found=True,
        **_game_fields(game),
        fen=game.start_fen,
        moves=_moves(game),
    )


def _entry_ref(entry: Entry) -> RefOut:
    b = entry.blunder
    side = "..." if entry.game.my_color == "black" else "."
    return RefOut(
        kind="log",
        id=b.id,
        found=True,
        **_game_fields(entry.game),
        move=f"{b.move_no}{side} {b.played_san}",
        judgment=b.judgment,
        status=b.status,
        due_on=b.due_on,
        played_uci=b.played_uci,
        best_uci=b.best_uci,
        fen=b.fen_before,
    )


def _game_fields(game: Game) -> dict[str, Any]:
    tc = timecontrol.parse(game.time_control)
    return {
        "game_id": game.id,
        "opponent": game.black if game.my_color == "white" else game.white,
        "my_color": game.my_color,
        "speed": game.speed,
        "tc_label": timecontrol.label(tc) if tc is not None else None,
        "played_on": game.played_on,
        "result": game.result,
    }


def _moves(game: Game) -> list[RefMove]:
    """The game's mainline, read again from its stored PGN, as the game page does."""
    parsed = pgn.parse(game.pgn).games
    if not parsed:
        return []
    return [RefMove(san=p.san, uci=p.uci, fen=p.fen_after) for p in parsed[0].plies]
