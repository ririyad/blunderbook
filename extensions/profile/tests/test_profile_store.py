"""profile.db (ROADMAP 17.2): each site's answer, one per day you asked."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from blunderbook_profile import extension, store
from profile_fakes import CHESSCOM, LICHESS, cfg_file  # noqa: F401  (fixtures)

from blunderbook import host
from blunderbook.core.models import Rating
from blunderbook.db import connection

NOON = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)


@pytest.fixture
def db() -> Iterator[sqlite3.Connection]:
    with closing(host.open_db(extension)) as conn:
        yield conn


def count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0])


def test_the_database(db: sqlite3.Connection) -> None:
    assert connection.table_names(db) == {"fetches", "ratings"}


def test_nothing_kept_yet(db: sqlite3.Connection) -> None:
    assert store.latest(db, "lichess") is None
    assert store.latest(db, "chesscom") is None


def test_save_and_read_back(db: sqlite3.Connection) -> None:
    saved = store.save(db, LICHESS, at=NOON)
    assert saved == store.Fetch(
        source="lichess",
        username="Rashed",
        day=NOON.astimezone().date(),
        fetched_at=NOON,
        ratings=LICHESS.ratings,
    )
    assert store.latest(db, "lichess") == saved  # every field, None and provisional too
    assert store.latest(db, "chesscom") is None
    assert store.save(db, CHESSCOM, at=NOON) == store.latest(db, "chesscom")


def test_ratings_come_back_in_the_fixed_order(db: sqlite3.Connection) -> None:
    mixed = replace(LICHESS, ratings=tuple(reversed(LICHESS.ratings)))
    store.save(db, mixed, at=NOON)
    kept = store.latest(db, "lichess")
    assert kept is not None
    assert [r.kind for r in kept.ratings] == ["blitz", "classical", "daily", "puzzle"]


def test_the_same_day_keeps_the_later_answer(db: sqlite3.Connection) -> None:
    store.save(db, LICHESS, at=NOON)
    fewer = replace(LICHESS, ratings=(Rating(kind="blitz", rating=1660, games=815),))
    later = store.save(db, fewer, at=NOON + timedelta(minutes=5))
    assert store.latest(db, "lichess") == later
    assert store.before(db, later) is None  # nothing from an earlier day
    assert count(db, "fetches") == 1
    assert count(db, "ratings") == 1  # the first answer's rows went with it


def test_before_and_changes(db: sqlite3.Connection) -> None:
    monday = store.save(db, LICHESS, at=NOON - timedelta(days=7))
    moved = replace(
        LICHESS,
        ratings=(
            Rating(kind="bullet", rating=1500, games=1),  # new: nothing to compare with
            Rating(kind="blitz", rating=1659, games=830),
            Rating(kind="classical", rating=1702, games=3),  # didn't move
            Rating(kind="puzzle", rating=1970, games=2150),
        ),
    )
    today = store.save(db, moved, at=NOON)
    assert store.before(db, today) == monday
    assert store.before(db, monday) is None
    assert store.changes(today, monday) == {"blitz": 12, "classical": 0, "puzzle": -15}
    assert store.changes(today, None) == {}
    assert count(db, "fetches") == 2


def test_a_best_only_rating_has_no_change(db: sqlite3.Connection) -> None:
    earlier = store.save(db, CHESSCOM, at=NOON - timedelta(days=2))
    today = store.save(db, CHESSCOM, at=NOON)
    assert store.changes(today, earlier) == {"blitz": 0}  # puzzle: no current rating


def test_another_account_isnt_compared(db: sqlite3.Connection) -> None:
    store.save(db, replace(LICHESS, username="SomeoneElse"), at=NOON - timedelta(days=1))
    today = store.save(db, LICHESS, at=NOON)
    assert store.before(db, today) is None
    again = store.save(db, replace(LICHESS, username="RASHED"), at=NOON + timedelta(days=1))
    assert store.before(db, again) == today  # the same account, spelled differently


def test_sites_are_kept_apart(db: sqlite3.Connection) -> None:
    store.save(db, CHESSCOM, at=NOON - timedelta(days=1))
    today = store.save(db, LICHESS, at=NOON)
    assert store.before(db, today) is None
