"""journal.db (ROADMAP 19.1, ``migrations/0001_journal.sql``): your notes, their tags, their
earlier versions and the search index. All of the Journal's SQL is here, with every value a
parameter."""

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from blunderbook import host
from blunderbook_journal import doc, notes

KEEP_VERSIONS = 30
VERSION_EVERY = timedelta(minutes=5)

_WORD = re.compile(r"\w+")


@dataclass(frozen=True, slots=True)
class Note:
    id: int
    title: str  # "" until the note has a line of text
    body: str  # as typed
    pinned: bool
    tags: tuple[str, ...]
    created_at: datetime  # UTC
    updated_at: datetime  # UTC: when the text last changed


@dataclass(frozen=True, slots=True)
class Summary:
    """A note as the list shows it."""

    id: int
    title: str
    snippet: str
    pinned: bool
    tags: tuple[str, ...]
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class Version:
    id: int
    note_id: int
    body: str
    saved_at: datetime  # when this was the note's text


def create(conn: sqlite3.Connection, body: str = "", *, at: datetime | None = None) -> Note:
    moment = _utc(at)
    read = notes.read(body)
    tree = _tree(body)
    with host.transaction(conn):
        cursor = conn.execute(
            "INSERT INTO notes (title, snippet, body, doc, doc_version, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                read.title,
                read.snippet,
                body,
                tree,
                doc.DOC_VERSION,
                moment.isoformat(),
                moment.isoformat(),
            ),
        )
        note_id = int(cursor.lastrowid or 0)
        _index(conn, note_id, body, read)
    found = get(conn, note_id)
    assert found is not None
    return found


def get(conn: sqlite3.Connection, note_id: int) -> Note | None:
    row = conn.execute(
        "SELECT id, title, body, pinned, created_at, updated_at FROM notes WHERE id = ?",
        (note_id,),
    ).fetchone()
    if row is None:
        return None
    found, title, body, pinned, created, updated = row
    return Note(
        id=found,
        title=title,
        body=body,
        pinned=bool(pinned),
        tags=_tags(conn, found),
        created_at=datetime.fromisoformat(created),
        updated_at=datetime.fromisoformat(updated),
    )


def update(
    conn: sqlite3.Connection, note_id: int, body: str, *, at: datetime | None = None
) -> Note | None:
    """Save new text. The text it replaces is kept as a version when the newest version is
    over 5 minutes old (or there's none); the newest 30 stay. The same text again changes
    nothing. None when there's no such note."""
    moment = _utc(at)
    with host.transaction(conn):
        row = conn.execute("SELECT body, updated_at FROM notes WHERE id = ?", (note_id,)).fetchone()
        if row is None:
            return None
        old_body, old_at = row
        if old_body != body:
            newest = conn.execute(
                "SELECT max(saved_at) FROM versions WHERE note_id = ?", (note_id,)
            ).fetchone()[0]
            due = newest is None or moment - datetime.fromisoformat(newest) > VERSION_EVERY
            if due and old_body.strip():
                conn.execute(
                    "INSERT INTO versions (note_id, body, saved_at) VALUES (?, ?, ?)",
                    (note_id, old_body, old_at),
                )
                conn.execute(
                    "DELETE FROM versions WHERE note_id = ? AND id NOT IN"
                    " (SELECT id FROM versions WHERE note_id = ?"
                    " ORDER BY saved_at DESC, id DESC LIMIT ?)",
                    (note_id, note_id, KEEP_VERSIONS),
                )
            read = notes.read(body)
            conn.execute(
                "UPDATE notes SET title = ?, snippet = ?, body = ?, doc = ?, doc_version = ?,"
                " updated_at = ? WHERE id = ?",
                (
                    read.title,
                    read.snippet,
                    body,
                    _tree(body),
                    doc.DOC_VERSION,
                    moment.isoformat(),
                    note_id,
                ),
            )
            _index(conn, note_id, body, read)
    return get(conn, note_id)


def document(conn: sqlite3.Connection, note_id: int) -> dict[str, object] | None:
    """The note as Reading mode draws it (:mod:`blunderbook_journal.doc`). A tree made by
    an older parser, or none, is made again and kept. None when there's no such note."""
    row = conn.execute("SELECT body, doc, doc_version FROM notes WHERE id = ?", (note_id,))
    found = row.fetchone()
    if found is None:
        return None
    body, kept, version = found
    if kept is not None and version == doc.DOC_VERSION:
        tree: dict[str, object] = json.loads(kept)
        return tree
    tree = doc.parse(body)
    conn.execute(
        "UPDATE notes SET doc = ?, doc_version = ? WHERE id = ?",
        (json.dumps(tree, ensure_ascii=False, separators=(",", ":")), doc.DOC_VERSION, note_id),
    )
    return tree


def set_pinned(conn: sqlite3.Connection, note_id: int, pinned: bool) -> Note | None:
    """Pin or unpin a note. It isn't an edit: the note keeps its place in time."""
    conn.execute("UPDATE notes SET pinned = ? WHERE id = ?", (int(pinned), note_id))
    return get(conn, note_id)


def delete(conn: sqlite3.Connection, note_id: int) -> bool:
    """Delete a note with its tags and versions. False when there was none."""
    with host.transaction(conn):
        gone = conn.execute("DELETE FROM notes WHERE id = ?", (note_id,)).rowcount
        conn.execute("DELETE FROM search WHERE rowid = ?", (note_id,))
    return gone > 0


def summaries(conn: sqlite3.Connection, *, q: str = "", tag: str = "") -> list[Summary]:
    """The notes, pinned first, then the latest edited. ``q`` keeps the notes that have
    every word of it (each also as the start of a longer word), in the title, the text or
    a PGN's players and opening, best matches first. ``tag`` keeps one tag's notes."""
    words = _WORD.findall(q)
    where: list[str] = []
    params: list[object] = []
    order = "n.pinned DESC, n.updated_at DESC, n.id DESC"
    joins = ""
    if words:
        joins = " JOIN search ON search.rowid = n.id"
        where.append("search MATCH ?")
        params.append(" ".join(f'"{w}"*' for w in words))
        order = "n.pinned DESC, search.rank, n.updated_at DESC"
    if tag.strip():
        where.append("n.id IN (SELECT note_id FROM tags WHERE tag = ?)")
        params.append(tag.strip().lstrip("#").casefold())
    sql = "SELECT n.id, n.title, n.snippet, n.pinned, n.updated_at FROM notes n" + joins
    if where:
        sql += " WHERE " + " AND ".join(where)
    rows = conn.execute(f"{sql} ORDER BY {order}", params).fetchall()
    tagged = _all_note_tags(conn)
    return [
        Summary(
            id=note_id,
            title=title,
            snippet=snippet,
            pinned=bool(pinned),
            tags=tagged.get(note_id, ()),
            updated_at=datetime.fromisoformat(updated),
        )
        for note_id, title, snippet, pinned, updated in rows
    ]


def all_tags(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    """Every tag in use and how many notes have it, most used first."""
    rows = conn.execute(
        "SELECT tag, count(*) FROM tags GROUP BY tag ORDER BY count(*) DESC, tag"
    ).fetchall()
    return [(tag, int(count)) for tag, count in rows]


def versions(conn: sqlite3.Connection, note_id: int) -> list[Version]:
    """A note's earlier texts, newest first."""
    rows = conn.execute(
        "SELECT id, note_id, body, saved_at FROM versions WHERE note_id = ?"
        " ORDER BY saved_at DESC, id DESC",
        (note_id,),
    ).fetchall()
    return [Version(i, n, b, datetime.fromisoformat(s)) for i, n, b, s in rows]


def every_note(conn: sqlite3.Connection) -> list[Note]:
    """All notes, oldest first: for the export."""
    ids = [row[0] for row in conn.execute("SELECT id FROM notes ORDER BY id")]
    return [note for note_id in ids if (note := get(conn, note_id)) is not None]


def _index(conn: sqlite3.Connection, note_id: int, body: str, read: notes.Read) -> None:
    """Bring the note's tags and search row in step with its text."""
    conn.execute("DELETE FROM tags WHERE note_id = ?", (note_id,))
    conn.executemany(
        "INSERT INTO tags (note_id, tag) VALUES (?, ?)", [(note_id, t) for t in read.tags]
    )
    conn.execute("DELETE FROM search WHERE rowid = ?", (note_id,))
    conn.execute(
        "INSERT INTO search (rowid, title, body, players) VALUES (?, ?, ?, ?)",
        (note_id, read.title, body, read.players),
    )


def _tree(body: str) -> str:
    return json.dumps(doc.parse(body), ensure_ascii=False, separators=(",", ":"))


def _tags(conn: sqlite3.Connection, note_id: int) -> tuple[str, ...]:
    rows = conn.execute("SELECT tag FROM tags WHERE note_id = ? ORDER BY tag", (note_id,))
    return tuple(row[0] for row in rows)


def _all_note_tags(conn: sqlite3.Connection) -> dict[int, tuple[str, ...]]:
    found: dict[int, list[str]] = {}
    for note_id, tag in conn.execute("SELECT note_id, tag FROM tags ORDER BY note_id, tag"):
        found.setdefault(note_id, []).append(tag)
    return {note_id: tuple(t) for note_id, t in found.items()}


def _utc(at: datetime | None) -> datetime:
    return (at or datetime.now(UTC)).astimezone(UTC)
