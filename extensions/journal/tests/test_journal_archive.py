"""Every note as a .md file in a .zip (ROADMAP 19.5): the text exactly as written."""

import io
import sqlite3
import zipfile
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest
from blunderbook_journal import archive, extension, store
from journal_fakes import ELEPHANT, cfg_file  # noqa: F401  (fixtures)

from blunderbook import host


@pytest.fixture
def db(cfg_file: Path) -> Iterator[sqlite3.Connection]:
    with closing(host.open_db(extension)) as conn:
        yield conn


def test_file_names(db: sqlite3.Connection) -> None:
    trap = store.create(db, ELEPHANT)
    blank = store.create(db, "")
    assert archive.file_name(trap) == f"{trap.id}-the-elephant-trap.md"
    assert archive.file_name(blank) == f"{blank.id}-note.md"


def test_the_archive_keeps_each_text_as_written(db: sqlite3.Connection) -> None:
    when = datetime(2026, 11, 7, 12, 30, 5, tzinfo=UTC)
    texts = [ELEPHANT, "# Same title\r\nCRLF kept", "# Same title\n\u00e9\u00e8 \u265e", ""]
    made = [store.create(db, text, at=when) for text in texts]
    with zipfile.ZipFile(io.BytesIO(archive.zip_notes(store.every_note(db)))) as zipped:
        assert zipped.testzip() is None
        names = zipped.namelist()
        assert names == [archive.file_name(note) for note in made]
        assert len(set(names)) == 4  # the same title twice: two files
        for note in made:
            assert zipped.read(archive.file_name(note)).decode("utf-8") == note.body
        local = when.astimezone()
        # A .zip keeps seconds in steps of 2.
        assert zipped.getinfo(names[0]).date_time == (
            local.year, local.month, local.day, local.hour, local.minute, local.second // 2 * 2,
        )  # fmt: skip


def test_an_empty_archive() -> None:
    with zipfile.ZipFile(io.BytesIO(archive.zip_notes([]))) as zipped:
        assert zipped.namelist() == []
