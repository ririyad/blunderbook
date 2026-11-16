"""Lichess sync adapter: downloads your games as PGN, and asks for your ratings (CLAUDE.md §8).

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

Ratings (``fetch_ratings``), checked 2026-11-16 against the same spec
(``tags/users/api-user-username.yaml``, ``tags/users/api-user-username-perf-perf.yaml``,
``schemas/Perfs.yaml``, ``Perf.yaml``, ``PerfStat.yaml``, ``PerfType.yaml``):

``GET /api/user/{username}`` ("Get user public data")
    Query parameters, all sent explicitly: ``trophies=false`` (the default), ``profile=false``
    (default true; we don't show it), ``rank=false`` (the default), ``fideId=false`` (the
    default). The answer's ``perfs`` has one object per kind of play: ``bullet``, ``blitz``,
    ``rapid``, ``classical``, ``correspondence``, ``puzzle`` (and variants, ``ultraBullet``
    and the puzzle modes, which we leave out). Each is ``{games, rating, rd, prog}``, with
    ``prov: true`` only while the rating is provisional. ``username`` is the name as Lichess
    spells it. TODO(verify): whether a kind you never played is left out or listed with 0
    games; we skip one with no games either way.

``GET /api/user/{username}/perf/{perf}`` ("Get performance statistics of a user")
    ``perf`` is a PerfType: ``bullet``, ``blitz``, ``rapid``, ``classical``,
    ``correspondence`` (not ``puzzle``). In the answer, ``stat.highest`` is ``{int, at,
    gameId}`` (your highest rating and when; optional), and ``stat.count`` has ``win``,
    ``loss`` and ``draw`` (every game of that kind, casual ones too). One request per kind
    you have games in, one at a time.

    Both are public: no token is sent, so none can leak. A 429 is a message, not a wait.
"""

import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any, Final
from urllib.parse import quote

import httpx

from blunderbook.core.models import RATING_KINDS, Rating, RatingKind, SiteRatings
from blunderbook.sources.base import (
    LONGEST_WAIT_S,
    RATINGS_TIMEOUT,
    TRIES,
    USER_AGENT,
    SyncError,
    games_in,
    redact,
    wait_for,
    whole,
)

BASE_URL: Final = "https://lichess.org"
# Standard chess only: the importer rejects variants anyway (CLAUDE.md §7.1).
STANDARD: Final = "ultraBullet,bullet,blitz,rapid,classical,correspondence"
TIMEOUT: Final = httpx.Timeout(60.0, connect=10.0)  # read = the longest gap in the stream
# Lichess's name for each kind of play we show a rating for.
PERFS: Final[dict[RatingKind, str]] = {
    "bullet": "bullet",
    "blitz": "blitz",
    "rapid": "rapid",
    "classical": "classical",
    "daily": "correspondence",
    "puzzle": "puzzle",
}
USER_PARAMS: Final = {"trophies": "false", "profile": "false", "rank": "false", "fideId": "false"}
_UNREADABLE: Final = "Lichess sent ratings Blunderbook can't read."


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
                    wait = wait_for(response)
            except httpx.HTTPError as exc:
                message = f"Can't download your Lichess games: {exc}"
                raise SyncError(redact(message, self._token)) from None
            if attempt == TRIES or wait > LONGEST_WAIT_S:
                raise SyncError(
                    "Lichess is limiting requests right now (HTTP 429). Run the sync again later."
                )
            self._sleep(wait)

    # ------------------------------------------------------------ ratings

    def fetch_ratings(self) -> SiteRatings:
        """Your Lichess ratings now: one request for the ratings, then one per kind of play
        for its highest rating and record. Public data, so no token is sent."""
        client = self._client if self._client is not None else httpx.Client(timeout=RATINGS_TIMEOUT)
        try:
            return self._ratings(client)
        finally:
            if self._client is None:
                client.close()

    def _ratings(self, client: httpx.Client) -> SiteRatings:
        url = f"{BASE_URL}/api/user/{quote(self.username, safe='')}"
        user = self._json(client, url, USER_PARAMS)
        if user is None:
            raise SyncError(f"Lichess has no user named '{self.username}'.")
        perfs = user.get("perfs")
        if not isinstance(perfs, dict):
            perfs = {}  # a closed account has none
        ratings: list[Rating] = []
        for kind in RATING_KINDS:
            perf = perfs.get(PERFS[kind])
            if not isinstance(perf, dict):
                continue
            rating, games = whole(perf.get("rating")), whole(perf.get("games"))
            if rating is None or not games:
                continue  # never played: there's no rating to show
            # No statistics page for puzzles, and a missing one only loses the extras.
            stat = None if kind == "puzzle" else self._json(client, f"{url}/perf/{PERFS[kind]}")
            ratings.append(_rating(kind, rating, games, perf.get("prov") is True, stat))
        name = user.get("username")
        return SiteRatings(
            source="lichess",
            username=name if isinstance(name, str) and name else self.username,
            ratings=tuple(ratings),
        )

    def _json(
        self, client: httpx.Client, url: str, params: dict[str, str] | None = None
    ) -> dict[str, Any] | None:
        """One request, answered with a JSON object. None for a 404."""
        headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        try:
            response = client.get(url, params=params, headers=headers)
        except httpx.HTTPError as exc:
            raise SyncError(f"Can't get your Lichess ratings: {exc}") from None
        if response.status_code == 404:
            return None
        if response.status_code == 429:
            raise SyncError(
                "Lichess is limiting requests right now (HTTP 429). Try again in a minute."
            )
        if response.status_code != 200:
            raise SyncError(f"Lichess answered HTTP {response.status_code}. Try again later.")
        try:
            data = response.json()
        except ValueError:
            raise SyncError(_UNREADABLE) from None
        if not isinstance(data, dict):
            raise SyncError(_UNREADABLE)
        return data

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


def _rating(
    kind: RatingKind, rating: int, games: int, provisional: bool, page: dict[str, Any] | None
) -> Rating:
    """One kind of play: the rating, plus the highest and the record from its statistics
    page (``page``) when it has them."""
    stat = page.get("stat") if page is not None else None
    stat = stat if isinstance(stat, dict) else {}
    highest, count = stat.get("highest"), stat.get("count")
    highest = highest if isinstance(highest, dict) else {}
    count = count if isinstance(count, dict) else {}
    best = whole(highest.get("int"))
    return Rating(
        kind=kind,
        rating=rating,
        provisional=provisional,
        games=games,
        best=best,
        best_at=_moment(highest.get("at")) if best is not None else None,
        wins=whole(count.get("win")),
        losses=whole(count.get("loss")),
        draws=whole(count.get("draw")),
    )


def _moment(value: object) -> datetime | None:
    """Lichess's date-time text ("2022-02-23T13:44:54.633Z") in UTC, or None."""
    if not isinstance(value, str):
        return None
    try:
        when = datetime.fromisoformat(value)
    except ValueError:
        return None
    return when.replace(tzinfo=UTC) if when.tzinfo is None else when.astimezone(UTC)
