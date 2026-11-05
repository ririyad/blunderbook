"""The Lichess adapter against recorded responses (CLAUDE.md §8). Tests never call the network:
every client here has a MockTransport."""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from blunderbook.core import pgn
from blunderbook.core.source import detect_source
from blunderbook.sources.base import USER_AGENT, SourceAdapter, SyncError, games_in, redact
from blunderbook.sources.lichess import LichessAdapter, since_ms

HTTP = Path(__file__).parent / "fixtures" / "http"
GAMES = (HTTP / "lichess_user_games.pgn").read_bytes()
TOKEN = "lip_secret0123456789"

Handler = Callable[[httpx.Request], httpx.Response]


def adapter(handler: Handler, token: str = "", sleeps: list[float] | None = None) -> LichessAdapter:
    waits = sleeps if sleeps is not None else []
    return LichessAdapter(
        "Rashed",
        token,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=waits.append,
    )


def chunks(data: bytes, size: int) -> Iterator[bytes]:
    """The body in pieces, as a stream arrives: cut mid-line and mid-game."""
    for start in range(0, len(data), size):
        yield data[start : start + size]


def ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=chunks(GAMES, 97))


def fetch(source: LichessAdapter, since: datetime | None = None) -> list[str]:
    return list(source.fetch_new_pgn(since))


# ---------------------------------------------------------------- the request


def test_it_is_a_source_adapter() -> None:
    source: SourceAdapter = adapter(ok)
    assert source.name == "lichess"


def test_request_asks_for_pgn_with_clocks_and_openings_oldest_first() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return ok(request)

    fetch(adapter(handler))
    (request,) = seen
    assert request.method == "GET"
    assert str(request.url).startswith("https://lichess.org/api/games/user/Rashed?")
    assert dict(request.url.params) == {
        "clocks": "true",
        "opening": "true",
        "evals": "false",
        "moves": "true",
        "tags": "true",
        "finished": "true",
        "ongoing": "false",
        "sort": "dateAsc",
        "perfType": "ultraBullet,bullet,blitz,rapid,classical,correspondence",
    }
    assert request.headers["Accept"] == "application/x-chess-pgn"
    assert request.headers["User-Agent"] == USER_AGENT
    assert "Authorization" not in request.headers


def test_since_is_sent_in_milliseconds() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return ok(request)

    when = datetime(2026, 10, 12, 17, 2, 41, 250000, tzinfo=UTC)
    fetch(adapter(handler), since=when)
    assert seen[0].url.params["since"] == "1791824561250"
    assert since_ms(when) == 1791824561250
    assert since_ms(when.replace(tzinfo=None)) == 1791824561250  # no zone means UTC
    dhaka = when.astimezone(timezone(timedelta(hours=6)))
    assert since_ms(dhaka) == 1791824561250


def test_token_goes_in_the_authorization_header_only() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return ok(request)

    source = adapter(handler, token=f"  {TOKEN}\n")
    fetch(source)
    assert seen[0].headers["Authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in str(seen[0].url)
    assert TOKEN not in repr(source)


def test_username_is_needed() -> None:
    with pytest.raises(SyncError, match=r"Set your Lichess username under \[lichess\]"):
        LichessAdapter("  ")


def test_username_is_quoted_into_the_path() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return ok(request)

    source = LichessAdapter("a/b?c", client=httpx.Client(transport=httpx.MockTransport(handler)))
    fetch(source)
    assert seen[0].url.raw_path.startswith(b"/api/games/user/a%2Fb%3Fc?")


# ---------------------------------------------------------------- the games


def test_each_game_comes_as_its_own_pgn() -> None:
    games = fetch(adapter(ok))
    assert len(games) == 2
    parsed = [pgn.parse(text) for text in games]
    assert [p.problems for p in parsed] == [(), ()]
    first, second = (p.games[0] for p in parsed)
    assert first.headers["Site"] == "https://lichess.org/qGd6Nxd5"
    assert second.headers["Site"] == "https://lichess.org/sChMate3"
    assert detect_source(first.headers).game_id == "qGd6Nxd5"
    assert first.has_clocks and second.has_clocks
    assert first.headers["Opening"].startswith("Queen's Gambit Declined")
    assert len(first.plies) == 18 and len(second.plies) == 7


def test_the_games_together_are_the_whole_download() -> None:
    """Chunking loses nothing: the core reads the same games from either."""
    whole = pgn.parse(GAMES.decode())
    pieces = [g for text in fetch(adapter(ok)) for g in pgn.parse(text).games]
    assert [g.plies for g in pieces] == [g.plies for g in whole.games]
    assert [dict(g.headers) for g in pieces] == [dict(g.headers) for g in whole.games]


def test_no_games_yields_nothing() -> None:
    assert fetch(adapter(lambda request: httpx.Response(200, content=b""))) == []


def test_games_arrive_while_the_stream_is_still_open() -> None:
    """The first game is handed over before the rest of the body is read."""
    read: list[int] = []

    def body() -> Iterator[bytes]:
        for i, piece in enumerate(chunks(GAMES, 64)):
            read.append(i)
            yield piece

    games = adapter(lambda request: httpx.Response(200, content=body())).fetch_new_pgn(None)
    next(games)
    assert len(read) < len(list(chunks(GAMES, 64)))
    games.close()


@pytest.mark.parametrize(
    ("lines", "expected"),
    [
        ([], []),
        (["", "  ", ""], []),
        (["1. e4 e5 *"], ["1. e4 e5 *\n"]),  # a bare move list
        (
            ['[White "A"]', "", "1. e4 *", "", "", '[White "B"]', "", "1. d4 *"],
            ['[White "A"]\n\n1. e4 *\n', '[White "B"]\n\n1. d4 *\n'],
        ),
        (
            ['[White "A"]\r\n', "\r\n", "1. e4 { [%clk 0:03:00] } *\r\n"],
            ['[White "A"]\n\n1. e4 { [%clk 0:03:00] } *\n'],
        ),
        (["1. e4 *", '[White "B"]', "1. d4 *"], ["1. e4 *\n", '[White "B"]\n1. d4 *\n']),
    ],
    ids=["empty", "blank", "bare moves", "two games", "crlf", "no blank lines"],
)
def test_games_in(lines: list[str], expected: list[str]) -> None:
    assert list(games_in(lines)) == expected


# ---------------------------------------------------------------- 429 and errors


def test_429_waits_a_minute_then_retries() -> None:
    answers = iter([httpx.Response(429), httpx.Response(429, headers={"Retry-After": "90"})])

    def handler(request: httpx.Request) -> httpx.Response:
        return next(answers, None) or ok(request)

    sleeps: list[float] = []
    assert len(fetch(adapter(handler, sleeps=sleeps))) == 2
    assert sleeps == [60.0, 90.0]


def test_429_three_times_stops_the_sync() -> None:
    sleeps: list[float] = []
    source = adapter(lambda request: httpx.Response(429), sleeps=sleeps)
    with pytest.raises(SyncError, match=r"limiting requests right now \(HTTP 429\)"):
        fetch(source)
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
    ("status", "token", "message"),
    [
        (404, "", "Lichess has no user named 'Rashed'."),
        (401, TOKEN, r"Lichess didn't accept your token \(HTTP 401\)"),
        (403, TOKEN, r"Lichess didn't accept your token \(HTTP 403\)"),
        (401, "", r"Lichess answered HTTP 401\."),
        (500, "", r"Lichess answered HTTP 500\. Run the sync again later\."),
    ],
)
def test_error_statuses(status: int, token: str, message: str) -> None:
    source = adapter(lambda request: httpx.Response(status, text=f"oops {TOKEN}"), token=token)
    with pytest.raises(SyncError, match=message) as caught:
        fetch(source)
    assert TOKEN not in str(caught.value)


def test_network_errors_never_show_the_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"refused, header was Bearer {TOKEN}", request=request)

    with pytest.raises(SyncError, match="Can't download your Lichess games") as caught:
        fetch(adapter(handler, token=TOKEN))
    assert TOKEN not in str(caught.value)
    assert "[token]" in str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__suppress_context__


def test_a_stream_that_breaks_keeps_the_games_before_it() -> None:
    first_game_end = GAMES.index(b"[Event", 10)

    def body() -> Iterator[bytes]:
        yield GAMES[:first_game_end]
        yield b'[Event "Rated rapid game"]\n'
        raise httpx.ReadError("connection reset")

    games = adapter(lambda request: httpx.Response(200, content=body())).fetch_new_pgn(None)
    got = []
    with pytest.raises(SyncError, match="Can't download your Lichess games: connection reset"):
        for text in games:
            got.append(text)
    assert len(got) == 1
    assert "qGd6Nxd5" in got[0]


def test_redact() -> None:
    assert redact("a lip_x b lip_x", "lip_x") == "a [token] b [token]"
    assert redact("nothing", "") == "nothing"


def test_its_own_client_is_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without a client passed in, the adapter makes one (no network here: its transport is
    mocked) and closes it, even when the sync stops early."""
    made: list[httpx.Client] = []
    real = httpx.Client

    def client(**kwargs: object) -> httpx.Client:
        made.append(real(transport=httpx.MockTransport(ok)))
        return made[-1]

    monkeypatch.setattr(httpx, "Client", client)
    games = LichessAdapter("Rashed").fetch_new_pgn(None)
    next(games)
    games.close()
    assert made[0].is_closed


def test_the_real_network_is_blocked_in_tests() -> None:
    """The conftest guard: a real client can't leave this computer."""
    with httpx.Client() as client, pytest.raises(AssertionError, match=r"lichess\.org"):
        client.get("https://lichess.org/api/games/user/Rashed")
