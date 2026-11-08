"""The Library's routes (ROADMAP 11.2), mounted at ``/api/ext/library``: the index and one
entry, with the FEN after every move so the page needs no chess logic (as in core).

Practise answers are never sent here. 11.3 serves the practise positions, and an answer
only comes back after an attempt, as in core's Re-test (CLAUDE.md §10).
"""

from functools import cache
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from blunderbook_library import content

router = APIRouter()


class EntrySummary(BaseModel):
    id: str
    kind: content.Kind
    name: str
    side: content.Side  # the side you practise as; the board faces it
    opening: str | None
    eco: str | None


class MoveOut(BaseModel):
    label: str  # "5. Nxe5", "5... Bxd1"
    san: str
    uci: str
    move_no: int
    color: Literal["white", "black"]  # the side that played it
    fen: str  # the position after it


class NextOut(BaseModel):
    """A reply at the end of the line: the reply first, then what follows it."""

    moves: list[MoveOut]
    says: str
    loses: bool


class EntryDetail(EntrySummary):
    idea: str
    start_fen: str
    moves: list[MoveOut]
    next: list[NextOut]


@cache
def entries() -> dict[str, content.Entry]:
    """The shipped entries, read and checked once. One with a problem is left out, as
    ``blunderbook library list`` does; ``blunderbook library check`` says why."""
    return {entry.id: entry for entry in content.load().entries}


@router.get("/entries")
def list_entries() -> list[EntrySummary]:
    """Every entry: openings, traps, then tactics, each by file name."""
    return [_summary(entry) for entry in entries().values()]


@router.get("/entries/{entry_id}")
def get_entry(entry_id: str) -> EntryDetail:
    entry = entries().get(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"There's no {entry_id!r} in the Library.")
    return EntryDetail(
        **_summary(entry).model_dump(),
        idea=entry.idea,
        start_fen=entry.start_fen,
        moves=_moves(entry.start_fen, entry.moves),
        next=[
            NextOut(moves=_moves(entry.end_fen, (n.move, *n.line)), says=n.says, loses=n.loses)
            for n in entry.next
        ],
    )


def _summary(entry: content.Entry) -> EntrySummary:
    return EntrySummary(
        id=entry.id,
        kind=entry.kind,
        name=entry.name,
        side=entry.side,
        opening=entry.opening,
        eco=entry.eco,
    )


def _moves(start_fen: str, moves: tuple[content.Move, ...]) -> list[MoveOut]:
    fens = content.positions(start_fen, moves)
    out = []
    for move, fen in zip(moves, fens[1:], strict=True):
        number, _, _ = move.label.partition(".")
        color: Literal["white", "black"] = "black" if "..." in move.label else "white"
        out.append(
            MoveOut(
                label=move.label,
                san=move.san,
                uci=move.uci,
                move_no=int(number),
                color=color,
                fen=fen,
            )
        )
    return out
