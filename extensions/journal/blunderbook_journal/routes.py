"""The Journal's routes, mounted at ``/api/ext/journal``: the notes list with search and
tags, one note with the tree Reading mode draws, and saving, pinning and deleting (ROADMAP
19.3); boards you play on, a line put into a game, and Analyse (19.4).

Every route that isn't a GET is for the Blunderbook page only (``host.same_origin``): those
that change something, and Analyse, which starts Stockfish. Your Log is only read, for the
``[[log 12]]`` and ``[[game 40]]`` links in a note. Nothing here goes online.
"""

import sqlite3
import threading
from datetime import date, datetime
from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from blunderbook import host
from blunderbook.core import pgn, timecontrol
from blunderbook.core.engine import EngineError
from blunderbook.core.models import Color, Entry, Game, Judgment, Speed, Status
from blunderbook_journal import doc, moves, store

router = APIRouter()

NO_NOTE: Final = "There's no such note. It may have been deleted."
MAX_BODY: Final = 1_000_000  # characters: a long book chapter is a tenth of this

MAX_MOVES: Final = 600  # half-moves played on a board at once
ANALYSE_LINES: Final = 3
BUSY: Final = "Stockfish is busy with another position. Try again when it's done."

Body = Annotated[str, Field(max_length=MAX_BODY)]
Fen = Annotated[str, Field(min_length=1, max_length=120)]
Ucis = Annotated[list[Annotated[str, Field(max_length=5)]], Field(max_length=MAX_MOVES)]

# One analysis at a time: a second press, or another window, is told to wait.
_analysing: Final = threading.Lock()


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


# ---------------------------------------------------------------- boards (19.4)


class BoardIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fen: Fen
    moves: Ucis = []


class PlayedOut(BaseModel):
    san: str
    uci: str
    fen: str  # after the move
    no: int
    white: bool


class BoardOut(BaseModel):
    start: str
    moves: list[PlayedOut]
    fen: str  # after the last move
    turn: Color
    legal: list[str]  # UCI, each promotion spelled out
    line: str  # "6. e3 Be7 7. Bd3"
    pgn: str  # the moves as a PGN game, with the start position when it isn't the usual
    over: str  # "Checkmate", "Stalemate", ... or ""


@router.post("/board", dependencies=[Depends(host.same_origin)])
def board(body: BoardIn) -> BoardOut:
    """Play moves from a FEN: each move's SAN and position, and what can be played next.
    Changes nothing. A FEN or move that can't be played is a 422 with the reason."""
    try:
        found = moves.position(body.fen, body.moves)
    except moves.BoardError as exc:
        raise HTTPException(422, str(exc)) from None
    return BoardOut(
        start=found.start,
        moves=[
            PlayedOut(san=m.san, uci=m.uci, fen=m.fen, no=m.no, white=m.white) for m in found.moves
        ],
        fen=found.fen,
        turn="white" if found.fen.split()[1] == "w" else "black",
        legal=list(found.legal),
        line=found.line,
        pgn=found.pgn,
        over=found.over,
    )


class LineIn(BaseModel):
    """A line played on the reading board, to put into a PGN block of the note."""

    model_config = ConfigDict(extra="forbid")
    block: int  # the PGN block's index in the note's tree
    after: int | None  # the move (its id in the tree) the line goes on from; None: the start
    moves: Annotated[
        list[Annotated[str, Field(max_length=5)]], Field(min_length=1, max_length=MAX_MOVES)
    ]


@router.post("/notes/{note_id}/lines", dependencies=[Depends(host.same_origin)])
def add_line(note_id: int, body: LineIn, db: host.ExtDb, log: host.Log) -> NoteOut:
    """Put a line into one of the note's games, as a variation (or as the game's own
    continuation when it goes on from its last move). The note is saved like an edit, so
    the text before is kept as a version. 409 when the game has that line already."""
    found = store.get(db, note_id)
    if found is None:
        raise HTTPException(404, NO_NOTE)
    tree = doc.parse(found.body)
    blocks: list[dict[str, Any]] = tree["blocks"]  # type: ignore[assignment]
    where = doc.sources(found.body).get(body.block)
    if not 0 <= body.block < len(blocks) or blocks[body.block]["t"] != "pgn" or where is None:
        raise HTTPException(422, "That game isn't in the note any more. Read the note again.")
    ids = _ids(blocks[body.block]["items"])
    if body.after is not None and body.after not in ids:
        raise HTTPException(422, "That move isn't in this game. Read the note again.")
    first, end = where
    lines = found.body.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    after = None if body.after is None else body.after - min(ids)
    try:
        text = moves.with_line("\n".join(lines[first:end]), after, body.moves)
    except moves.BoardError as exc:
        raise HTTPException(422, str(exc)) from None
    if text is None:
        raise HTTPException(409, "The game has that line already.")
    store.update(db, note_id, "\n".join([*lines[:first], text, *lines[end:]]))
    return _note_out(db, log, note_id)


def _ids(items: list[dict[str, Any]]) -> set[int]:
    """The move ids written in a PGN block, its variations included."""
    found: set[int] = set()
    for item in items:
        if "move" in item:
            found.add(item["move"])
        elif "line" in item:
            found |= _ids(item["line"])
    return found


class AnalyseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fen: Fen


class EngineLineOut(BaseModel):
    eval: dict[str, int]  # {"cp": 36} or {"mate": -2}, White's point of view
    uci: str  # the line's first move
    line: str  # "6. e3 Be7 7. Bd3 ...", up to 10 moves


class AnalyseOut(BaseModel):
    fen: str
    engine: str  # "Stockfish 17.1"; "" when the game is over and nothing was asked
    depth: int
    lines: list[EngineLineOut]  # best first
    over: str  # "Checkmate", "Stalemate", ... or ""


@router.post("/analyse", dependencies=[Depends(host.same_origin)])
def analyse(body: AnalyseIn) -> AnalyseOut:
    """Stockfish's best lines for a position, at your engine depth. Only when you press
    Analyse, and one at a time (409 while another runs). No Stockfish is a 503."""
    try:
        board = moves.board_at(body.fen)
    except moves.BoardError as exc:
        raise HTTPException(422, str(exc)) from None
    fen = board.fen()
    outcome = board.outcome(claim_draw=False)
    if outcome is not None:
        over = outcome.termination.name.replace("_", " ").capitalize()
        return AnalyseOut(fen=fen, engine="", depth=0, lines=[], over=over)
    if not _analysing.acquire(blocking=False):
        raise HTTPException(409, BUSY)
    try:
        depth = host.settings().engine_depth
        with host.engine() as engine:
            found = engine.lines(board, depth, multipv=ANALYSE_LINES)
            name = engine.name
    except (host.HostError, EngineError) as exc:
        raise HTTPException(503, str(exc)) from None
    finally:
        _analysing.release()
    return AnalyseOut(
        fen=fen,
        engine=name,
        depth=depth,
        lines=[
            EngineLineOut(
                eval={"mate": line.score.mate}
                if line.score.mate is not None
                else {"cp": line.score.cp or 0},
                uci=line.pv[0].uci(),
                line=moves.san_line(fen, [m.uci() for m in line.pv]),
            )
            for line in found
            if line.pv
        ],
        over="",
    )


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
