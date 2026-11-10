"""collection.db (ROADMAP 12.1, ``migrations/0001_collections.sql``). All of the Collection's
SQL is here, with every value a parameter.

A game is analysed once and kept by its fingerprint; ``members`` puts it in collections.
"""

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from blunderbook.core.models import Eval
from blunderbook_collection import stats
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


def by_id(conn: sqlite3.Connection, collection_id: int) -> CollectionRow | None:
    row = conn.execute(_COLLECTIONS + " WHERE c.id = ? GROUP BY c.id", (collection_id,)).fetchone()
    return None if row is None else CollectionRow(*row)


def count_games(conn: sqlite3.Connection) -> int:
    """How many games there are, each once, in every collection."""
    return int(conn.execute("SELECT COUNT(*) FROM games").fetchone()[0])


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
    return [_position(r) for r in rows]


def _position(r: Sequence[Any]) -> Position:
    return Position(
        ply=r[0],
        fen=r[1],
        move_uci=r[2],
        move_san=r[3],
        clock_s=r[4],
        score=Eval.from_dict(json.loads(r[5])),
        best_uci=r[6],
        pv_uci=tuple(r[7].split()),
    )


def load(
    conn: sqlite3.Connection,
    collection_id: int | None = None,
    *,
    game_ids: Sequence[int] | None = None,
) -> list[stats.Game]:
    """The games of a collection (every collection's with None, each game once), or the
    games ``game_ids``, with their positions, for the stats. In the order they were first
    added."""
    if game_ids is not None:
        where = f"WHERE g.id IN ({', '.join('?' * len(game_ids))})"
        params: tuple[int, ...] = tuple(game_ids)
    elif collection_id is not None:
        where, params = "WHERE m.collection_id = ?", (collection_id,)
    else:
        where, params = "", ()
    rows = conn.execute(
        "SELECT g.id, g.white, g.black, g.result, g.eco, g.opening, g.date, g.event "
        f"FROM games g JOIN members m ON m.game_id = g.id {where} "
        "GROUP BY g.id ORDER BY MIN(m.added_at), g.id",
        params,
    ).fetchall()
    found: dict[int, list[Position]] = {row[0]: [] for row in rows}
    if found:
        marks = ", ".join("?" * len(found))
        for r in conn.execute(
            "SELECT game_id, ply, fen, move_uci, move_san, clock_s, eval, best_uci, pv_uci "
            f"FROM positions WHERE game_id IN ({marks}) ORDER BY game_id, ply",
            tuple(found),
        ):
            found[r[0]].append(_position(r[1:]))
    return [
        stats.Game(
            id=r[0],
            white=r[1],
            black=r[2],
            result=r[3],
            eco=r[4],
            opening=r[5],
            date=r[6],
            event=r[7],
            positions=tuple(found[r[0]]),
        )
        for r in rows
    ]


@dataclass(frozen=True, slots=True)
class GameDetail:
    """One game for its page: the stats' game, and what the page shows besides."""

    game: stats.Game
    white_elo: int | None
    black_elo: int | None
    site_label: str
    round: str | None
    start_fen: str
    engine_name: str
    engine_depth: int
    collections: tuple[tuple[int, str], ...]  # (id, name), by name


def game_detail(conn: sqlite3.Connection, game_id: int) -> GameDetail | None:
    """One game, with its positions and the collections it's in; None when there's none."""
    row = conn.execute(
        "SELECT white_elo, black_elo, site_label, round, start_fen, engine_name, engine_depth "
        "FROM games WHERE id = ?",
        (game_id,),
    ).fetchone()
    if row is None:
        return None
    (game,) = load(conn, game_ids=(game_id,))
    named = conn.execute(
        "SELECT c.id, c.name FROM members m JOIN collections c ON c.id = m.collection_id "
        "WHERE m.game_id = ? ORDER BY c.name, c.id",
        (game_id,),
    )
    return GameDetail(
        game=game,
        white_elo=row[0],
        black_elo=row[1],
        site_label=row[2],
        round=row[3],
        start_fen=row[4],
        engine_name=row[5],
        engine_depth=row[6],
        collections=tuple((r[0], r[1]) for r in named),
    )


def engines(conn: sqlite3.Connection, collection_id: int | None = None) -> list[tuple[str, int]]:
    """The engines and depths the games were analysed with (a collection's, or every
    game's), most games first."""
    where = "WHERE m.collection_id = ?" if collection_id is not None else ""
    params: tuple[int, ...] = (collection_id,) if collection_id is not None else ()
    rows = conn.execute(
        "SELECT g.engine_name, g.engine_depth FROM games g "
        f"WHERE g.id IN (SELECT m.game_id FROM members m {where}) "
        "GROUP BY g.engine_name, g.engine_depth ORDER BY COUNT(*) DESC, g.engine_depth DESC",
        params,
    )
    return [(r[0], r[1]) for r in rows]


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
