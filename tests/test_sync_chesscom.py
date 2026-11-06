"""The Chess.com adapter against recorded responses (CLAUDE.md §8). Tests never call the
network: every client here has a MockTransport."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from blunderbook import __version__
from blunderbook.core import pgn
from blunderbook.core.source import detect_source
from blunderbook.sources.base import SourceAdapter, SyncError
from blunderbook.sources.chesscom import ChesscomAdapter, month_of

HTTP = Path(__file__).parent / "fixtures" / "http"
PLAYER = "/pub/player/rashed_blitz/games"
ARCHIVES = (HTTP / "chesscom_archives.json").read_bytes()
MONTHS = {
    f"{PLAYER}/2026/08/pgn": b"",  # a month whose games are gone: nothing in it
    f"{PLAYER}/2026/09/pgn": (HTTP / "chesscom_2026_09.pgn").read_bytes(),
    f"{PLAYER}/2026/10/pgn": (HTTP / "chesscom_2026_10.pgn").read_bytes(),
}

Handler = Callable[[httpx.Request], httpx.Response]


def site(request: httpx.Request) -> httpx.Response:
    """Chess.com as the docs describe it."""
    path = request.url.path
    if path == f"{PLAYER}/archives":
        return httpx.Response(200, content=ARCHIVES, headers={"Content-Type": "application/json"})
    if path in MONTHS:
        return httpx.Response(
            200, content=MONTHS[path], headers={"Content-Type": "application/x-chess-pgn"}
        )
    return httpx.Response(404, json={"code": 0, "message": "not found"})


class Recorder:
    """The handler, plus every request it was sent, in order."""

    def __init__(self, handler: Handler = site) -> None:
        self.handler = handler
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)

    @property
    def paths(self) -> list[str]:
        return [r.url.path for r in self.requests]


def adapter(
    handler: Handler = site, sleeps: list[float] | None = None, username: str = "Rashed_Blitz"
) -> ChesscomAdapter:
    waits = sleeps if sleeps is not None else []
    return ChesscomAdapter(
        username,
        "rashed@example.org",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=waits.append,
    )


def fetch(source: ChesscomAdapter, since: datetime | None = None) -> list[str]:
    return list(source.fetch_new_pgn(since))


# ---------------------------------------------------------------- the requests


def test_it_is_a_source_adapter() -> None:
    source: SourceAdapter = adapter()
    assert source.name == "chesscom"


def test_all_months_oldest_first_one_request_at_a_time() -> None:
    recorder = Recorder()
    fetch(adapter(recorder))
    assert recorder.paths == [
        f"{PLAYER}/archives",
        f"{PLAYER}/2026/08/pgn",
        f"{PLAYER}/2026/09/pgn",
        f"{PLAYER}/2026/10/pgn",
    ]
    assert all(
        str(r.url).startswith("https://api.chess.com/pub/player/") for r in recorder.requests
    )
    assert all(r.method == "GET" for r in recorder.requests)


def test_user_agent_names_the_app_and_your_contact() -> None:
    recorder = Recorder()
    fetch(adapter(recorder))
    expected = (
        f"Blunderbook/{__version__} (local chess mistake library; contact: rashed@example.org)"
    )
    assert {r.headers["User-Agent"] for r in recorder.requests} == {expected}


def test_requests_are_serial() -> None:
    """Each request waits for the one before: the adapter reads an answer before asking
    again (Chess.com: "Your serial access rate is unlimited")."""
    open_now = 0
    most = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal open_now, most
        open_now += 1
        most = max(most, open_now)
        try:
            return site(request)
        finally:
            open_now -= 1

    fetch(adapter(handler))
    assert most == 1


def test_only_months_from_the_last_synced_month_on() -> None:
    recorder = Recorder()
    fetch(adapter(recorder), since=datetime(2026, 9, 21, 19, 47, 52, tzinfo=UTC))
    assert recorder.paths == [
        f"{PLAYER}/archives",
        f"{PLAYER}/2026/09/pgn",
        f"{PLAYER}/2026/10/pgn",
    ]


def test_after_the_last_month_only_the_archive_list_is_read() -> None:
    recorder = Recorder()
    assert fetch(adapter(recorder), since=datetime(2026, 11, 2, tzinfo=UTC)) == []
    assert recorder.paths == [f"{PLAYER}/archives"]


def test_month_of_is_in_utc() -> None:
    assert month_of(datetime(2026, 10, 31, 23, 30, tzinfo=UTC)) == (2026, 10)
    dhaka = timezone(timedelta(hours=6))
    assert month_of(datetime(2026, 11, 1, 3, 0, tzinfo=dhaka)) == (2026, 10)
    assert month_of(datetime(2026, 11, 1, 3, 0)) == (2026, 11)  # no zone means UTC


def test_username_is_lowercased_and_quoted() -> None:
    recorder = Recorder(lambda request: httpx.Response(200, json={"archives": []}))
    fetch(adapter(recorder, username="  Odd/Name "))
    assert recorder.requests[0].url.raw_path == b"/pub/player/odd%2Fname/games/archives"


# ---------------------------------------------------------------- the games


def test_each_game_comes_as_its_own_pgn() -> None:
    games = fetch(adapter())
    assert len(games) == 3
    parsed = [pgn.parse(text) for text in games]
    assert [p.problems for p in parsed] == [(), (), ()]
    found = [p.games[0] for p in parsed]
    assert [detect_source(g.headers).game_id for g in found] == [
        "live/140512345678",
        "live/140599990001",
        "daily/870012345",
    ]
    assert all(detect_source(g.headers).source == "chesscom" for g in found)
    assert all(g.has_clocks for g in found)
    assert [len(g.plies) for g in found] == [12, 13, 4]


def test_the_games_together_are_the_whole_month() -> None:
    whole = pgn.parse(MONTHS[f"{PLAYER}/2026/10/pgn"].decode())
    pieces = [
        g for text in fetch(adapter(), since=datetime(2026, 10, 1)) for g in pgn.parse(text).games
    ]
    assert [g.plies for g in pieces] == [g.plies for g in whole.games]
    assert [dict(g.headers) for g in pieces] == [dict(g.headers) for g in whole.games]


def test_a_month_in_windows_1252_is_read() -> None:
    month = '[White "Rashed_Blitz"]\n[Black "Jos\xe9"]\n\n1. e4 e5 *\n'.encode("cp1252")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/archives"):
            return httpx.Response(
                200, json={"archives": [f"https://api.chess.com{PLAYER}/2026/10"]}
            )
        return httpx.Response(200, content=month)

    (game,) = fetch(adapter(handler))
    assert 'Black "José"' in game


def test_a_410_month_is_skipped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"{PLAYER}/2026/09/pgn":
            return httpx.Response(410)
        return site(request)

    assert len(fetch(adapter(handler))) == 2


def test_redirects_are_followed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"{PLAYER}/2026/09/pgn":
            return httpx.Response(301, headers={"Location": f"{PLAYER}/2026/10/pgn"})
        return site(request)

    assert len(fetch(adapter(handler))) == 4  # September's answer is October's games


def test_archive_list_entries_that_are_not_months_are_ignored() -> None:
    recorder = Recorder(
        lambda request: (
            httpx.Response(
                200,
                json={
                    "archives": [
                        f"https://api.chess.com{PLAYER}/2026/10",
                        f"https://api.chess.com{PLAYER}/2026/10/",  # the same month twice
                        f"https://api.chess.com{PLAYER}/2026/13",
                        "https://example.org/whatever",
                        42,
                    ]
                },
            )
            if request.url.path.endswith("/archives")
            else httpx.Response(200, content=b"")
        )
    )
    fetch(adapter(recorder))
    assert recorder.paths == [f"{PLAYER}/archives", f"{PLAYER}/2026/10/pgn"]


# ---------------------------------------------------------------- settings and errors


@pytest.mark.parametrize(
    ("username", "contact", "message"),
    [
        (" ", "me@example.org", r"Set your Chess.com username under \[chesscom\]"),
        ("rashed", "  ", r"Set contact under \[chesscom\] in config.toml"),
        ("rashed", "me@example.org\r\nX-Evil: 1", "must be one line of text"),
    ],
)
def test_settings_are_needed(username: str, contact: str, message: str) -> None:
    with pytest.raises(SyncError, match=message):
        ChesscomAdapter(username, contact)


def test_unknown_player() -> None:
    with pytest.raises(SyncError, match=r"Chess\.com has no player named 'nobody_here'\."):
        fetch(adapter(username="nobody_here"))


def test_429_waits_then_retries() -> None:
    answers = iter([httpx.Response(429), httpx.Response(429, headers={"Retry-After": "75"})])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"{PLAYER}/2026/09/pgn":
            answer = next(answers, None)
            if answer is not None:
                return answer
        return site(request)

    sleeps: list[float] = []
    assert len(fetch(adapter(handler, sleeps=sleeps))) == 3
    assert sleeps == [60.0, 75.0]


def test_429_three_times_stops_the_sync_and_keeps_earlier_games() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"{PLAYER}/2026/10/pgn":
            return httpx.Response(429)
        return site(request)

    sleeps: list[float] = []
    got: list[str] = []
    with pytest.raises(SyncError, match=r"limiting requests right now \(HTTP 429\)"):
        for game in adapter(handler, sleeps=sleeps).fetch_new_pgn(None):
            got.append(game)
    assert len(got) == 1  # September's game was handed over before October failed
    assert sleeps == [60.0, 60.0]


def test_a_long_retry_after_stops_instead_of_hanging() -> None:
    sleeps: list[float] = []
    source = adapter(
        lambda request: httpx.Response(429, headers={"Retry-After": "3600"}), sleeps=sleeps
    )
    with pytest.raises(SyncError, match="HTTP 429"):
        fetch(source)
    assert sleeps == []


@pytest.mark.parametrize(
    ("archives", "status"),
    [(b"<html>maintenance</html>", 200), (b'{"no": "archives"}', 200), (b'{"archives": 3}', 200)],
)
def test_an_unreadable_archive_list(archives: bytes, status: int) -> None:
    source = adapter(lambda request: httpx.Response(status, content=archives))
    with pytest.raises(SyncError, match="archive list Blunderbook can't read"):
        fetch(source)


def test_other_statuses() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"{PLAYER}/2026/09/pgn":
            return httpx.Response(503)
        return site(request)

    with pytest.raises(
        SyncError, match=rf"Chess.com answered HTTP 503 for {PLAYER}/2026/09/pgn\. Run the sync"
    ):
        fetch(adapter(handler))


def test_network_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("name or service not known", request=request)

    with pytest.raises(
        SyncError, match=r"Can't download your Chess\.com games: name or service not known"
    ) as caught:
        fetch(adapter(handler))
    assert caught.value.__suppress_context__


def test_its_own_client_is_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    made: list[httpx.Client] = []
    real = httpx.Client

    def client(**kwargs: object) -> httpx.Client:
        made.append(real(transport=httpx.MockTransport(site)))
        return made[-1]

    monkeypatch.setattr(httpx, "Client", client)
    games = ChesscomAdapter("rashed_blitz", "me@example.org").fetch_new_pgn(None)
    next(games)
    games.close()
    assert made[0].is_closed
