"""One update of a source's lists (ROADMAP 16.1), shared by ``blunderbook rankings update`` and
(from 16.3) the page's Update button.

Everything is downloaded and read first; the lists are written in one transaction at the
end. A failure at any point leaves the lists as they were and records why; a stop
(``Stopped``) changes nothing at all.
"""

import sqlite3
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx

from blunderbook import host
from blunderbook_rankings import fide, net, store

Step = Callable[[str, float], None]  # what it's doing, and 0..1 of this source


@dataclass(frozen=True, slots=True)
class Outcome:
    source: str  # 'fide' | 'lichess' | 'chesscom'
    changed: bool
    message: str  # one line: "FIDE November 2026: standard, rapid and blitz lists updated."
    error: str | None = None  # the lists are as they were


def update_fide(
    conn: sqlite3.Connection,
    http: httpx.Client,
    *,
    progress: Step,
    stop: Callable[[], bool],
    wait: net.Wait,
    today: date,
) -> Outcome:
    """Download FIDE's three lists, skipping any that hasn't changed, and keep their top
    players. Raises net.Stopped."""
    found: list[tuple[fide.FideList, str, net.Validators]] = []
    unchanged: list[fide.Speed] = []
    count = len(fide.SPEEDS)
    try:
        with tempfile.TemporaryDirectory(prefix="blunderbook-rankings-") as folder:
            for i, speed in enumerate(fide.SPEEDS):
                url = fide.url(speed)
                got = net.download(
                    http,
                    url,
                    Path(folder) / f"{speed}.zip",
                    store.validators(conn, url),
                    wait,
                    _part(progress, f"Downloading FIDE's {speed} list", (i + 0.0) / count, count),
                    stop,
                )
                if got is None:
                    unchanged.append(speed)
                    progress(f"FIDE's {speed} list hasn't changed", (i + 1) / count)
                    continue
                listed = fide.read_list(
                    got.path,
                    speed,
                    _month_of(got.validators.last_modified) or f"{today:%Y-%m}",
                    _part(progress, f"Reading FIDE's {speed} list", (i + 0.5) / count, count),
                    stop,
                )
                found.append((listed, url, got.validators))
    except (net.RankingsError, fide.BadList) as exc:
        with host.transaction(conn):
            store.checked(conn, "fide", at=store.now(), changed=False, error=str(exc))
        return Outcome("fide", False, f"FIDE: {exc}", error=str(exc))

    month = max((listed.month for listed, _, _ in found), default=None)
    with host.transaction(conn):
        for listed, url, got_validators in found:
            store.replace_fide(conn, listed)
            store.save_validators(conn, url, got_validators)
        store.checked(conn, "fide", at=store.now(), changed=bool(found), list_month=month)
    return Outcome("fide", bool(found), _fide_message(conn, found, unchanged))


def _fide_message(
    conn: sqlite3.Connection,
    found: list[tuple[fide.FideList, str, net.Validators]],
    unchanged: list[fide.Speed],
) -> str:
    if not found:
        row = store.source(conn, "fide")
        month = row.list_month if row else None
        when = f" ({fide.month_label(month)} lists)" if month else ""
        return f"FIDE: already up to date{when}."
    month = max(listed.month for listed, _, _ in found)
    updated = _and([listed.speed for listed, _, _ in found])
    noun = "list" if len(found) == 1 else "lists"
    message = f"FIDE {fide.month_label(month)}: {updated} {noun} updated"
    if unchanged:
        message += f"; {_and(list(unchanged))} already up to date"
    return message + "."


def _part(progress: Step, label: str, start: float, count: int) -> Callable[[float], None]:
    """Progress of one half of one list (its download, or reading it), as part of the whole."""
    return lambda done: progress(label, start + done / (2 * count))


def _month_of(last_modified: str | None) -> str | None:
    """A Last-Modified header's "YYYY-MM", or None."""
    if not last_modified:
        return None
    try:
        return f"{parsedate_to_datetime(last_modified):%Y-%m}"
    except TypeError, ValueError:
        return None


def _and(words: list[str]) -> str:
    if len(words) <= 1:
        return "".join(words)
    return ", ".join(words[:-1]) + " and " + words[-1]


def stale(list_month: str | None, today: date) -> bool:
    """A FIDE list from an earlier month than ``today``'s: a newer one is usually out."""
    return list_month is not None and list_month < f"{today:%Y-%m}"
