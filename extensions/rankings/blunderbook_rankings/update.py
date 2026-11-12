"""One update of a source's lists (ROADMAP 16.1, 16.2), shared by ``blunderbook rankings
update`` and (from 16.3) the page's Update button.

Each source is downloaded and read first; its lists are written in one transaction at the
end. A failure at any point leaves that source's lists as they were and records why; a stop
(``Stopped``) changes nothing in the source being updated. Sources are separate: one that
fails doesn't stop the next.
"""

import sqlite3
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Final

import httpx

from blunderbook import host
from blunderbook_rankings import chesscom, fide, lichess, net, store
from blunderbook_rankings.site import SitePlayer

Step = Callable[[str, float], None]  # what it's doing, and 0..1 of this source

SOURCES: Final = ("fide", "lichess", "chesscom")
NAMES: Final = {"fide": "FIDE", "lichess": "Lichess", "chesscom": "Chess.com"}


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
        return _failed(conn, "fide", exc)

    month = max((listed.month for listed, _, _ in found), default=None)
    with host.transaction(conn):
        for listed, url, got_validators in found:
            store.replace_fide(conn, listed)
            store.save_validators(conn, url, got_validators)
        store.checked(conn, "fide", at=store.now(), changed=bool(found), list_month=month)
    return Outcome("fide", bool(found), _fide_message(conn, found, unchanged))


def update_lichess(
    conn: sqlite3.Connection,
    http: httpx.Client,
    *,
    progress: Step,
    stop: Callable[[], bool],
    wait: net.Wait,
) -> Outcome:
    """Download Lichess's five leaderboards, one at a time. Raises net.Stopped."""
    boards: dict[str, list[SitePlayer]] = {}
    count = len(lichess.BOARDS)
    try:
        for i, board in enumerate(lichess.BOARDS):
            if stop():
                raise net.Stopped
            progress(f"Downloading Lichess's {lichess.NAMES[board]} leaderboard", i / count)
            response = net.get_json(http, lichess.url(board), wait)
            boards[board] = lichess.parse(board, response.content)
    except net.RankingsError as exc:
        return _failed(conn, "lichess", exc)
    progress("Lichess's leaderboards", 1.0)
    with host.transaction(conn):
        store.replace_boards(conn, "lichess", boards)
        store.checked(conn, "lichess", at=store.now(), changed=True)
    return Outcome("lichess", True, f"Lichess: {count} leaderboards updated.")


def update_chesscom(
    conn: sqlite3.Connection,
    http: httpx.Client,
    *,
    progress: Step,
    stop: Callable[[], bool],
    wait: net.Wait,
    contact: str = "",
) -> Outcome:
    """Download Chess.com's leaderboards (one answer for all of them), unless they haven't
    changed. Raises net.Stopped."""
    if stop():
        raise net.Stopped
    saved = store.validators(conn, chesscom.URL)
    headers = net.conditional(saved) | {"User-Agent": net.user_agent(contact)}
    progress("Downloading Chess.com's leaderboards", 0.0)
    try:
        response = net.get_json(http, chesscom.URL, wait, headers)
        if net.unchanged(response, saved):
            with host.transaction(conn):
                store.checked(conn, "chesscom", at=store.now(), changed=False)
            progress("Chess.com's leaderboards haven't changed", 1.0)
            return Outcome("chesscom", False, "Chess.com: already up to date.")
        boards = chesscom.parse(response.content)
    except net.RankingsError as exc:
        return _failed(conn, "chesscom", exc)
    progress("Chess.com's leaderboards", 1.0)
    with host.transaction(conn):
        store.replace_boards(conn, "chesscom", boards)
        store.save_validators(conn, chesscom.URL, net.validators(response))
        store.checked(conn, "chesscom", at=store.now(), changed=True)
    noun = "leaderboard" if len(boards) == 1 else "leaderboards"
    return Outcome("chesscom", True, f"Chess.com: {len(boards)} {noun} updated.")


def one(
    conn: sqlite3.Connection,
    http: httpx.Client,
    source: str,
    *,
    progress: Step,
    stop: Callable[[], bool],
    wait: net.Wait,
    today: date,
    contact: str = "",
) -> Outcome:
    """Update one of SOURCES."""
    if source == "fide":
        return update_fide(conn, http, progress=progress, stop=stop, wait=wait, today=today)
    if source == "lichess":
        return update_lichess(conn, http, progress=progress, stop=stop, wait=wait)
    if source == "chesscom":
        return update_chesscom(conn, http, progress=progress, stop=stop, wait=wait, contact=contact)
    raise ValueError(f"Unknown source: {source}")


def _failed(conn: sqlite3.Connection, source: str, exc: Exception) -> Outcome:
    """Record why ``source``'s update failed; its lists stay as they were."""
    with host.transaction(conn):
        store.checked(conn, source, at=store.now(), changed=False, error=str(exc))
    return Outcome(source, False, f"{NAMES[source]}: {exc}", error=str(exc))


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
