"""What the route modules share: one database connection per request, the 404 for a missing
entry, and small labels read from a game."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from typing import Annotated, NoReturn

from fastapi import Depends, HTTPException, Request

from blunderbook.core import pgn, timecontrol
from blunderbook.core.models import Entry, Explanation, Game, Outcome, TimeControl
from blunderbook.db import connection

from .schemas import ExplanationOut, GameOut, MoveOut


def db(request: Request) -> Iterator[sqlite3.Connection]:
    """One connection per request, closed when the request is done."""
    with closing(connection.connect(request.app.state.db_path, any_thread=True)) as conn:
        yield conn


Db = Annotated[sqlite3.Connection, Depends(db)]


def found(entry: Entry | None, blunder_id: int) -> Entry:
    if entry is None:
        not_found(blunder_id)
    return entry


def not_found(blunder_id: int) -> NoReturn:
    raise HTTPException(status_code=404, detail=f"No entry #{blunder_id}.")


def same_origin(request: Request) -> None:
    """Only the page itself may start an import or ask for an explanation. Browsers send
    ``Origin`` with every POST; a request without one isn't from a web page."""
    origin = request.headers.get("origin")
    if origin is not None and origin != f"{request.url.scheme}://{request.headers.get('host')}":
        raise HTTPException(status_code=403, detail="Only the Blunderbook page can do this.")


def explanation_out(saved: Explanation | None) -> ExplanationOut | None:
    if saved is None:
        return None
    return ExplanationOut(text=saved.text, model=saved.model, created_at=saved.created_at)


def opponent(game: Game) -> str | None:
    return game.black if game.my_color == "white" else game.white


def opponent_elo(game: Game) -> int | None:
    return game.black_elo if game.my_color == "white" else game.white_elo


def outcome(game: Game) -> Outcome | None:
    """Won, lost or drawn from your side; None when the result is unknown."""
    if game.result == "1/2-1/2":
        return "drawn"
    if game.result in ("1-0", "0-1"):
        return "won" if (game.result == "1-0") == (game.my_color == "white") else "lost"
    return None


def moves(game: Game) -> list[MoveOut]:
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


def game_out(game: Game) -> GameOut:
    """A game as the Log's detail and the game page show it, with its moves."""
    return GameOut(
        id=game.id,
        source=game.source,
        site_label=game.site_label,
        white=game.white,
        black=game.black,
        white_elo=game.white_elo,
        black_elo=game.black_elo,
        my_color=game.my_color,
        opponent=opponent(game),
        result=game.result,
        played_on=game.played_on,
        time_control=game.time_control,
        tc_label=tc_label(game),
        speed=game.speed,
        opening=game.opening,
        eco=game.eco,
        has_clocks=game.has_clocks,
        engine_name=game.engine_name,
        engine_depth=game.engine_depth,
        start_fen=game.start_fen,
        moves=moves(game),
    )


def tc_label(game: Game) -> str | None:
    if game.tc_base_s is None or game.tc_inc_s is None:
        return None
    return timecontrol.label(TimeControl(game.tc_base_s, game.tc_inc_s))
