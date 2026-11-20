"""Exporting notes (ROADMAP 19.5): each note as a Markdown file, exactly as you wrote it, so
its ```pgn and ```fen blocks and its tags stay as typed. ``blunderbook journal export``
writes the files to a folder; the tab's Export downloads them as one .zip.

Files are named by the note's number and title (``3-the-elephant-trap.md``), so two notes
with the same title never share a name, and they carry the time the note was last edited.
"""

import io
import zipfile
from collections.abc import Iterable
from datetime import datetime

from blunderbook_journal import notes
from blunderbook_journal.store import Note

_ZIP_EARLIEST = (1980, 1, 1, 0, 0, 0)  # a .zip can't hold an earlier time


def file_name(note: Note) -> str:
    return f"{note.id}-{notes.slug(note.title)}.md"


def zip_notes(everything: Iterable[Note]) -> bytes:
    """Every note as a .md file in one .zip, with each file's time the note's last edit
    (in local time, as a .zip keeps it)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        for note in everything:
            info = zipfile.ZipInfo(file_name(note), date_time=_zip_time(note.updated_at))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16  # a plain file, readable by you and others
            zipped.writestr(info, note.body.encode("utf-8"))
    return buffer.getvalue()


def _zip_time(moment: datetime) -> tuple[int, int, int, int, int, int]:
    local = moment.astimezone()
    found = (local.year, local.month, local.day, local.hour, local.minute, local.second)
    return max(found, _ZIP_EARLIEST)
