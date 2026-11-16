"""Your ratings, asked of Lichess and Chess.com (CLAUDE.md §8), against hand-built responses.
Tests never call the network: every client here has a MockTransport."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from blunderbook import __version__, sources
from blunderbook.config import ChesscomConfig, Config, LichessConfig
from blunderbook.core.models import RATING_KINDS, Rating, SiteRatings
from blunderbook.sources.base import USER_AGENT, RatingsSource, SyncError, whole
from blunderbook.sources.chesscom import ChesscomAdapter
from blunderbook.sources.lichess import LichessAdapter

HTTP = Path(__file__).parent / "fixtures" / "http"
TOKEN = "lip_secret0123456789"

Handler = Callable[[httpx.Request], httpx.Response]


def load(name: str) -> Any:
    return json.loads((HTTP / name).read_text("utf-8"))


class Recorder:
    """The handler, plus every request it was sent, in order."""

    def __init__(self, handler: Handler) -> None:
        self.handler = handler
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)

    @property
    def paths(self) -> list[str]:
        return [r.url.path for r in self.requests]


def failing(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("no route to host", request=request)


# ---------------------------------------------------------------- Lichess

LICHESS_PAGES = {
    "/api/user/Rashed": load("lichess_user.json"),
    "/api/user/Rashed/perf/blitz": load("lichess_perf_blitz.json"),
    "/api/user/Rashed/perf/rapid": load("lichess_perf_rapid.json"),
    # /perf/classical: not there (404), so classical has no highest or record
}


def lichess_site(request: httpx.Request) -> httpx.Response:
    page = LICHESS_PAGES.get(request.url.path)
    if page is None:
        return httpx.Response(404, json={"error": "Not found"})
    return httpx.Response(200, json=page)


def lichess(handler: Handler = lichess_site, token: str = "") -> LichessAdapter:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return LichessAdapter("Rashed", token, client=client)


def test_lichess_ratings() -> None:
    source: RatingsSource = lichess()
    assert source.fetch_ratings() == SiteRatings(
        source="lichess",
        username="Rashed",
        ratings=(
            # bullet: 0 games, so no rating to show
            Rating(
                kind="blitz",
                rating=1647,
                games=812,
                best=1712,
                best_at=datetime(2026, 8, 14, 18, 22, 5, 120000, tzinfo=UTC),
                wins=401,
                losses=392,
                draws=47,
            ),
            Rating(
                kind="rapid",
                rating=1790,
                games=140,
                best=1821,
                best_at=datetime(2026, 10, 30, 20, 1, 44, tzinfo=UTC),
                wins=80,
                losses=58,
                draws=13,
            ),
            Rating(kind="classical", rating=1702, provisional=True, games=3),
            Rating(kind="puzzle", rating=1985, games=2104),
        ),
    )


def test_lichess_asks_one_page_at_a_time_and_sends_no_token() -> None:
    seen = Recorder(lichess_site)
    lichess(seen, token=TOKEN).fetch_ratings()
    assert seen.paths == [
        "/api/user/Rashed",
        "/api/user/Rashed/perf/blitz",
        "/api/user/Rashed/perf/rapid",
        "/api/user/Rashed/perf/classical",
    ]  # nothing for bullet (never played) or puzzle (no statistics page)
    first = seen.requests[0]
    assert str(first.url).startswith("https://lichess.org/api/user/Rashed?")
    assert dict(first.url.params) == {
        "trophies": "false",
        "profile": "false",
        "rank": "false",
        "fideId": "false",
    }
    for request in seen.requests:
        assert request.method == "GET"
        assert request.headers["Accept"] == "application/json"
        assert request.headers["User-Agent"] == USER_AGENT
        assert "Authorization" not in request.headers  # public data: the token stays here


def test_lichess_daily_is_correspondence() -> None:
    user = {"username": "Rashed", "perfs": {"correspondence": {"games": 9, "rating": 1611}}}
    seen = Recorder(lambda request: httpx.Response(200, json=user))
    (rating,) = lichess(seen).fetch_ratings().ratings
    assert (rating.kind, rating.rating, rating.games) == ("daily", 1611, 9)
    assert seen.paths[1] == "/api/user/Rashed/perf/correspondence"


def test_lichess_a_closed_account_has_no_ratings() -> None:
    closed = {"id": "rashed", "username": "Rashed", "disabled": True}
    got = lichess(lambda request: httpx.Response(200, json=closed)).fetch_ratings()
    assert got == SiteRatings(source="lichess", username="Rashed", ratings=())


@pytest.mark.parametrize(
    ("handler", "message"),
    [
        (lambda r: httpx.Response(404), "Lichess has no user named 'Rashed'."),
        (lambda r: httpx.Response(429), "limiting requests right now (HTTP 429). Try again"),
        (lambda r: httpx.Response(503), "Lichess answered HTTP 503. Try again later."),
        (lambda r: httpx.Response(200, content=b"<html>"), "ratings Blunderbook can't read"),
        (lambda r: httpx.Response(200, json=["a list"]), "ratings Blunderbook can't read"),
        (failing, "Can't get your Lichess ratings: no route to host"),
    ],
)
def test_lichess_problems_are_plain(handler: Handler, message: str) -> None:
    with pytest.raises(SyncError) as caught:
        lichess(handler, token=TOKEN).fetch_ratings()
    assert message in str(caught.value)
    assert TOKEN not in str(caught.value)


def test_lichess_a_429_is_never_waited_for() -> None:
    seen = Recorder(lambda request: httpx.Response(429, headers={"Retry-After": "60"}))
    with pytest.raises(SyncError):
        lichess(seen).fetch_ratings()
    assert len(seen.requests) == 1  # no retry: someone is waiting for the answer


def test_lichess_a_failing_statistics_page_stops_it() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/perf/" in request.url.path:
            return httpx.Response(429)
        return lichess_site(request)

    with pytest.raises(SyncError, match="limiting requests"):
        lichess(handler).fetch_ratings()


# ---------------------------------------------------------------- Chess.com

STATS = load("chesscom_stats.json")


def chesscom_site(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/pub/player/rashed_blitz/stats":
        return httpx.Response(200, json=STATS)
    return httpx.Response(404, json={"code": 0, "message": "not found"})


def chesscom(handler: Handler = chesscom_site) -> ChesscomAdapter:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return ChesscomAdapter("Rashed_Blitz", "rashed@example.com", client=client)


def test_chesscom_ratings() -> None:
    source: RatingsSource = chesscom()
    assert source.fetch_ratings() == SiteRatings(
        source="chesscom",
        username="Rashed_Blitz",
        ratings=(
            # no bullet (never played), and Chess.com has no classical
            Rating(
                kind="blitz",
                rating=1502,
                games=1289,
                best=1561,
                best_at=datetime.fromtimestamp(1786000000, UTC),
                wins=620,
                losses=598,
                draws=71,
            ),
            # rapid: no win yet, so no best
            Rating(kind="rapid", rating=1655, games=4, wins=0, losses=3, draws=1),
            Rating(
                kind="daily",
                rating=1420,
                games=27,
                best=1466,
                best_at=datetime.fromtimestamp(1780000000, UTC),
                wins=14,
                losses=11,
                draws=2,
            ),
            # puzzles: only the highest is given, never the current one
            Rating(
                kind="puzzle",
                rating=None,
                best=2104,
                best_at=datetime.fromtimestamp(1790000000, UTC),
            ),
        ),
    )


def test_chesscom_asks_once_with_the_contact() -> None:
    seen = Recorder(chesscom_site)
    chesscom(seen).fetch_ratings()
    (request,) = seen.requests
    assert request.method == "GET"
    assert str(request.url) == "https://api.chess.com/pub/player/rashed_blitz/stats"
    assert request.headers["User-Agent"] == (
        f"Blunderbook/{__version__} (local chess mistake library; contact: rashed@example.com)"
    )


def test_chesscom_nothing_played_is_no_ratings() -> None:
    got = chesscom(lambda request: httpx.Response(200, json={"fide": 0})).fetch_ratings()
    assert got.ratings == ()


def test_chesscom_odd_values_are_left_out() -> None:
    odd = {
        "chess_blitz": {"last": {"rating": "1502"}},  # text, not a number: no rating
        "chess_rapid": {"last": {"rating": 1600}, "best": "high", "record": None},
        "chess_daily": [],
        "tactics": {"highest": {"rating": 1900, "date": "soon"}},
    }
    got = chesscom(lambda request: httpx.Response(200, json=odd)).fetch_ratings()
    assert got.ratings == (
        Rating(kind="rapid", rating=1600),
        Rating(kind="puzzle", rating=None, best=1900),
    )


@pytest.mark.parametrize(
    ("handler", "message"),
    [
        (lambda r: httpx.Response(404), "Chess.com has no player named 'Rashed_Blitz'."),
        (lambda r: httpx.Response(429), "limiting requests right now (HTTP 429). Try again"),
        (lambda r: httpx.Response(500), "Chess.com answered HTTP 500. Try again later."),
        (lambda r: httpx.Response(200, content=b"oops"), "ratings Blunderbook can't read"),
        (failing, "Can't get your Chess.com ratings: no route to host"),
    ],
)
def test_chesscom_problems_are_plain(handler: Handler, message: str) -> None:
    seen = Recorder(handler)
    with pytest.raises(SyncError) as caught:
        chesscom(seen).fetch_ratings()
    assert message in str(caught.value)
    assert len(seen.requests) == 1  # a 429 is never waited for


# ---------------------------------------------------------------- from config.toml


def test_ratings_for_gives_lichess_no_token() -> None:
    cfg = Config(lichess=LichessConfig(username="rashed", token=TOKEN))
    source = sources.ratings_for("lichess", cfg)
    assert isinstance(source, LichessAdapter)
    assert source.username == "rashed"
    assert source._token == ""


def test_ratings_for_chesscom_needs_the_contact() -> None:
    cfg = Config(chesscom=ChesscomConfig(username="rashed_blitz"))
    with pytest.raises(SyncError, match=r"Set contact under \[chesscom\]"):
        sources.ratings_for("chesscom", cfg)
    with pytest.raises(SyncError, match=r"Set your Lichess username under \[lichess\]"):
        sources.ratings_for("lichess", Config())


def test_whole_numbers_only() -> None:
    assert whole(1502) == 1502
    assert whole(0) == 0
    for odd in (None, "1502", 1502.5, True, [1502]):
        assert whole(odd) is None


def test_kinds_are_in_the_fixed_order() -> None:
    assert RATING_KINDS == ("bullet", "blitz", "rapid", "classical", "daily", "puzzle")
