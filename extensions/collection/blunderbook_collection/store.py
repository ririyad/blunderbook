"""collection.db (ROADMAP 12.1, ``migrations/0001_collections.sql``). All of the Collection's
SQL is here, with every value a parameter.

A game is analysed once and kept by its fingerprint; ``members`` puts it in collections.
"""

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from blunderbook.core.models import Eval
from blunderbook_collection.games import GameInfo, Position


@dataclass(frozen=True, slots=True)
class CollectionRow:
    id: int
    name: str
    created_at: str
    games: int


@dataclass(frozen=True, slots=True)
class GameRow:
    id: int
    white: str | None
    black: str | None
    result: str | None
    date: str | None
    event: str | None
    eco: str | None
    opening: str | None
    plies: int
    engine_name: str
    engine_depth: int


def now() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------- reading


def analysed(conn: sqlite3.Connection) -> dict[str, int]:
    """Every analysed game's fingerprint, and its id."""
    return {row[0]: row[1] for row in conn.execute("SELECT fingerprint, id FROM games")}


def find(conn: sqlite3.Connection, name: str) -> CollectionRow | None:
    """The collection called ``name`` (ignoring ASCII case), or None."""
    row = conn.execute(_COLLECTIONS + " WHERE c.name = ? GROUP BY c.id", (name,)).fetchone()
    return None if row is None else CollectionRow(*row)


def collections(conn: sqlite3.Connection) -> list[CollectionRow]:
    """Every collection, by name."""
    rows = conn.execute(_COLLECTIONS + " GROUP BY c.id ORDER BY c.name, c.id")
    return [CollectionRow(*row) for row in rows]


_COLLECTIONS = (
    "SELECT c.id, c.name, c.created_at, COUNT(m.game_id) FROM collections c "
    "LEFT JOIN members m ON m.collection_id = c.id"
)


def members(conn: sqlite3.Connection, collection_id: int) -> set[str]:
    """The fingerprints of the games in a collection."""
    rows = conn.execute(
        "SELECT g.fingerprint FROM members m JOIN games g ON g.id = m.game_id "
        "WHERE m.collection_id = ?",
        (collection_id,),
    )
    return {row[0] for row in rows}


def games(conn: sqlite3.Connection, collection_id: int) -> list[GameRow]:
    """A collection's games, in the order they were added."""
    rows = conn.execute(
        "SELECT g.id, g.white, g.black, g.result, g.date, g.event, g.eco, g.opening, "
        "g.plies, g.engine_name, g.engine_depth FROM members m "
        "JOIN games g ON g.id = m.game_id WHERE m.collection_id = ? "
        "ORDER BY m.added_at, g.id",
        (collection_id,),
    )
    return [GameRow(*row) for row in rows]


def positions(conn: sqlite3.Connection, game_id: int) -> list[Position]:
    """A game's positions, from the start."""
    rows = conn.execute(
        "SELECT ply, fen, move_uci, move_san, clock_s, eval, best_uci, pv_uci "
        "FROM positions WHERE game_id = ? ORDER BY ply",
        (game_id,),
    )
    return [
        Position(
            ply=r[0],
            fen=r[1],
            move_uci=r[2],
            move_san=r[3],
            clock_s=r[4],
            score=Eval.from_dict(json.loads(r[5])),
            best_uci=r[6],
            pv_uci=tuple(r[7].split()),
        )
        for r in rows
    ]


# ---------------------------------------------------------------- writing
# Call these inside one host.transaction(conn) per game, so a game is saved whole or not
# at all.


def ensure_collection(conn: sqlite3.Connection, name: str, at: str) -> tuple[int, bool]:
    """The collection's id, made if it's missing; True when it was just made."""
    found = find(conn, name)
    if found is not None:
        return found.id, False
    cur = conn.execute("INSERT INTO collections (name, created_at) VALUES (?, ?)", (name, at))
    assert cur.lastrowid is not None
    return cur.lastrowid, True


def save_game(
    conn: sqlite3.Connection,
    game: GameInfo,
    scored: tuple[Position, ...],
    *,
    engine_name: str,
    engine_depth: int,
    at: str,
) -> int:
    """Save an analysed game and its positions; returns its id."""
    values = asdict(game) | {
        "engine_name": engine_name,
        "engine_depth": engine_depth,
        "analysed_at": at,
    }
    names = ", ".join(values)
    marks = ", ".join(f":{k}" for k in values)
    cur = conn.execute(f"INSERT INTO games ({names}) VALUES ({marks})", values)
    game_id = cur.lastrowid
    assert game_id is not None
    conn.executemany(
        "INSERT INTO positions (game_id, ply, fen, move_uci, move_san, clock_s, eval, "
        "best_uci, pv_uci) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                game_id,
                p.ply,
                p.fen,
                p.move_uci,
                p.move_san,
                p.clock_s,
                json.dumps(p.score.to_dict()),
                p.best_uci,
                " ".join(p.pv_uci),
            )
            for p in scored
        ],
    )
    return game_id


def add_member(conn: sqlite3.Connection, collection_id: int, game_id: int, at: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO members (collection_id, game_id, added_at) VALUES (?, ?, ?)",
        (collection_id, game_id, at),
    )
