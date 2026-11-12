"""rankings.db (ROADMAP 16.1, ``migrations/0001_rankings.sql``). All of the Rankings SQL is
here, with every value a parameter."""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from blunderbook_rankings.fide import JUNIOR_AGE, Category, FideList, Speed
from blunderbook_rankings.net import Validators
from blunderbook_rankings.site import SitePlayer

KEEP_MONTHS: Final = 2  # the newest list, and the one before for "change since last month"


@dataclass(frozen=True, slots=True)
class SourceRow:
    source: str
    list_month: str | None
    fetched_at: str | None
    checked_at: str | None
    last_error: str | None


@dataclass(frozen=True, slots=True)
class FideRow:
    fide_id: int
    name: str
    fed: str | None
    sex: str | None
    title: str | None
    born: int | None
    rating: int
    games: int | None


@dataclass(frozen=True, slots=True)
class FideCount:
    speed: str
    list_month: str
    players: int


def now() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------- sources and downloads


def source(conn: sqlite3.Connection, name: str) -> SourceRow | None:
    row = conn.execute(
        "SELECT source, list_month, fetched_at, checked_at, last_error FROM sources"
        " WHERE source = ?",
        (name,),
    ).fetchone()
    return None if row is None else SourceRow(*row)


def checked(
    conn: sqlite3.Connection,
    name: str,
    *,
    at: str,
    changed: bool,
    list_month: str | None = None,
    error: str | None = None,
) -> None:
    """Record an update of ``name`` at ``at``: it ``changed`` the lists, or not, or failed
    with ``error`` (the lists stay as they were)."""
    conn.execute(
        "INSERT INTO sources (source, list_month, fetched_at, checked_at, last_error)"
        " VALUES (?, ?, ?, ?, ?)"
        " ON CONFLICT (source) DO UPDATE SET"
        "   list_month = coalesce(excluded.list_month, list_month),"
        "   fetched_at = coalesce(excluded.fetched_at, fetched_at),"
        "   checked_at = excluded.checked_at,"
        "   last_error = excluded.last_error",
        (name, list_month, at if changed else None, at, error),
    )


def validators(conn: sqlite3.Connection, url: str) -> Validators:
    row = conn.execute("SELECT etag, last_modified FROM downloads WHERE url = ?", (url,)).fetchone()
    return Validators() if row is None else Validators(*row)


def save_validators(conn: sqlite3.Connection, url: str, got: Validators) -> None:
    conn.execute(
        "INSERT INTO downloads (url, etag, last_modified) VALUES (?, ?, ?)"
        " ON CONFLICT (url) DO UPDATE SET etag = excluded.etag,"
        " last_modified = excluded.last_modified",
        (url, got.etag, got.last_modified),
    )


# ---------------------------------------------------------------- FIDE


def replace_fide(conn: sqlite3.Connection, found: FideList) -> None:
    """Put ``found`` in as its month's list (replacing that month's, if FIDE republished it),
    and keep only the newest KEEP_MONTHS months of that speed. Call inside a transaction."""
    conn.execute(
        "DELETE FROM fide_players WHERE speed = ? AND list_month = ?", (found.speed, found.month)
    )
    conn.executemany(
        "INSERT INTO fide_players (list_month, speed, fide_id, name, fed, sex, title, born,"
        " rating, games) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            (
                found.month,
                found.speed,
                p.fide_id,
                p.name,
                p.fed,
                p.sex,
                p.title,
                p.born,
                p.rating,
                p.games,
            )
            for p in found.players
        ),
    )
    conn.execute(
        "DELETE FROM fide_players WHERE speed = ? AND list_month NOT IN ("
        "  SELECT DISTINCT list_month FROM fide_players WHERE speed = ?"
        "  ORDER BY list_month DESC LIMIT ?)",
        (found.speed, found.speed, KEEP_MONTHS),
    )


def fide_months(conn: sqlite3.Connection, speed: Speed) -> list[str]:
    """The months kept for ``speed``, newest first."""
    rows = conn.execute(
        "SELECT DISTINCT list_month FROM fide_players WHERE speed = ? ORDER BY list_month DESC",
        (speed,),
    )
    return [row[0] for row in rows]


def fide_counts(conn: sqlite3.Connection) -> list[FideCount]:
    """Players kept per speed in its newest month, in the order of ``fide.SPEEDS``."""
    rows = conn.execute(
        "SELECT speed, list_month, count(*) FROM fide_players f"
        " WHERE list_month = (SELECT max(list_month) FROM fide_players WHERE speed = f.speed)"
        " GROUP BY speed, list_month"
    ).fetchall()
    order = {"standard": 0, "rapid": 1, "blitz": 2}
    return sorted((FideCount(*row) for row in rows), key=lambda c: order.get(c.speed, 9))


def fide_top(
    conn: sqlite3.Connection,
    month: str,
    speed: Speed,
    category: Category,
    fed: str | None,
    limit: int,
) -> list[FideRow]:
    """The top ``limit`` of one list as kept: ``fed`` None for the world."""
    where = ["list_month = ?", "speed = ?"]
    params: list[object] = [month, speed]
    if category in ("women", "girls"):
        where.append("sex = 'F'")
    if category in ("juniors", "girls"):
        where.append("born >= ?")
        params.append(int(month[:4]) - JUNIOR_AGE)
    if fed is not None:
        where.append("fed = ?")
        params.append(fed)
    params.append(limit)
    rows = conn.execute(
        "SELECT fide_id, name, fed, sex, title, born, rating, games FROM fide_players"
        f" WHERE {' AND '.join(where)} ORDER BY rating DESC, fide_id LIMIT ?",
        params,
    )
    return [FideRow(*row) for row in rows]


# ---------------------------------------------------------------- Lichess and Chess.com


def replace_boards(
    conn: sqlite3.Connection, source_name: str, boards: dict[str, list[SitePlayer]]
) -> None:
    """Put in ``source_name``'s latest boards, in place of everything it had. Call inside a
    transaction."""
    conn.execute("DELETE FROM site_players WHERE source = ?", (source_name,))
    conn.executemany(
        "INSERT INTO site_players (source, board, rank, username, title, rating, progress)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            (source_name, board, p.rank, p.username, p.title, p.rating, p.progress)
            for board, players in boards.items()
            for p in players
        ),
    )


def board(conn: sqlite3.Connection, source_name: str, name: str) -> list[SitePlayer]:
    """One board, best first."""
    rows = conn.execute(
        "SELECT rank, username, title, rating, progress FROM site_players"
        " WHERE source = ? AND board = ? ORDER BY rank",
        (source_name, name),
    )
    return [SitePlayer(*row) for row in rows]


def board_counts(conn: sqlite3.Connection, source_name: str) -> dict[str, int]:
    """Players kept per board."""
    rows = conn.execute(
        "SELECT board, count(*) FROM site_players WHERE source = ? GROUP BY board",
        (source_name,),
    )
    return {row[0]: row[1] for row in rows}
