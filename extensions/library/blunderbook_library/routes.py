"""The Library's routes, mounted at ``/api/ext/library``: the index and one entry (ROADMAP
11.2), practise (11.3), and your Log entries from games in an entry's opening (11.4, read
through ``host.Log``, which can't change your Log). Every move comes with the FEN after it,
so the page needs no chess logic (as in core).

Practise is core's Re-test, for the Library's positions (CLAUDE.md §7.8, §10): the queue never
sends an answer, nor the entry's idea (it gives the answer away). The server checks every
attempt, and only then sends the answers.
"""

from datetime import date
from functools import cache
from typing import Annotated, Literal

import chess
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from blunderbook import host
from blunderbook.core import retest
from blunderbook.core.models import Judgment, Source, Status
from blunderbook_library import content, progress, yours

router = APIRouter()

type Color = Literal["white", "black"]
type PositionStatus = Literal["new", "solved", "missed"]


def today() -> date:
    """Your local day, as core's Re-test uses. A test can replace it."""
    return date.today()


# ---------------------------------------------------------------- the entries


class Counts(BaseModel):
    """Your practise of one entry's positions."""

    positions: int
    tried: int
    solved: int  # solved the last time you tried
    due: int  # due today or earlier, new ones included


class EntrySummary(BaseModel):
    id: str
    kind: content.Kind
    name: str
    side: content.Side  # the side you practise as; the board faces it
    opening: str | None
    eco: str | None
    practise: Counts


class MoveOut(BaseModel):
    label: str  # "5. Nxe5", "5... Bxd1"
    san: str
    uci: str
    move_no: int
    color: Color  # the side that played it
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
def list_entries(db: host.ExtDb) -> list[EntrySummary]:
    """Every entry: openings, traps, then tactics, each by file name."""
    tried, day = progress.all_progress(db), today()
    return [_summary(entry, tried, day) for entry in entries().values()]


@router.get("/entries/{entry_id}")
def get_entry(entry_id: str, db: host.ExtDb) -> EntryDetail:
    entry = _entry(entry_id)
    return EntryDetail(
        **_summary(entry, progress.all_progress(db), today()).model_dump(),
        idea=entry.idea,
        start_fen=entry.start_fen,
        moves=_moves(entry.start_fen, entry.moves),
        next=[
            NextOut(moves=_moves(entry.end_fen, (n.move, *n.line)), says=n.says, loses=n.loses)
            for n in entry.next
        ],
    )


# ---------------------------------------------------------------- from your Log


class LogEntryOut(BaseModel):
    """One of your Log entries, from a game that reached the Library entry's position."""

    id: int  # the Log entry: #log/<id>
    move: str  # "5... Bxd1", your move
    judgment: Judgment
    status: Status  # its Re-test status
    source: Source
    opponent: str | None
    played_on: date | None
    fell_in: bool  # you played one of the entry's losing replies, there
    on_line: bool  # the mistake was on the entry's line itself


@router.get("/entries/{entry_id}/log")
def from_log(entry_id: str, log: host.Log) -> list[LogEntryOut]:
    """Your Log entries from games that reached this entry's position, newest first."""
    entry = _entry(entry_id)
    out = []
    for m in yours.matches(entry, log.entries()):
        b, g = m.log.blunder, m.log.game
        out.append(
            LogEntryOut(
                id=b.id,
                move=f"{b.move_no}{'.' if g.my_color == 'white' else '...'} {b.played_san}",
                judgment=b.judgment,
                status=b.status,
                source=g.source,
                opponent=g.black if g.my_color == "white" else g.white,
                played_on=g.played_on,
                fell_in=m.fell_in,
                on_line=m.on_line,
            )
        )
    return out


# ---------------------------------------------------------------- practise


class PractiseItem(BaseModel):
    """One position to practise. It never carries an answer or the entry's idea."""

    entry_id: str
    n: int  # the entry's [[practise]] number, from 1
    name: str
    kind: content.Kind
    side: content.Side  # the side to move, and the way the board faces
    fen: str
    prompt: str
    last_move: str | None  # "5. Nxe5": the line's move that led here; None at its start
    legal_uci: list[str]  # every legal move, for tap-to-move
    status: PositionStatus
    due_on: date


class PractiseQueue(BaseModel):
    items: list[PractiseItem]  # due first (oldest first), then in the Library's order
    total: int  # every position the queue could hold, for "Practise all anyway"
    next_due_on: date | None  # the first one due after today


class AttemptIn(BaseModel):
    """Your move, or ``null`` when you gave up ("I don't know — show me")."""

    model_config = ConfigDict(extra="forbid")

    move_uci: str | None
    used_hint: bool = False


class ReplyOut(BaseModel):
    """A reply from the entry's ``[[next]]``, with what follows it."""

    move: str  # "5... Bxd1"
    line: str  # "6. Bxf7+ Ke7 7. Nd5#", or "" when nothing follows
    says: str
    loses: bool


class AttemptOut(BaseModel):
    """The answer, sent only after you tried."""

    solved: bool
    move_uci: str | None  # your move as recorded (a bare promotion becomes a queen)
    move_san: str | None
    move_fen: str | None  # the position after your move; null when you gave up
    answer_uci: str  # the answer you found, or the first one when you didn't
    answer_san: str
    answers: list[str]  # every move counted as right (SAN)
    line_next: str | None  # "2... d6": the line's own move, when you found another
    your_reply: ReplyOut | None  # what the entry says about your move, when it says
    answer_reply: ReplyOut | None  # and about the answer, when that's another move
    idea: str
    status: Literal["solved", "missed"]
    streak: int
    due_on: date
    next_in_days: int


class HintOut(BaseModel):
    from_square: str  # "d6": where the first answer starts


@router.get("/practise")
def queue(
    db: host.ExtDb,
    entry_id: Annotated[str | None, Query(alias="entry")] = None,
    every: Annotated[bool, Query(alias="all")] = False,
) -> PractiseQueue:
    """The positions due today or earlier, new ones included. ``all=1`` gives every
    position; ``entry=legal-trap`` every position of one entry, in its order."""
    tried, day = progress.all_progress(db), today()
    scope = [_entry(entry_id)] if entry_id is not None else list(entries().values())
    found = [
        (entry, n, practise, tried.get((entry.id, practise.fen)))
        for entry in scope
        for n, practise in enumerate(entry.practise, 1)
    ]

    def due_on(p: progress.Progress | None) -> date:
        return day if p is None else p.due_on

    if entry_id is None:
        chosen = [f for f in found if every or due_on(f[3]) <= day]
        chosen.sort(key=lambda f: due_on(f[3]))  # stable: the Library's order within a day
    else:
        chosen = found
    later = [p.due_on for *_, p in found if p is not None and p.due_on > day]
    return PractiseQueue(
        items=[_item(entry, n, practise, p, day) for entry, n, practise, p in chosen],
        total=len(found),
        next_due_on=min(later, default=None),
    )


@router.post("/practise/{entry_id}/{n}/attempt", dependencies=[Depends(host.same_origin)])
def attempt(entry_id: str, n: int, body: AttemptIn, db: host.ExtDb) -> AttemptOut:
    """Check a move (or giving up), record it, and reschedule the position."""
    entry, practise = _position(entry_id, n)
    move: chess.Move | None = None
    if body.move_uci is not None:
        move = retest.read_move(practise.fen, body.move_uci)
        if move is None:
            raise HTTPException(
                status_code=422, detail=f"{body.move_uci!r} isn't a legal move in this position."
            )
    played = None if move is None else move.uci()
    solved = retest.is_solved(played, [a.uci for a in practise.answers])
    day = today()
    after = progress.record(
        db,
        (entry.id, practise.fen),
        move_uci=played,
        solved=solved,
        used_hint=body.used_hint,
        today=day,
    )
    answer = practise.answers[0]
    if solved and played is not None:
        answer = next(a for a in practise.answers if retest.is_solved(played, [a.uci]))
    board = chess.Board(practise.fen)
    at_end = practise.ply == len(entry.moves)
    # When you found another right move than the line's own, say how the line goes on.
    line_move = None if at_end else entry.moves[practise.ply]
    goes_on = line_move is not None and solved and answer.uci != line_move.uci
    your_reply = _reply(entry, played) if at_end else None
    answer_reply = _reply(entry, answer.uci) if at_end else None
    if your_reply is not None and answer_reply == your_reply:
        answer_reply = None
    return AttemptOut(
        solved=solved,
        move_uci=played,
        move_san=None if move is None else board.san(move),
        move_fen=None if move is None else _after(board, move),
        answer_uci=answer.uci,
        answer_san=answer.san,
        answers=[a.san for a in practise.answers],
        line_next=line_move.label if goes_on and line_move is not None else None,
        your_reply=your_reply,
        answer_reply=answer_reply,
        idea=entry.idea,
        status=after.status,
        streak=after.streak,
        due_on=after.due_on,
        next_in_days=(after.due_on - day).days,
    )


@router.get("/practise/{entry_id}/{n}/hint")
def hint(entry_id: str, n: int) -> HintOut:
    """Only the square the first answer starts from. The attempt records whether you used
    it."""
    _, practise = _position(entry_id, n)
    return HintOut(from_square=retest.from_square(practise.answers[0].uci))


# ---------------------------------------------------------------- helpers


def _entry(entry_id: str) -> content.Entry:
    entry = entries().get(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"There's no {entry_id!r} in the Library.")
    return entry


def _position(entry_id: str, n: int) -> tuple[content.Entry, content.Practise]:
    entry = _entry(entry_id)
    if not 1 <= n <= len(entry.practise):
        raise HTTPException(status_code=404, detail=f"{entry.name} has no practise position {n}.")
    return entry, entry.practise[n - 1]


def _summary(
    entry: content.Entry, tried: dict[progress.Key, progress.Progress], day: date
) -> EntrySummary:
    mine = [tried.get((entry.id, p.fen)) for p in entry.practise]
    return EntrySummary(
        id=entry.id,
        kind=entry.kind,
        name=entry.name,
        side=entry.side,
        opening=entry.opening,
        eco=entry.eco,
        practise=Counts(
            positions=len(mine),
            tried=sum(p is not None for p in mine),
            solved=sum(p is not None and p.status == "solved" for p in mine),
            due=sum(p is None or p.due_on <= day for p in mine),
        ),
    )


def _item(
    entry: content.Entry,
    n: int,
    practise: content.Practise,
    tried: progress.Progress | None,
    day: date,
) -> PractiseItem:
    return PractiseItem(
        entry_id=entry.id,
        n=n,
        name=entry.name,
        kind=entry.kind,
        side=entry.side,
        fen=practise.fen,
        prompt=practise.prompt,
        last_move=entry.moves[practise.ply - 1].label if practise.ply else None,
        legal_uci=retest.legal_uci(practise.fen),
        status="new" if tried is None else tried.status,
        due_on=day if tried is None else tried.due_on,
    )


def _reply(entry: content.Entry, uci: str | None) -> ReplyOut | None:
    """The entry's ``[[next]]`` reply that is this move, if there is one."""
    for n in entry.next:
        if uci is not None and retest.is_solved(uci, [n.move.uci]):
            return ReplyOut(move=n.move.label, line=_line_text(n.line), says=n.says, loses=n.loses)
    return None


def _line_text(moves: tuple[content.Move, ...]) -> str:
    """ "6. Bxf7+ Ke7 7. Nd5#": a number before White's moves, and before the first."""
    return " ".join(
        m.label if i == 0 or "..." not in m.label else m.san for i, m in enumerate(moves)
    )


def _moves(start_fen: str, moves: tuple[content.Move, ...]) -> list[MoveOut]:
    fens = content.positions(start_fen, moves)
    out = []
    for move, fen in zip(moves, fens[1:], strict=True):
        number, _, _ = move.label.partition(".")
        color: Color = "black" if "..." in move.label else "white"
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


def _after(board: chess.Board, move: chess.Move) -> str:
    after = board.copy(stack=False)
    after.push(move)
    return after.fen()
