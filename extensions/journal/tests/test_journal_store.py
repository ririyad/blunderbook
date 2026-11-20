"""journal.db (ROADMAP 19.1): notes, tags, versions and search."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime, timedelta

import pytest
from blunderbook_journal import extension, store
from journal_fakes import ELEPHANT, cfg_file  # noqa: F401  (fixtures)

from blunderbook import host
from blunderbook.db import connection

NOON = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


@pytest.fixture
def db() -> Iterator[sqlite3.Connection]:
    with closing(host.open_db(extension)) as conn:
        yield conn


def count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0])


def ids(found: list[store.Summary]) -> list[int]:
    return [s.id for s in found]


def test_the_database(db: sqlite3.Connection) -> None:
    tables = connection.table_names(db)
    assert {"notes", "tags", "versions", "search"} <= tables
    assert all(t.startswith("search_") for t in tables - {"notes", "tags", "versions", "search"})


def test_create_and_read_back(db: sqlite3.Connection) -> None:
    note = store.create(db, ELEPHANT, at=NOON)
    assert note == store.Note(
        id=note.id,
        title="The Elephant trap",
        body=ELEPHANT,
        pinned=False,
        tags=("qgd", "traps"),
        created_at=NOON,
        updated_at=NOON,
    )
    assert store.get(db, note.id) == note
    assert store.get(db, note.id + 1) is None


def test_the_text_is_kept_exactly(db: sqlite3.Connection) -> None:
    body = "  # Odd\r\nspacing\t\n\n\né́ \U0001f600\n"
    assert store.create(db, body).body == body


def test_update_reads_the_text_again(db: sqlite3.Connection) -> None:
    note = store.create(db, ELEPHANT, at=NOON)
    later = NOON + timedelta(minutes=1)
    changed = store.update(db, note.id, "# Renamed\n#endgame", at=later)
    assert changed is not None
    assert (changed.title, changed.tags, changed.updated_at) == ("Renamed", ("endgame",), later)
    assert changed.created_at == NOON
    assert store.all_tags(db) == [("endgame", 1)]
    assert store.update(db, 999, "x") is None


def test_the_same_text_changes_nothing(db: sqlite3.Connection) -> None:
    note = store.create(db, ELEPHANT, at=NOON)
    same = store.update(db, note.id, ELEPHANT, at=NOON + timedelta(hours=1))
    assert same == note
    assert store.versions(db, note.id) == []


def test_a_version_every_five_minutes(db: sqlite3.Connection) -> None:
    note = store.create(db, "v0", at=NOON)
    minute = timedelta(minutes=1)
    for n in range(1, 13):  # a save a minute for 12 minutes
        store.update(db, note.id, f"v{n}", at=NOON + n * minute)
    kept = store.versions(db, note.id)
    # v0 at the first save. Then, once the newest kept is over 5 minutes old, the text the
    # save replaces, with the time it was written: v5 (kept at 6 min), v10 (at 11 min).
    assert [v.body for v in kept] == ["v10", "v5", "v0"]
    assert [v.saved_at for v in kept] == [NOON + 10 * minute, NOON + 5 * minute, NOON]
    assert {v.note_id for v in kept} == {note.id}


def test_an_empty_text_isnt_a_version(db: sqlite3.Connection) -> None:
    note = store.create(db, "", at=NOON)
    store.update(db, note.id, "first words", at=NOON + timedelta(seconds=5))
    assert store.versions(db, note.id) == []


def test_only_the_newest_30_versions_stay(db: sqlite3.Connection) -> None:
    note = store.create(db, "v0", at=NOON)
    for n in range(1, 41):
        store.update(db, note.id, f"v{n}", at=NOON + timedelta(minutes=6 * n))
    kept = store.versions(db, note.id)
    assert len(kept) == store.KEEP_VERSIONS
    assert kept[0].body == "v39" and kept[-1].body == "v10"


def test_pinning_isnt_an_edit(db: sqlite3.Connection) -> None:
    note = store.create(db, "A", at=NOON)
    pinned = store.set_pinned(db, note.id, True)
    assert pinned is not None and pinned.pinned and pinned.updated_at == NOON
    unpinned = store.set_pinned(db, note.id, False)
    assert unpinned is not None and not unpinned.pinned
    assert store.set_pinned(db, 999, True) is None


def test_delete_takes_tags_versions_and_search(db: sqlite3.Connection) -> None:
    note = store.create(db, ELEPHANT, at=NOON)
    store.update(db, note.id, ELEPHANT + "more", at=NOON + timedelta(minutes=1))
    other = store.create(db, "Other #traps", at=NOON)
    assert store.delete(db, note.id)
    assert not store.delete(db, note.id)
    assert store.get(db, note.id) is None
    assert count(db, "versions") == 0
    assert store.all_tags(db) == [("traps", 1)]
    assert ids(store.summaries(db, q="Elephant")) == []
    assert ids(store.summaries(db)) == [other.id]


def test_the_list_order(db: sqlite3.Connection) -> None:
    old = store.create(db, "Old", at=NOON)
    new = store.create(db, "New", at=NOON + timedelta(hours=1))
    pinned = store.create(db, "Pinned", at=NOON - timedelta(days=9))
    store.set_pinned(db, pinned.id, True)
    assert ids(store.summaries(db)) == [pinned.id, new.id, old.id]
    store.update(db, old.id, "Old, edited", at=NOON + timedelta(hours=2))
    assert ids(store.summaries(db)) == [pinned.id, old.id, new.id]


def test_a_summary(db: sqlite3.Connection) -> None:
    note = store.create(db, ELEPHANT, at=NOON)
    store.set_pinned(db, note.id, True)
    [summary] = store.summaries(db)
    assert summary.title == "The Elephant trap"
    assert summary.snippet.startswith("The d5 pawn looks free")
    assert (summary.pinned, summary.tags, summary.updated_at) == (True, ("qgd", "traps"), NOON)


@pytest.mark.parametrize(
    "query",
    [
        "elephant",  # the title, any case
        "ELEPH",  # the start of a word
        "queen back",  # every word, anywhere
        "Nxd5",  # a move in the text
        "Petrova",  # a player in a PGN block
        "gambit declined",  # its opening
        "D51",  # its ECO
        "  elephant!!  ",  # punctuation is ignored
        'elephant"*(',  # so is anything FTS5 would read as syntax
    ],
)
def test_search_finds(db: sqlite3.Connection, query: str) -> None:
    note = store.create(db, ELEPHANT)
    store.create(db, "# Caro-Kann\n1. e4 c6 #repertoire")
    assert ids(store.summaries(db, q=query)) == [note.id]


@pytest.mark.parametrize("query", ["lephant", "elephant zebra", "Carlsen"])
def test_search_misses(db: sqlite3.Connection, query: str) -> None:
    store.create(db, ELEPHANT)
    assert store.summaries(db, q=query) == []


def test_search_follows_edits(db: sqlite3.Connection) -> None:
    note = store.create(db, ELEPHANT)
    store.update(db, note.id, "# Lucena\nBuild the bridge.")
    assert store.summaries(db, q="elephant") == []
    assert ids(store.summaries(db, q="bridge")) == [note.id]


def test_search_with_accents(db: sqlite3.Connection) -> None:
    note = store.create(db, "# Défense française")
    assert ids(store.summaries(db, q="defense francaise")) == [note.id]


def test_the_best_match_comes_first(db: sqlite3.Connection) -> None:
    once = store.create(db, "# Notes\nThe trap is old.", at=NOON + timedelta(hours=1))
    often = store.create(db, "# Trap\ntrap trap trap", at=NOON)
    assert ids(store.summaries(db, q="trap")) == [often.id, once.id]


def test_a_tag(db: sqlite3.Connection) -> None:
    a = store.create(db, "A #traps #qgd", at=NOON)
    b = store.create(db, "B #traps", at=NOON + timedelta(minutes=1))
    store.create(db, "C #endgame")
    assert ids(store.summaries(db, tag="traps")) == [b.id, a.id]
    assert ids(store.summaries(db, tag="#TRAPS")) == [b.id, a.id]
    assert ids(store.summaries(db, tag="qgd", q="A")) == [a.id]
    assert store.summaries(db, tag="nothing") == []
    assert store.all_tags(db) == [("traps", 2), ("endgame", 1), ("qgd", 1)]


def test_every_note_oldest_first(db: sqlite3.Connection) -> None:
    first = store.create(db, "One")
    second = store.create(db, "Two")
    store.set_pinned(db, second.id, True)
    assert [n.id for n in store.every_note(db)] == [first.id, second.id]
