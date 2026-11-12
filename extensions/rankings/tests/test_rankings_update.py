"""Updating FIDE's lists (ROADMAP 16.1) against a fake server: only what changed is
downloaded, a failure keeps the lists you had, and two months of each list are kept."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import date

import httpx
import pytest
from blunderbook_rankings import extension, fide, net, store, update
from rankings_fakes import (  # noqa: F401  (fixtures)
    DEC,
    NOV,
    Server,
    cfg_file,
    fide_zip,
    month_zip,
    ok,
    player,
    serve_fide,
    server,
    status,
    xml,
)

from blunderbook import ext, host

URLS = [fide.url(s) for s in fide.SPEEDS]


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    with closing(host.open_db(extension)) as c:
        yield c


def run(
    conn: sqlite3.Connection,
    server: Server,
    *,
    stop: bool = False,
    waits: list[float] | None = None,
    steps: list[tuple[str, float]] | None = None,
) -> update.Outcome:
    with server.client() as http:
        return update.update_fide(
            conn,
            http,
            progress=lambda label, done: (steps if steps is not None else []).append((label, done)),
            stop=lambda: stop,
            wait=(waits if waits is not None else []).append,
            today=date(2026, 11, 12),
        )


def months(conn: sqlite3.Connection) -> dict[str, list[str]]:
    return {s: store.fide_months(conn, s) for s in fide.SPEEDS}


def test_first_update(conn: sqlite3.Connection, server: Server) -> None:
    serve_fide(server)
    steps: list[tuple[str, float]] = []
    got = run(conn, server, steps=steps)
    assert got == update.Outcome(
        "fide", True, "FIDE November 2026: standard, rapid and blitz lists updated."
    )
    assert server.urls() == URLS  # one at a time, in order
    assert all(r.headers["User-Agent"] == net.USER_AGENT for r in server.requests)
    assert months(conn) == {s: ["2026-11"] for s in fide.SPEEDS}
    row = store.source(conn, "fide")
    assert row is not None
    assert (row.list_month, row.last_error) == ("2026-11", None)
    assert row.fetched_at is not None and row.fetched_at == row.checked_at
    assert store.validators(conn, URLS[0]) == net.Validators('"standard-nov26"', NOV)
    # Progress goes up to 100%, and says what it's doing.
    fractions = [done for _, done in steps]
    assert fractions == sorted(fractions) and fractions[-1] == 1.0
    assert steps[0][0] == "Downloading FIDE's standard list"
    assert ("Reading FIDE's blitz list", 1.0) in steps


def test_again_is_already_up_to_date(conn: sqlite3.Connection, server: Server) -> None:
    serve_fide(server)
    run(conn, server)
    before = store.source(conn, "fide")
    got = run(conn, server)
    assert got == update.Outcome("fide", False, "FIDE: already up to date (November 2026 lists).")
    sent = server.requests[3:]
    assert [r.headers.get("If-None-Match") for r in sent] == [
        '"standard-nov26"',
        '"rapid-nov26"',
        '"blitz-nov26"',
    ]
    assert all(r.headers.get("If-Modified-Since") == NOV for r in sent)
    after = store.source(conn, "fide")
    assert before is not None and after is not None
    assert after.fetched_at == before.fetched_at  # nothing new
    assert after.checked_at != before.checked_at


def test_a_server_that_ignores_the_question(conn: sqlite3.Connection, server: Server) -> None:
    """A 200 with the same Last-Modified as last time isn't read again."""
    for speed in fide.SPEEDS:
        server.on(fide.url(speed), ok(month_zip(speed, "nov26"), modified=NOV))
    run(conn, server)
    got = run(conn, server)
    assert got.message == "FIDE: already up to date (November 2026 lists)."


def test_a_new_month(conn: sqlite3.Connection, server: Server) -> None:
    serve_fide(server)
    run(conn, server)
    server.on(fide.url("standard"), ok(month_zip("standard", "dec26"), etag='"s2"', modified=DEC))
    got = run(conn, server)
    assert got.message == (
        "FIDE December 2026: standard list updated; rapid and blitz already up to date."
    )
    assert months(conn) == {
        "standard": ["2026-12", "2026-11"],  # last month's kept, for the change
        "rapid": ["2026-11"],
        "blitz": ["2026-11"],
    }
    row = store.source(conn, "fide")
    assert row is not None and row.list_month == "2026-12"


def test_only_two_months_are_kept(conn: sqlite3.Connection, server: Server) -> None:
    for i, month in enumerate(["sep26", "oct26", "nov26"]):
        for speed in fide.SPEEDS:
            server.on(fide.url(speed), ok(month_zip(speed, month), etag=f'"{i}"', modified=None))
        run(conn, server)
    assert months(conn) == {s: ["2026-11", "2026-10"] for s in fide.SPEEDS}


def test_a_republished_month_replaces_it(conn: sqlite3.Connection, server: Server) -> None:
    serve_fide(server)
    run(conn, server)
    fixed = month_zip("standard", "nov26", player(1503014, 2831))
    server.on(fide.url("standard"), ok(fixed, etag='"fixed"'))
    run(conn, server)
    top = store.fide_top(conn, "2026-11", "standard", "open", None, 10)
    assert [(p.fide_id, p.rating) for p in top] == [(1503014, 2831)]


def test_month_from_last_modified(conn: sqlite3.Connection, server: Server) -> None:
    for speed in fide.SPEEDS:
        server.on(fide.url(speed), ok(fide_zip(xml(player(1, 2400)), "players.xml"), modified=DEC))
    run(conn, server)
    assert months(conn)["standard"] == ["2026-12"]


def test_top_lists(conn: sqlite3.Connection, server: Server) -> None:
    players = [
        player(1, 2700, fed="NOR"),
        player(2, 2600, fed="BAN", sex="F", born="2008"),
        player(3, 2500, fed="BAN", born="2000"),
        player(4, 2400, fed="NOR", sex="F", born="1980"),
    ]
    for speed in fide.SPEEDS:
        server.on(fide.url(speed), ok(month_zip(speed, "nov26", *players)))
    run(conn, server)

    def ids(category: fide.Category, fed: str | None = None, limit: int = 100) -> list[int]:
        return [p.fide_id for p in store.fide_top(conn, "2026-11", "blitz", category, fed, limit)]

    assert ids("open") == [1, 2, 3, 4]
    assert ids("open", limit=2) == [1, 2]
    assert ids("women") == [2, 4]
    assert ids("juniors") == [2]
    assert ids("girls") == [2]
    assert ids("open", "BAN") == [2, 3]
    assert ids("women", "NOR") == [4]
    assert [c.players for c in store.fide_counts(conn)] == [4, 4, 4]


# ---------------------------------------------------------------- when it goes wrong


def test_a_failure_keeps_the_lists(conn: sqlite3.Connection, server: Server) -> None:
    serve_fide(server)
    run(conn, server)
    server.on(fide.url("standard"), ok(month_zip("standard", "dec26"), etag='"s2"'))
    server.on(fide.url("rapid"), status(500))
    got = run(conn, server)
    message = f"ratings.fide.com answered HTTP 500 for {fide.url('rapid')}."
    assert got == update.Outcome("fide", False, f"FIDE: {message}", error=message)
    assert months(conn)["standard"] == ["2026-11"]  # December's wasn't kept
    assert store.validators(conn, fide.url("standard")).etag == '"standard-nov26"'
    row = store.source(conn, "fide")
    assert row is not None and row.last_error == message and row.list_month == "2026-11"
    # The next update that works clears it.
    serve_fide(server, "dec26", DEC)
    got = run(conn, server)
    assert got.error is None
    row = store.source(conn, "fide")
    assert row is not None and row.last_error is None


def test_a_bad_file(conn: sqlite3.Connection, server: Server) -> None:
    serve_fide(server)
    server.on(fide.url("blitz"), ok(b"<html>Maintenance</html>"))
    got = run(conn, server)
    assert got.error == "FIDE's blitz list isn't a zip file."
    assert got.message == "FIDE: FIDE's blitz list isn't a zip file."
    assert months(conn) == {s: [] for s in fide.SPEEDS}


def test_offline(conn: sqlite3.Connection, server: Server) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("No route", request=request)

    server.on(fide.url("standard"), refuse)
    got = run(conn, server)
    assert got.error == "Can't reach ratings.fide.com: no connection (are you online?)."


def test_too_big(conn: sqlite3.Connection, server: Server) -> None:
    huge = str(net.MAX_DOWNLOAD_BYTES + 1)
    server.on(fide.url("standard"), lambda r: httpx.Response(200, headers={"Content-Length": huge}))
    got = run(conn, server)
    assert got.error == "ratings.fide.com sent a file too big to be a rating list."


def test_429_waits_once(conn: sqlite3.Connection, server: Server) -> None:
    serve_fide(server)
    good = server.answers[fide.url("standard")][0]
    server.on(fide.url("standard"), status(429), good)
    waits: list[float] = []
    got = run(conn, server, waits=waits)
    assert got.error is None
    assert waits == [60.0]


def test_429_with_retry_after(conn: sqlite3.Connection, server: Server) -> None:
    serve_fide(server)
    good = server.answers[fide.url("standard")][0]
    server.on(fide.url("standard"), status(429, **{"Retry-After": "120"}), good)
    waits: list[float] = []
    run(conn, server, waits=waits)
    assert waits == [120.0]


def test_429_twice_stops(conn: sqlite3.Connection, server: Server) -> None:
    server.on(fide.url("standard"), status(429))
    waits: list[float] = []
    got = run(conn, server, waits=waits)
    assert got.error == (
        "ratings.fide.com asked to slow down (HTTP 429). Try again in a few minutes."
    )
    assert waits == [60.0]


def test_429_too_long_a_wait(conn: sqlite3.Connection, server: Server) -> None:
    server.on(fide.url("standard"), status(429, **{"Retry-After": "3600"}))
    waits: list[float] = []
    got = run(conn, server, waits=waits)
    assert got.error is not None and "slow down" in got.error
    assert waits == []


def test_stop_changes_nothing(conn: sqlite3.Connection, server: Server) -> None:
    serve_fide(server)
    with pytest.raises(net.Stopped):
        run(conn, server, stop=True)
    assert store.source(conn, "fide") is None
    assert months(conn) == {s: [] for s in fide.SPEEDS}


def test_sleeper_stops() -> None:
    with pytest.raises(net.Stopped):
        net.sleeper(lambda: True)(30)


def test_stale() -> None:
    assert update.stale("2026-11", date(2026, 12, 1))
    assert not update.stale("2026-11", date(2026, 11, 30))
    assert not update.stale(None, date(2026, 12, 1))


def test_its_own_database(conn: sqlite3.Connection) -> None:
    assert ext.db_path(extension).name == "rankings.db"
