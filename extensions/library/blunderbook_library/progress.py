"""Your practise, in library.db (ROADMAP 11.3): where each position stands, and every try.

A position is named by its entry's id and its FEN (``migrations/0001_progress.sql``). One you
haven't tried has no row: it's new, and due today. Scheduling follows core's Re-test rules
(CLAUDE.md §7.8), from ``blunderbook.core.retest``: a solve moves it out by 1, 3, 7, 14, 30,
then 60 days; a miss or giving up brings it back tomorrow. The hint is recorded and changes
nothing.

All of the Library's SQL is here, with every value a parameter.
"""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal, cast

from blunderbook import host
from blunderbook.core import retest

type Key = tuple[str, str]  # (entry id, FEN)
type Tried = Literal["solved", "missed"]


@dataclass(frozen=True, slots=True)
class Progress:
    """A position you've tried."""

    status: Tried
    streak: int
    due_on: date


def all_progress(conn: sqlite3.Connection) -> dict[Key, Progress]:
    rows = conn.execute("SELECT entry_id, fen, status, streak, due_on FROM progress")
    return {(row["entry_id"], row["fen"]): _progress(row) for row in rows}


def get(conn: sqlite3.Connection, key: Key) -> Progress | None:
    row = conn.execute(
        "SELECT status, streak, due_on FROM progress WHERE entry_id = ? AND fen = ?", key
    ).fetchone()
    return None if row is None else _progress(row)


def record(
    conn: sqlite3.Connection,
    key: Key,
    *,
    move_uci: str | None,
    solved: bool,
    used_hint: bool,
    today: date,
    now: datetime | None = None,
) -> Progress:
    """Record a try (``move_uci`` None: you gave up) and reschedule the position, together."""
    at = (now or datetime.now(UTC)).isoformat()
    with host.transaction(conn):
        before = get(conn, key)
        after = retest.after_attempt(0 if before is None else before.streak, solved, today)
        conn.execute(
            "INSERT INTO progress (entry_id, fen, status, streak, due_on, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (entry_id, fen) DO UPDATE SET status = excluded.status,"
            " streak = excluded.streak, due_on = excluded.due_on,"
            " updated_at = excluded.updated_at",
            (*key, after.status, after.streak, after.due_on.isoformat(), at),
        )
        conn.execute(
            "INSERT INTO attempts (entry_id, fen, attempted_at, move_uci, solved, used_hint)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (*key, at, move_uci, int(solved), int(used_hint)),
        )
    return Progress(cast(Tried, after.status), after.streak, after.due_on)


def attempts(conn: sqlite3.Connection, key: Key) -> list[sqlite3.Row]:
    """Every try at a position, oldest first."""
    return conn.execute(
        "SELECT attempted_at, move_uci, solved, used_hint FROM attempts"
        " WHERE entry_id = ? AND fen = ? ORDER BY id",
        key,
    ).fetchall()


def _progress(row: sqlite3.Row) -> Progress:
    return Progress(row["status"], row["streak"], date.fromisoformat(row["due_on"]))
