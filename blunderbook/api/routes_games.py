"""The Games tab's routes (CLAUDE.md §10): the games you imported, and one game with its
moves and entries. FEN quick entries aren't games, so they aren't here."""

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query

from blunderbook.core.models import GameRow, ImportInfo, Outcome, Source, Speed
from blunderbook.db import repo

from .common import Db, game_out, opponent, opponent_elo, outcome, tc_label
from .schemas import GameDetail, GameEntryOut, GameSummary, ImportOut

router = APIRouter(prefix="/api/games", tags=["games"])


@router.get("")
def list_games(
    conn: Db,
    source: Source | None = None,
    result: Outcome | None = None,
    speed: Speed | None = None,
    blunders: Literal["with", "clean"] | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> list[GameSummary]:
    """Newest first; a game with no date by the day it was imported. ``result`` is from your
    side; ``blunders=clean`` keeps games with no entries; ``q`` searches the opponent, the
    opening and its ECO code."""
    rows = repo.list_games(
        conn,
        source=source,
        outcome=result,
        speed=speed,
        clean=None if blunders is None else blunders == "clean",
        text=q,
    )
    return [_summary(row) for row in rows]


@router.get("/{game_id}")
def get_game(game_id: int, conn: Db) -> GameDetail:
    row = repo.get_game_row(conn, game_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No game #{game_id}.")
    entries = repo.list_entries(conn, game_id=game_id)
    return GameDetail(
        game=game_out(row.game),
        outcome=outcome(row.game),
        imported_at=row.game.imported_at,
        batch=_batch(row.batch),
        entries=[
            GameEntryOut(
                id=e.blunder.id,
                ply=e.blunder.ply,
                move_no=e.blunder.move_no,
                played_san=e.blunder.played_san,
                judgment=e.blunder.judgment,
                status=e.blunder.status,
                due_on=e.blunder.due_on,
            )
            for e in entries
        ],
    )


def _batch(info: ImportInfo | None) -> ImportOut | None:
    if info is None:
        return None
    return ImportOut(id=info.id, label=info.label, kind=info.kind, started_at=info.started_at)


def _summary(row: GameRow) -> GameSummary:
    g = row.game
    return GameSummary(
        id=g.id,
        source=g.source,
        site_label=g.site_label,
        white=g.white,
        black=g.black,
        my_color=g.my_color,
        opponent=opponent(g),
        opponent_elo=opponent_elo(g),
        result=g.result,
        outcome=outcome(g),
        played_on=g.played_on,
        imported_at=g.imported_at,
        speed=g.speed,
        tc_label=tc_label(g),
        opening=g.opening,
        eco=g.eco,
        batch=_batch(row.batch),
        blunders=row.blunders,
        mistakes=row.mistakes,
        inaccuracies=row.inaccuracies,
    )
