"""The Log's routes (CLAUDE.md §10): list, one entry with its game, your notes, delete."""

import sqlite3
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Response

from blunderbook.core import detect
from blunderbook.core.models import Color, Entry, Source, Status
from blunderbook.db import repo

from .common import Db, explanation_out, found, game_out, not_found, opponent, tc_label
from .schemas import Cause, EntryOut, EntrySummary, NotesIn

router = APIRouter(prefix="/api/blunders", tags=["blunders"])


@router.get("")
def list_blunders(
    conn: Db,
    source: Source | None = None,
    status: Annotated[list[Status] | None, Query()] = None,
    cause: Cause | None = None,
    due: bool = False,
) -> list[EntrySummary]:
    """The Log, newest first. ``status`` can be given more than once; ``due=1`` keeps
    entries due today or earlier."""
    entries = repo.list_entries(
        conn,
        source=source,
        statuses=status or (),
        cause=cause,
        due_by=date.today() if due else None,
    )
    return [_summary(entry) for entry in entries]


@router.get("/{blunder_id}")
def get_blunder(blunder_id: int, conn: Db) -> EntryOut:
    return _detail(conn, found(repo.get_entry(conn, blunder_id), blunder_id))


@router.patch("/{blunder_id}")
def update_blunder(blunder_id: int, notes: NotesIn, conn: Db) -> EntryOut:
    entry = repo.update_notes(
        conn,
        blunder_id,
        causes=notes.causes,
        other_cause=notes.other_cause,
        thinking=notes.thinking,
        lesson=notes.lesson,
    )
    return _detail(conn, found(entry, blunder_id))


@router.delete("/{blunder_id}", status_code=204)
def delete_blunder(blunder_id: int, conn: Db) -> Response:
    """Delete the entry and its re-test history. Its game stays, so it isn't imported again."""
    if not repo.delete_blunder(conn, blunder_id):
        not_found(blunder_id)
    return Response(status_code=204)


# ---------------------------------------------------------------- shapes


def _summary(entry: Entry) -> EntrySummary:
    b, g = entry.blunder, entry.game
    return EntrySummary(
        id=b.id,
        source=g.source,
        my_color=g.my_color,
        move_no=b.move_no,
        played_san=b.played_san,
        judgment=b.judgment,
        status=b.status,
        due_on=b.due_on,
        opponent=opponent(g),
        played_on=g.played_on,
        speed=g.speed,
        tc_label=tc_label(g),
    )


def _detail(conn: sqlite3.Connection, entry: Entry) -> EntryOut:
    b, g = entry.blunder, entry.game
    me = g.my_color
    them: Color = "black" if me == "white" else "white"
    return EntryOut(
        id=b.id,
        ply=b.ply,
        move_no=b.move_no,
        fen_before=b.fen_before,
        played_uci=b.played_uci,
        played_san=b.played_san,
        best_uci=b.best_uci,
        best_san=b.best_san,
        best_line_san=b.best_line_san,
        refutation_san=b.refutation_san,
        eval_before=b.eval_before.to_dict(),
        eval_after=b.eval_after.to_dict(),
        chances_before=detect.chances(b.eval_before, me, me),
        chances_after=detect.chances(b.eval_after, them, me),
        swing=b.swing,
        judgment=b.judgment,
        clock_left_s=b.clock_left_s,
        time_spent_s=b.time_spent_s,
        auto_causes=list(b.auto_causes),
        causes=list(b.causes),
        other_cause=b.other_cause,
        thinking=b.thinking,
        lesson=b.lesson,
        status=b.status,
        streak=b.streak,
        due_on=b.due_on,
        created_at=b.created_at,
        updated_at=b.updated_at,
        game=game_out(g),
        explanation=explanation_out(repo.get_explanation(conn, b.id)),
    )
