"""Chess.com sync adapter: downloads your games as PGN (CLAUDE.md §8).

API notes, checked 2026-11-05 against the official "Published-Data API" page
(https://www.chess.com/news/view/published-data-api):

Endpoints (read-only, no authentication)
    - ``GET https://api.chess.com/pub/player/{username}/games/archives``:
      ``{"archives": ["https://api.chess.com/pub/player/{username}/games/YYYY/MM", ...]}``,
      in ascending chronological order. Only months with games are listed.
    - ``GET https://api.chess.com/pub/player/{username}/games/{YYYY}/{MM}/pgn``: that month's
      games as one PGN file (``Content-Type: application/x-chess-pgn``, not JSON-encoded;
      ``Content-Disposition: attachment; filename="ChessCom_username_YYYYMM.pgn"``).
      ``YYYY``/``MM`` is the month the game *ended*, with a two-digit month.
    - (Not used: ``.../games/{YYYY}/{MM}`` is the same month as JSON, ``{"games": [...]}``,
      each with a ``pgn`` field.)
    The examples use lowercase usernames, and the page doesn't say whether case matters.
    TODO(verify): send the username lowercased.

Which months
    Past months never change, so download only the months from the last synced month onward
    (§8). The month of ``sync_state.last_synced`` is fetched again because it may have been
    incomplete. TODO(verify): we take the month boundaries as UTC. No HTTP cache table: we
    don't keep ETags. The page offers ``ETag`` / ``Last-Modified`` with ``If-None-Match`` /
    ``If-Modified-Since`` -> 304, and says data
    refreshes "at most once every 12 hours" in one place and every 24 hours in another, so
    a game you just finished may not be there yet.

Rate limits
    Serial access is unlimited: send one request at a time, waiting for each answer.
    Parallel requests may get ``429 Too Many Requests``. Suspicious activity can get the
    application blocked.

User-Agent
    Chess.com asks for "a recognizable user-agent that contains contact information", so they
    can reach you rather than block you. We send
    ``Blunderbook/<version> (local chess mistake library; contact: <chesscom.contact>)``.
    There's no required format. The sync needs ``contact`` set and never fills it in for you.

Status codes
    301: the right URL is elsewhere; follow it. 404: malformed URL, or no such data (e.g. an
    unknown username). 410: there will never be data there; don't ask again.

Game ids
    Each game's ``[Link "https://www.chess.com/game/live/<id>"]`` header gives the
    fingerprint (§7.4). TODO(verify) with a real download: the Link header and ``[%clk]``
    comments in the monthly PGN.
"""

import re
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Final
from urllib.parse import quote

import httpx

from blunderbook.core import pgn
from blunderbook.sources.base import (
    LONGEST_WAIT_S,
    TRIES,
    USER_AGENT,
    SyncError,
    games_in,
    wait_for,
)

BASE_URL: Final = "https://api.chess.com/pub/player"
TIMEOUT: Final = httpx.Timeout(60.0, connect=10.0)
_MONTH = re.compile(r"/games/(\d{4})/(\d{2})/?$")  # the end of an archive URL
_NO_CONTACT = (
    "Set contact under [chesscom] in config.toml: an email address or web page where "
    "Chess.com can reach you. It goes in the User-Agent they ask for."
)

Month = tuple[int, int]  # (year, month)


class ChesscomAdapter:
    """Downloads your Chess.com games as PGN, month by month, oldest first, one request at a
    time."""

    name = "chesscom"

    def __init__(
        self,
        username: str,
        contact: str,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.username = username.strip()
        if not self.username:
            raise SyncError("Set your Chess.com username under [chesscom] in config.toml.")
        self.contact = contact.strip()
        if not self.contact:
            raise SyncError(_NO_CONTACT)
        if not self.contact.isprintable():
            raise SyncError("contact under [chesscom] in config.toml must be one line of text.")
        self._client = client  # tests pass one with a MockTransport
        self._sleep = sleep

    def __repr__(self) -> str:
        return f"ChesscomAdapter(username={self.username!r})"

    @property
    def user_agent(self) -> str:
        return f"{USER_AGENT.removesuffix(')')}; contact: {self.contact})"

    def player_url(self) -> str:
        # TODO(verify): the docs' examples are lowercase; we send the name lowercased.
        return f"{BASE_URL}/{quote(self.username.lower(), safe='')}"

    def fetch_new_pgn(self, since: datetime | None) -> Iterator[str]:
        client = self._client if self._client is not None else httpx.Client(timeout=TIMEOUT)
        try:
            months = self.months(client)
            first = month_of(since) if since is not None else None
            for month in months:
                if first is None or month >= first:
                    yield from self._month(client, month)
        finally:
            if self._client is None:
                client.close()

    def months(self, client: httpx.Client) -> list[Month]:
        """The months with games, oldest first, read from the archive list."""
        response = self._get(client, f"{self.player_url()}/games/archives")
        if response.status_code == 404:
            raise SyncError(f"Chess.com has no player named '{self.username}'.")
        self._check(response)
        try:
            archives = response.json()["archives"]
            urls = [url for url in archives if isinstance(url, str)]
        except ValueError, KeyError, TypeError:
            raise SyncError("Chess.com sent an archive list Blunderbook can't read.") from None
        found = {_month_in(url) for url in urls}
        return sorted(m for m in found if m is not None)

    def _month(self, client: httpx.Client, month: Month) -> Iterator[str]:
        year, mm = month
        response = self._get(client, f"{self.player_url()}/games/{year:04d}/{mm:02d}/pgn")
        if response.status_code == 410:  # "no data will ever be available" there
            return
        self._check(response)
        text = pgn.decode(response.content).text
        yield from games_in(text.splitlines())

    def _get(self, client: httpx.Client, url: str) -> httpx.Response:
        """One request, waiting for its answer before the next (Chess.com asks for serial
        access). A 429 waits and tries again."""
        headers = {"User-Agent": self.user_agent}
        for attempt in range(1, TRIES + 1):
            try:
                response = client.get(url, headers=headers, follow_redirects=True)
            except httpx.HTTPError as exc:
                raise SyncError(f"Can't download your Chess.com games: {exc}") from None
            if response.status_code != 429:
                return response
            wait = wait_for(response)
            if attempt == TRIES or wait > LONGEST_WAIT_S:
                break
            self._sleep(wait)
        raise SyncError(
            "Chess.com is limiting requests right now (HTTP 429). Run the sync again later."
        )

    def _check(self, response: httpx.Response) -> None:
        if response.status_code != 200:
            raise SyncError(
                f"Chess.com answered HTTP {response.status_code} for "
                f"{response.request.url.path}. Run the sync again later."
            )


def month_of(when: datetime) -> Month:
    """The month `when` falls in, in UTC (a time without a zone is UTC)."""
    if when.tzinfo is not None:
        when = when.astimezone(UTC)
    return when.year, when.month


def _month_in(url: str) -> Month | None:
    match = _MONTH.search(url)
    if match is None:
        return None
    month = int(match[1]), int(match[2])
    return month if 1 <= month[1] <= 12 else None
