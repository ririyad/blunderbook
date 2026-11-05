"""The Log's routes (CLAUDE.md §10): list, one entry with its game, your notes, delete."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import date
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from blunderbook.core import detect, pgn, timecontrol
from blunderbook.core.models import Color, Entry, Game, Source, Status, TimeControl
from blunderbook.db import connection, repo

from .schemas import Cause, EntryOut, EntrySummary, GameOut, MoveOut, NotesIn

router = APIRouter(prefix="/api/blunders", tags=["blunders"])


def db(request: Request) -> Iterator[sqlite3.Connection]:
    """One connection per request, closed when the request is done."""
    with closing(connection.connect(request.app.state.db_path, any_thread=True)) as conn:
        yield conn


Db = Annotated[sqlite3.Connection, Depends(db)]


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
    return _detail(_found(repo.get_entry(conn, blunder_id), blunder_id))


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
    return _detail(_found(entry, blunder_id))


@router.delete("/{blunder_id}", status_code=204)
def delete_blunder(blunder_id: int, conn: Db) -> Response:
    """Delete the entry and its re-test history. Its game stays, so it isn't imported again."""
    if not repo.delete_blunder(conn, blunder_id):
        _not_found(blunder_id)
    return Response(status_code=204)


# ---------------------------------------------------------------- shapes


def _found(entry: Entry | None, blunder_id: int) -> Entry:
    if entry is None:
        _not_found(blunder_id)
    return entry


def _not_found(blunder_id: int) -> NoReturn:
    raise HTTPException(status_code=404, detail=f"No entry #{blunder_id}.")


def _opponent(game: Game) -> str | None:
    return game.black if game.my_color == "white" else game.white


def _tc_label(game: Game) -> str | None:
    if game.tc_base_s is None or game.tc_inc_s is None:
        return None
    return timecontrol.label(TimeControl(game.tc_base_s, game.tc_inc_s))


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
        opponent=_opponent(g),
        played_on=g.played_on,
        speed=g.speed,
        tc_label=_tc_label(g),
    )


def _moves(game: Game) -> list[MoveOut]:
    """The mainline, read again from the stored PGN. It was read once to import it, so this
    only comes back empty if the stored text was changed by hand."""
    parsed = pgn.parse(game.pgn).games
    if len(parsed) != 1:
        return []
    return [
        MoveOut(
            ply=p.index, move_no=p.move_no, color=p.color, san=p.san, uci=p.uci, fen=p.fen_after
        )
        for p in parsed[0].plies
    ]


def _game(game: Game) -> GameOut:
    return GameOut(
        id=game.id,
        source=game.source,
        site_label=game.site_label,
        white=game.white,
        black=game.black,
        white_elo=game.white_elo,
        black_elo=game.black_elo,
        my_color=game.my_color,
        opponent=_opponent(game),
        result=game.result,
        played_on=game.played_on,
        time_control=game.time_control,
        tc_label=_tc_label(game),
        speed=game.speed,
        opening=game.opening,
        eco=game.eco,
        has_clocks=game.has_clocks,
        engine_name=game.engine_name,
        engine_depth=game.engine_depth,
        start_fen=game.start_fen,
        moves=_moves(game),
    )


def _detail(entry: Entry) -> EntryOut:
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
        game=_game(g),
    )
