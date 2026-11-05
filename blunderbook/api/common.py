"""What the route modules share: one database connection per request, the 404 for a missing
entry, and small labels read from a game."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from typing import Annotated, NoReturn

from fastapi import Depends, HTTPException, Request

from blunderbook.core import timecontrol
from blunderbook.core.models import Entry, Game, TimeControl
from blunderbook.db import connection


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


def opponent(game: Game) -> str | None:
    return game.black if game.my_color == "white" else game.white


def tc_label(game: Game) -> str | None:
    if game.tc_base_s is None or game.tc_inc_s is None:
        return None
    return timecontrol.label(TimeControl(game.tc_base_s, game.tc_inc_s))
