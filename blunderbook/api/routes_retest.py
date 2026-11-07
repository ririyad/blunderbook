"""The Re-test routes (CLAUDE.md §7.8, §10): the queue, an attempt, the hint.

The queue never sends the answer. The server checks every attempt against the stored
accepted moves, and only then sends the best move and your lesson.
"""

from datetime import date
from typing import Annotated

import chess
from fastapi import APIRouter, HTTPException, Query

from blunderbook.core import retest
from blunderbook.core.models import Entry
from blunderbook.db import repo

from .common import Db, explanation_out, found, not_found, opponent
from .schemas import AttemptIn, AttemptOut, HintOut, RetestItem, RetestQueue

router = APIRouter(prefix="/api/retest", tags=["retest"])


@router.get("/queue")
def queue(conn: Db, every: Annotated[bool, Query(alias="all")] = False) -> RetestQueue:
    """Entries due today or earlier, new ones included. ``all=1`` gives every entry, for
    "Practise all anyway"."""
    today = date.today()
    entries = repo.list_entries(conn, due_by=None if every else today)
    entries.sort(
        key=lambda e: retest.queue_key(e.blunder.due_on, e.game.played_on, e.game.id, e.blunder.ply)
    )
    return RetestQueue(
        items=[_item(entry) for entry in entries],
        total=repo.totals(conn).entries,
        next_due_on=repo.next_due_after(conn, today),
    )


@router.post("/{blunder_id}/attempt")
def attempt(blunder_id: int, body: AttemptIn, conn: Db) -> AttemptOut:
    """Check a move (or giving up), record it, and reschedule the entry."""
    entry = found(repo.get_entry(conn, blunder_id), blunder_id)
    fen = entry.blunder.fen_before
    move: chess.Move | None = None
    if body.move_uci is not None:
        move = retest.read_move(fen, body.move_uci)
        if move is None:
            raise HTTPException(
                status_code=422, detail=f"{body.move_uci!r} isn't a legal move in this position."
            )
    today = date.today()
    result = repo.record_attempt(
        conn,
        blunder_id,
        move_uci=None if move is None else move.uci(),
        used_hint=body.used_hint,
        today=today,
    )
    if result is None:  # deleted meanwhile
        not_found(blunder_id)
    entry, tried = result
    b = entry.blunder
    board = chess.Board(fen)
    return AttemptOut(
        id=b.id,
        solved=tried.solved,
        move_uci=tried.move_uci,
        move_san=None if move is None else board.san(move),
        move_fen=None if move is None else _after(board, move),
        best_uci=b.best_uci,
        best_san=b.best_san,
        best_line_san=b.best_line_san,
        played_uci=b.played_uci,
        played_san=b.played_san,
        refutation_san=b.refutation_san,
        judgment=b.judgment,
        lesson=b.lesson,
        status=b.status,
        streak=b.streak,
        due_on=b.due_on,
        next_in_days=(b.due_on - today).days,
        explanation=explanation_out(repo.get_explanation(conn, b.id)),
    )


@router.get("/{blunder_id}/hint")
def hint(blunder_id: int, conn: Db) -> HintOut:
    """Only the square the best move starts from. The attempt records whether you used it."""
    entry = found(repo.get_entry(conn, blunder_id), blunder_id)
    return HintOut(from_square=retest.from_square(entry.blunder.best_uci))


def _item(entry: Entry) -> RetestItem:
    b, g = entry.blunder, entry.game
    return RetestItem(
        id=b.id,
        fen=b.fen_before,
        my_color=g.my_color,
        move_no=b.move_no,
        legal_uci=retest.legal_uci(b.fen_before),
        source=g.source,
        site_label=g.site_label,
        opponent=opponent(g),
        played_on=g.played_on,
        due_on=b.due_on,
    )


def _after(board: chess.Board, move: chess.Move) -> str:
    after = board.copy(stack=False)
    after.push(move)
    return after.fen()
