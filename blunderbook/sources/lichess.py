"""Lichess sync adapter: downloads your games as PGN (CLAUDE.md §8).

API notes, checked 2026-11-05 against the official OpenAPI spec (github.com/lichess-org/api,
``doc/specs/lichess-api.yaml`` and ``tags/games/api-games-user-username.yaml``; lichess.org/api
renders the same spec):

Endpoint
    ``GET https://lichess.org/api/games/user/{username}`` ("Export games of a user").
    Most recent first by default; the response is streamed, and the spec advises reading it
    as a stream because it can be very large.

Header
    ``Accept: application/x-chess-pgn`` (the default) gives PGN text, one game after
    another. ``application/x-ndjson`` gives JSON lines. We use PGN: the core takes PGN only.

Query parameters we send
    - ``since`` (int): "games played since this timestamp". Default: account creation.
      Minimum ``1356998400070``, so it's Unix time in milliseconds.
      TODO(verify): whether it compares with the game's start or end time.
    - ``clocks=true`` (default false): ``[%clk h:mm:ss]`` comments for the time hints.
    - ``opening=true`` (default false): the ``Opening`` header.
    - ``evals=false`` (default false): we run our own Stockfish anyway (§1.5).
    - ``tags=true``, ``moves=true``, ``finished=true``, ``ongoing=false``: the defaults,
      sent explicitly so a change of default can't surprise us.
    - ``sort=dateAsc`` (default ``dateDesc``): oldest first, so a sync that stops halfway
      keeps its progress.
    - ``perfType`` (comma-separated): ``ultraBullet, bullet, blitz, rapid, classical,
      correspondence, chess960, crazyhouse, antichess, atomic, horde, kingOfTheHill,
      racingKings, threeCheck``. We send only the standard ones, which saves downloading
      variant games that the importer rejects anyway (§7.1).
    Not used: ``until``, ``max``, ``vs``, ``rated``, ``color``, ``analysed``, ``pgnInJson``,
    ``accuracy``, ``division``, ``literate``, ``lastFen``, ``withBookmarked`` (several of
    these are NDJSON only).

Authentication
    Optional. A personal API access token goes in ``Authorization: Bearer {token}``. The spec
    lists no scope for this endpoint. A token only raises the download speed. Never log it, and
    redact it from errors (§6).

Rate limits
    The stream is throttled to 20 games/s anonymous, 30 games/s with a token, and 60 games/s
    for your own games with a token. On HTTP 429 the spec says waiting one minute is usually
    enough, but some limits need longer: back off at least 60 s, then retry.

Game ids
    Each game's ``[Site "https://lichess.org/<8-char id>"]`` gives the fingerprint (§7.4).
"""

import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Final
from urllib.parse import quote

import httpx

from blunderbook.sources.base import USER_AGENT, SyncError, games_in, redact

BASE_URL: Final = "https://lichess.org"
# Standard chess only: the importer rejects variants anyway (CLAUDE.md §7.1).
STANDARD: Final = "ultraBullet,bullet,blitz,rapid,classical,correspondence"
WAIT_429_S: Final = 60.0  # the spec: "waiting one minute before retrying"
LONGEST_WAIT_S: Final = 300.0  # a longer Retry-After stops the sync instead of hanging it
TRIES: Final = 3
TIMEOUT: Final = httpx.Timeout(60.0, connect=10.0)  # read = the longest gap in the stream


class LichessAdapter:
    """Downloads your Lichess games as PGN, oldest first, one game at a time as it streams."""

    name = "lichess"

    def __init__(
        self,
        username: str,
        token: str = "",
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.username = username.strip()
        if not self.username:
            raise SyncError("Set your Lichess username under [lichess] in config.toml.")
        self._token = token.strip()
        self._client = client  # tests pass one with a MockTransport
        self._sleep = sleep

    def __repr__(self) -> str:  # never the token
        return f"LichessAdapter(username={self.username!r})"

    def request_params(self, since: datetime | None) -> dict[str, str]:
        params = {
            "clocks": "true",
            "opening": "true",
            "evals": "false",
            "moves": "true",
            "tags": "true",
            "finished": "true",
            "ongoing": "false",
            "sort": "dateAsc",  # oldest first: a sync that stops halfway keeps its progress
            "perfType": STANDARD,
        }
        if since is not None:
            params["since"] = str(since_ms(since))
        return params

    def request_headers(self) -> dict[str, str]:
        headers = {"Accept": "application/x-chess-pgn", "User-Agent": USER_AGENT}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def fetch_new_pgn(self, since: datetime | None) -> Iterator[str]:
        client = self._client if self._client is not None else httpx.Client(timeout=TIMEOUT)
        try:
            yield from self._fetch(client, since)
        finally:
            if self._client is None:
                client.close()

    def _fetch(self, client: httpx.Client, since: datetime | None) -> Iterator[str]:
        url = f"{BASE_URL}/api/games/user/{quote(self.username, safe='')}"
        for attempt in range(1, TRIES + 1):
            try:
                with client.stream(
                    "GET", url, params=self.request_params(since), headers=self.request_headers()
                ) as response:
                    if response.status_code != 429:
                        self._check(response)
                        yield from games_in(response.iter_lines())
                        return
                    wait = _wait_for(response)
            except httpx.HTTPError as exc:
                message = f"Can't download your Lichess games: {exc}"
                raise SyncError(redact(message, self._token)) from None
            if attempt == TRIES or wait > LONGEST_WAIT_S:
                raise SyncError(
                    "Lichess is limiting requests right now (HTTP 429). Run the sync again later."
                )
            self._sleep(wait)

    def _check(self, response: httpx.Response) -> None:
        status = response.status_code
        if status == 200:
            return
        if status in (401, 403) and self._token:
            raise SyncError(
                f"Lichess didn't accept your token (HTTP {status}). Check token under "
                "[lichess] in config.toml, or leave it empty."
            )
        if status == 404:
            raise SyncError(f"Lichess has no user named '{self.username}'.")
        raise SyncError(f"Lichess answered HTTP {status}. Run the sync again later.")


def since_ms(since: datetime) -> int:
    """Lichess's `since`: Unix time in milliseconds. A time without a zone is UTC."""
    if since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    return int(since.timestamp() * 1000)


def _wait_for(response: httpx.Response) -> float:
    """How long to wait after a 429: Retry-After if it says longer, else one minute."""
    try:
        asked = float(response.headers.get("Retry-After", "0"))
    except ValueError:
        asked = 0.0
    return max(WAIT_429_S, asked)
