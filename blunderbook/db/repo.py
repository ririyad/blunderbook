"""All data SQL (CLAUDE.md §5, §14): games and blunders in, dataclasses out.

Every value is a query parameter. Column lists are built from the constant tuples below,
never from input. Writes that belong together share one ``transaction()``.

Timestamps are stored as ISO-8601 UTC (``2026-11-05T09:30:00+00:00``), dates you see as
local ``YYYY-MM-DD``. Sync state arrives with M5.
"""

import json
import sqlite3
from collections.abc import Collection, Iterable
from datetime import UTC, date, datetime
from typing import Any, cast

from blunderbook.core import retest
from blunderbook.core.models import (
    CAUSES,
    AnalysisStatus,
    Attempt,
    AttemptStats,
    Blunder,
    Color,
    Entry,
    Eval,
    Game,
    Judgment,
    NewBlunder,
    NewGame,
    SavedIds,
    Source,
    Speed,
    Status,
    SyncSource,
    SyncState,
    Totals,
)
from blunderbook.db.connection import transaction

_GAME_COLUMNS = (
    "fingerprint",
    "source",
    "site_label",
    "external_id",
    "white",
    "black",
    "white_elo",
    "black_elo",
    "my_color",
    "result",
    "played_on",
    "time_control",
    "tc_base_s",
    "tc_inc_s",
    "speed",
    "opening",
    "eco",
    "start_fen",
    "pgn",
    "has_clocks",
    "analysis_status",
    "engine_name",
    "engine_depth",
    "imported_at",
)
_BLUNDER_COLUMNS = (
    "game_id",
    "ply",
    "move_no",
    "fen_before",
    "played_uci",
    "played_san",
    "best_uci",
    "best_san",
    "best_line_san",
    "refutation_san",
    "accept_uci",
    "eval_before",
    "eval_after",
    "swing",
    "judgment",
    "clock_left_s",
    "time_spent_s",
    "auto_causes",
    "causes",
    "other_cause",
    "thinking",
    "lesson",
    "status",
    "streak",
    "due_on",
    "created_at",
    "updated_at",
)

_INSERT_GAME = (
    f"INSERT INTO games ({', '.join(_GAME_COLUMNS)}) "
    f"VALUES ({', '.join(':' + c for c in _GAME_COLUMNS)}) "
    "ON CONFLICT (fingerprint) DO NOTHING RETURNING id"
)
_INSERT_BLUNDER = (
    f"INSERT INTO blunders ({', '.join(_BLUNDER_COLUMNS)}) "
    f"VALUES ({', '.join(':' + c for c in _BLUNDER_COLUMNS)}) RETURNING id"
)
_SELECT_GAME = f"SELECT id, {', '.join(_GAME_COLUMNS)} FROM games"
_SELECT_ENTRY = (
    "SELECT "
    + ", ".join(f"g.{c} AS g_{c}" for c in ("id", *_GAME_COLUMNS))
    + ", "
    + ", ".join(f"b.{c} AS b_{c}" for c in ("id", *_BLUNDER_COLUMNS))
    + " FROM blunders AS b JOIN games AS g ON g.id = b.game_id"
)
# Newest entries first, as the demo's Log does; one game's entries in move order.
_ENTRY_ORDER = " ORDER BY b.created_at DESC, g.played_on DESC NULLS LAST, g.id DESC, b.ply"


# ---------------------------------------------------------------- games


def known_fingerprints(conn: sqlite3.Connection) -> set[str]:
    """Every saved game's fingerprint, for "Already imported — skipped" (CLAUDE.md §7.4)."""
    return {row[0] for row in conn.execute("SELECT fingerprint FROM games")}


def add_game(
    conn: sqlite3.Connection,
    game: NewGame,
    blunders: Iterable[NewBlunder] = (),
    *,
    now: datetime | None = None,
) -> SavedIds | None:
    """Save an analysed game and its blunders in one transaction, and return their ids.

    A game with no blunders is saved too, so importing it again is skipped. Returns None,
    and writes nothing, when a game with the same fingerprint is already saved. New entries
    are due today (CLAUDE.md §7.8).
    """
    moment = _moment(now)
    stamp = _timestamp(moment)
    due = moment.astimezone().date()  # local
    with transaction(conn):
        row = conn.execute(_INSERT_GAME, _game_params(game, stamp)).fetchone()
        if row is None:
            return None
        game_id = int(row[0])
        blunder_ids = tuple(
            int(
                conn.execute(_INSERT_BLUNDER, _blunder_params(game_id, b, stamp, due)).fetchone()[0]
            )
            for b in blunders
        )
    return SavedIds(game_id, blunder_ids)


def find_saved(conn: sqlite3.Connection, fingerprint: str) -> SavedIds | None:
    """The saved game with this fingerprint and its entry ids (in move order), or None."""
    row = conn.execute("SELECT id FROM games WHERE fingerprint = ?", (fingerprint,)).fetchone()
    if row is None:
        return None
    rows = conn.execute("SELECT id FROM blunders WHERE game_id = ? ORDER BY ply", (row[0],))
    return SavedIds(int(row[0]), tuple(int(r[0]) for r in rows))


def totals(conn: sqlite3.Connection) -> Totals:
    """Games and entries in the database. Works on any schema version from 1 on."""
    row = conn.execute(
        "SELECT (SELECT count(*) FROM games WHERE source <> 'fen'), (SELECT count(*) FROM blunders)"
    ).fetchone()
    return Totals(games=int(row[0]), entries=int(row[1]))


def get_game(conn: sqlite3.Connection, game_id: int) -> Game | None:
    row = conn.execute(f"{_SELECT_GAME} WHERE id = ?", (game_id,)).fetchone()
    return None if row is None else _game(row)


def _game_params(game: NewGame, stamp: str) -> dict[str, Any]:
    return {
        "fingerprint": game.fingerprint,
        "source": game.source,
        "site_label": game.site_label,
        "external_id": game.external_id,
        "white": game.white,
        "black": game.black,
        "white_elo": game.white_elo,
        "black_elo": game.black_elo,
        "my_color": game.my_color,
        "result": game.result,
        "played_on": None if game.played_on is None else game.played_on.isoformat(),
        "time_control": game.time_control,
        "tc_base_s": game.tc_base_s,
        "tc_inc_s": game.tc_inc_s,
        "speed": game.speed,
        "opening": game.opening,
        "eco": game.eco,
        "start_fen": game.start_fen,
        "pgn": game.pgn,
        "has_clocks": int(game.has_clocks),
        "analysis_status": "done",  # only analysed games are saved
        "engine_name": game.engine_name,
        "engine_depth": game.engine_depth,
        "imported_at": stamp,
    }


def _game(row: sqlite3.Row, prefix: str = "") -> Game:
    def col(name: str) -> Any:
        return row[prefix + name]

    return Game(
        id=col("id"),
        fingerprint=col("fingerprint"),
        source=cast(Source, col("source")),
        site_label=col("site_label"),
        external_id=col("external_id"),
        white=col("white"),
        black=col("black"),
        white_elo=col("white_elo"),
        black_elo=col("black_elo"),
        my_color=cast(Color, col("my_color")),
        result=col("result"),
        played_on=_date_or_none(col("played_on")),
        time_control=col("time_control"),
        tc_base_s=col("tc_base_s"),
        tc_inc_s=col("tc_inc_s"),
        speed=cast(Speed | None, col("speed")),
        opening=col("opening"),
        eco=col("eco"),
        start_fen=col("start_fen"),
        pgn=col("pgn"),
        has_clocks=bool(col("has_clocks")),
        analysis_status=cast(AnalysisStatus, col("analysis_status")),
        engine_name=col("engine_name"),
        engine_depth=col("engine_depth"),
        imported_at=datetime.fromisoformat(col("imported_at")),
    )


# ---------------------------------------------------------------- entries


def get_entry(conn: sqlite3.Connection, blunder_id: int) -> Entry | None:
    row = conn.execute(f"{_SELECT_ENTRY} WHERE b.id = ?", (blunder_id,)).fetchone()
    return None if row is None else _entry(row)


def list_entries(
    conn: sqlite3.Connection,
    *,
    source: Source | None = None,
    statuses: Collection[Status] = (),
    cause: str | None = None,
    due_by: date | None = None,
) -> list[Entry]:
    """The Log, newest first. Filters combine; each one left out matches everything.

    ``cause`` matches entries where you confirmed it, or where you haven't confirmed any
    cause yet and it's suggested (as the demo's Log does). ``due_by`` keeps entries due on
    or before that day.
    """
    where: list[str] = []
    params: dict[str, Any] = {}
    if source is not None:
        where.append("g.source = :source")
        params["source"] = source
    if statuses:
        names = [f"status{i}" for i in range(len(statuses))]
        where.append(f"b.status IN ({', '.join(':' + n for n in names)})")
        params.update(zip(names, statuses, strict=True))
    if cause is not None:
        _check_cause(cause)
        where.append(
            "(EXISTS (SELECT 1 FROM json_each(b.causes) WHERE value = :cause)"
            " OR (json_array_length(b.causes) = 0"
            " AND EXISTS (SELECT 1 FROM json_each(b.auto_causes) WHERE value = :cause)))"
        )
        params["cause"] = cause
    if due_by is not None:
        where.append("b.due_on <= :due_by")
        params["due_by"] = due_by.isoformat()
    sql = _SELECT_ENTRY + (" WHERE " + " AND ".join(where) if where else "") + _ENTRY_ORDER
    return [_entry(row) for row in conn.execute(sql, params)]


def update_notes(
    conn: sqlite3.Connection,
    blunder_id: int,
    *,
    causes: Iterable[str] | None = None,
    other_cause: str | None = None,
    thinking: str | None = None,
    lesson: str | None = None,
    now: datetime | None = None,
) -> Entry | None:
    """Change your part of an entry. Only the fields given change. ``other_cause=""``
    clears it. Text is kept exactly as written. Causes are stored once each, in the fixed
    order. Returns the updated entry, or None when there's no such entry."""
    changes: dict[str, Any] = {}
    if causes is not None:
        changes["causes"] = _json(_ordered_causes(causes))
    if other_cause is not None:
        changes["other_cause"] = other_cause or None
    if thinking is not None:
        changes["thinking"] = thinking
    if lesson is not None:
        changes["lesson"] = lesson
    if changes:
        changes["updated_at"] = _timestamp(_moment(now))
        assignments = ", ".join(f"{column} = :{column}" for column in changes)
        conn.execute(
            f"UPDATE blunders SET {assignments} WHERE id = :id", {**changes, "id": blunder_id}
        )
    return get_entry(conn, blunder_id)


def record_attempt(
    conn: sqlite3.Connection,
    blunder_id: int,
    *,
    move_uci: str | None,
    used_hint: bool,
    today: date,
    now: datetime | None = None,
) -> tuple[Entry, Attempt] | None:
    """Record a re-test try and reschedule the entry, in one transaction (CLAUDE.md §7.8).
    ``move_uci`` is a legal move in the entry's position, or None when you gave up. Whether
    it solves the entry is decided here, from the stored accepted moves. Returns the
    rescheduled entry and the attempt, or None when there's no such entry."""
    stamp = _timestamp(_moment(now))
    with transaction(conn):
        row = conn.execute(
            "SELECT accept_uci, streak FROM blunders WHERE id = ?", (blunder_id,)
        ).fetchone()
        if row is None:
            return None
        solved = retest.is_solved(move_uci, json.loads(row["accept_uci"]))
        schedule = retest.after_attempt(row["streak"], solved, today)
        attempt_id = conn.execute(
            "INSERT INTO retest_attempts (blunder_id, attempted_at, move_uci, solved, used_hint)"
            " VALUES (?, ?, ?, ?, ?) RETURNING id",
            (blunder_id, stamp, move_uci, int(solved), int(used_hint)),
        ).fetchone()[0]
        conn.execute(
            "UPDATE blunders SET status = ?, streak = ?, due_on = ?, updated_at = ? WHERE id = ?",
            (schedule.status, schedule.streak, schedule.due_on.isoformat(), stamp, blunder_id),
        )
        entry = get_entry(conn, blunder_id)
    assert entry is not None
    attempt = Attempt(
        id=attempt_id,
        blunder_id=blunder_id,
        attempted_at=datetime.fromisoformat(stamp),
        move_uci=move_uci,
        solved=solved,
        used_hint=used_hint,
    )
    return entry, attempt


def list_attempts(conn: sqlite3.Connection, blunder_id: int) -> list[Attempt]:
    """An entry's re-test tries, oldest first."""
    rows = conn.execute(
        "SELECT id, blunder_id, attempted_at, move_uci, solved, used_hint"
        " FROM retest_attempts WHERE blunder_id = ? ORDER BY attempted_at, id",
        (blunder_id,),
    )
    return [
        Attempt(
            id=r["id"],
            blunder_id=r["blunder_id"],
            attempted_at=datetime.fromisoformat(r["attempted_at"]),
            move_uci=r["move_uci"],
            solved=bool(r["solved"]),
            used_hint=bool(r["used_hint"]),
        )
        for r in rows
    ]


def attempt_stats(conn: sqlite3.Connection) -> dict[int, AttemptStats]:
    """Each re-tested entry's number of tries and the time of the last, by entry id."""
    rows = conn.execute(
        "SELECT blunder_id, count(*) AS n, max(attempted_at) AS last_at"
        " FROM retest_attempts GROUP BY blunder_id"
    )
    return {
        r["blunder_id"]: AttemptStats(r["n"], datetime.fromisoformat(r["last_at"])) for r in rows
    }


def next_due_after(conn: sqlite3.Connection, day: date) -> date | None:
    """The first re-test date after ``day``, or None when nothing is scheduled later."""
    row = conn.execute(
        "SELECT min(due_on) FROM blunders WHERE due_on > ?", (day.isoformat(),)
    ).fetchone()
    return _date_or_none(row[0])


def get_sync_state(conn: sqlite3.Connection, source: SyncSource) -> SyncState | None:
    """How far `blunderbook sync` got with one site, or None before its first run."""
    row = conn.execute(
        "SELECT source, username, last_synced, last_run_at, last_error FROM sync_state"
        " WHERE source = ?",
        (source,),
    ).fetchone()
    if row is None:
        return None
    return SyncState(
        source=row["source"],
        username=row["username"],
        last_synced=_moment_or_none(row["last_synced"]),
        last_run_at=_moment_or_none(row["last_run_at"]),
        last_error=row["last_error"],
    )


def record_sync(
    conn: sqlite3.Connection,
    source: SyncSource,
    *,
    username: str,
    newest: datetime | None = None,
    error: str | None = None,
    now: datetime | None = None,
) -> SyncState:
    """Store one sync run. A run that worked (no `error`) moves `last_synced` on to `newest`
    (never back) and clears the last error. A failed run keeps `last_synced` and records
    the error. Another username starts again from the beginning: its `last_synced` isn't
    the old account's."""
    if newest is not None and newest.tzinfo is None:
        raise ValueError("newest must be timezone-aware.")
    ran = _moment(now)
    with transaction(conn):
        before = get_sync_state(conn, source)
        same = before is not None and before.username.casefold() == username.casefold()
        last = before.last_synced if same and before is not None else None
        if error is None and newest is not None and (last is None or newest > last):
            last = newest
        conn.execute(
            "INSERT INTO sync_state (source, username, last_synced, last_run_at, last_error)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT (source) DO UPDATE SET username = excluded.username,"
            " last_synced = excluded.last_synced, last_run_at = excluded.last_run_at,"
            " last_error = excluded.last_error",
            (
                source,
                username,
                None if last is None else _timestamp(last),
                _timestamp(ran),
                error,
            ),
        )
        state = get_sync_state(conn, source)
    assert state is not None
    return state


def delete_blunder(conn: sqlite3.Connection, blunder_id: int) -> bool:
    """Delete one entry and its re-test history. Its game stays, so importing the game again
    is still skipped. Returns False when there was no such entry."""
    return conn.execute("DELETE FROM blunders WHERE id = ?", (blunder_id,)).rowcount > 0


def _blunder_params(game_id: int, b: NewBlunder, stamp: str, due: date) -> dict[str, Any]:
    return {
        "game_id": game_id,
        "ply": b.ply,
        "move_no": b.move_no,
        "fen_before": b.fen_before,
        "played_uci": b.played_uci,
        "played_san": b.played_san,
        "best_uci": b.best_uci,
        "best_san": b.best_san,
        "best_line_san": b.best_line_san,
        "refutation_san": b.refutation_san,
        "accept_uci": _json(list(b.accept_uci)),
        "eval_before": _json(b.eval_before.to_dict()),
        "eval_after": _json(b.eval_after.to_dict()),
        "swing": b.swing,
        "judgment": b.judgment,
        "clock_left_s": b.clock_left_s,
        "time_spent_s": b.time_spent_s,
        "auto_causes": _json(_ordered_causes(b.auto_causes)),
        "causes": "[]",
        "other_cause": None,
        "thinking": "",
        "lesson": "",
        "status": "new",
        "streak": 0,
        "due_on": due.isoformat(),
        "created_at": stamp,
        "updated_at": stamp,
    }


def _entry(row: sqlite3.Row) -> Entry:
    return Entry(_blunder(row, "b_"), _game(row, "g_"))


def _blunder(row: sqlite3.Row, prefix: str = "") -> Blunder:
    def col(name: str) -> Any:
        return row[prefix + name]

    return Blunder(
        id=col("id"),
        game_id=col("game_id"),
        ply=col("ply"),
        move_no=col("move_no"),
        fen_before=col("fen_before"),
        played_uci=col("played_uci"),
        played_san=col("played_san"),
        best_uci=col("best_uci"),
        best_san=col("best_san"),
        best_line_san=col("best_line_san"),
        refutation_san=col("refutation_san"),
        accept_uci=tuple(json.loads(col("accept_uci"))),
        eval_before=Eval.from_dict(json.loads(col("eval_before"))),
        eval_after=Eval.from_dict(json.loads(col("eval_after"))),
        swing=col("swing"),
        judgment=cast(Judgment, col("judgment")),
        clock_left_s=col("clock_left_s"),
        time_spent_s=col("time_spent_s"),
        auto_causes=tuple(json.loads(col("auto_causes"))),
        causes=tuple(json.loads(col("causes"))),
        other_cause=col("other_cause"),
        thinking=col("thinking"),
        lesson=col("lesson"),
        status=cast(Status, col("status")),
        streak=col("streak"),
        due_on=date.fromisoformat(col("due_on")),
        created_at=datetime.fromisoformat(col("created_at")),
        updated_at=datetime.fromisoformat(col("updated_at")),
    )


# ---------------------------------------------------------------- helpers


def _check_cause(cause: str) -> None:
    if cause not in CAUSES:
        raise ValueError(f"Unknown cause: {cause!r}. Choose from the fixed list (CLAUDE.md §5).")


def _ordered_causes(causes: Iterable[str]) -> list[str]:
    chosen = set(causes)
    for cause in chosen:
        _check_cause(cause)
    return [c for c in CAUSES if c in chosen]


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _moment(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware.")
    return now


def _timestamp(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def _moment_or_none(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def _date_or_none(value: str | None) -> date | None:
    return None if value is None else date.fromisoformat(value)
