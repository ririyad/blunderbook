"""The Lichess and Chess.com leaderboards (ROADMAP 16.2): reading their answers, and updating
them against a fake server."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing

import pytest
from blunderbook_rankings import chesscom, extension, lichess, net, store, update
from blunderbook_rankings.site import BadBoard, SitePlayer
from rankings_fakes import (  # noqa: F401  (fixtures)
    Server,
    cfg_file,
    chesscom_json,
    lichess_json,
    ok,
    serve_sites,
    server,
    status,
)

from blunderbook import host


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    with closing(host.open_db(extension)) as c:
        yield c


# ---------------------------------------------------------------- Lichess's answer


def test_lichess_board() -> None:
    data = lichess_json("blitz", ("DrNykterstein", 3200, 12), ("Zhigalko_Sergei", 3100, -5))
    assert lichess.parse("blitz", data) == [
        SitePlayer(1, "DrNykterstein", "GM", 3200, 12),
        SitePlayer(2, "Zhigalko_Sergei", "GM", 3100, -5),
    ]


def test_lichess_without_a_title_or_progress() -> None:
    data = json.dumps(
        {"users": [{"id": "a", "username": "a", "perfs": {"rapid": {"rating": 2500}}}]}
    ).encode()
    assert lichess.parse("rapid", data) == [SitePlayer(1, "a", None, 2500, None)]


def test_lichess_skips_what_it_cant_read() -> None:
    users = [
        "not a user",
        {"username": "NoPerf"},
        {"username": "OtherPerf", "perfs": {"bullet": {"rating": 3000}}},
        {"username": "BoolRating", "perfs": {"blitz": {"rating": True}}},
        {"perfs": {"blitz": {"rating": 3000}}},
        {"username": "Good", "perfs": {"blitz": {"rating": 2900, "progress": 3}}},
    ]
    got = lichess.parse("blitz", json.dumps({"users": users}).encode())
    assert got == [SitePlayer(1, "Good", None, 2900, 3)]


@pytest.mark.parametrize("data", [b"<html>", b"[]", b'{"users": {}}', b"{}"])
def test_lichess_not_a_board(data: bytes) -> None:
    with pytest.raises(BadBoard, match="Lichess's Classical leaderboard couldn't be read"):
        lichess.parse("classical", data)


# ---------------------------------------------------------------- Chess.com's answer


def test_chesscom_boards() -> None:
    got = chesscom.parse(chesscom_json())
    assert list(got) == list(chesscom.BOARDS)  # tactics and other boards are left out
    assert got["live_blitz"] == [
        SitePlayer(1, "Hikaru", None, 3300, None),
        SitePlayer(2, "MagnusCarlsen", None, 3290, None),
    ]


def test_chesscom_sorted_by_rank_and_capped() -> None:
    entries = [{"username": f"p{i}", "score": 3000 - i, "rank": i} for i in range(60, 0, -1)]
    entries.append({"username": "NoScore", "rank": 61})
    entries.append({"username": "Titled", "score": 1, "rank": 62, "title": "IM"})
    got = chesscom.parse(json.dumps({"daily": entries}).encode())
    assert list(got) == ["daily"]  # the boards that are there
    assert [p.username for p in got["daily"][:3]] == ["p1", "p2", "p3"]
    assert len(got["daily"]) == chesscom.TOP


def test_chesscom_title_when_present() -> None:
    entries = [{"username": "Titled", "score": 2700, "rank": 1, "title": "GM"}]
    got = chesscom.parse(json.dumps({"live_rapid": entries}).encode())
    assert got["live_rapid"] == [SitePlayer(1, "Titled", "GM", 2700, None)]


@pytest.mark.parametrize("data", [b"<html>", b"[]", b'{"tactics": []}', b'{"daily": {}}'])
def test_chesscom_not_leaderboards(data: bytes) -> None:
    with pytest.raises(BadBoard, match=r"Chess.com's leaderboards couldn't be read"):
        chesscom.parse(data)


def test_long_names_are_cut() -> None:
    data = lichess_json("blitz", ("x" * 80, 3000, 0))
    assert lichess.parse("blitz", data)[0].username == "x" * 50


def test_profiles() -> None:
    assert lichess.profile("DrNykterstein") == "https://lichess.org/@/DrNykterstein"
    assert chesscom.profile("Hikaru") == "https://www.chess.com/member/Hikaru"


# ---------------------------------------------------------------- updating Lichess


def run_lichess(conn: sqlite3.Connection, server: Server, stop: bool = False) -> update.Outcome:
    with server.client() as http:
        return update.update_lichess(
            conn, http, progress=lambda *_: None, stop=lambda: stop, wait=lambda s: None
        )


def test_lichess_update(conn: sqlite3.Connection, server: Server) -> None:
    serve_sites(server)
    got = run_lichess(conn, server)
    assert got == update.Outcome("lichess", True, "Lichess: 5 leaderboards updated.")
    assert server.urls() == [lichess.url(b) for b in lichess.BOARDS]  # one at a time
    assert lichess.url("blitz") == "https://lichess.org/api/player/top/100/blitz"
    assert store.board(conn, "lichess", "blitz") == [SitePlayer(1, "DrNykterstein", "GM", 3200, 12)]
    assert store.board_counts(conn, "lichess") == {b: 1 for b in lichess.BOARDS}


def test_lichess_failure_keeps_the_boards(conn: sqlite3.Connection, server: Server) -> None:
    serve_sites(server)
    run_lichess(conn, server)
    server.on(lichess.url("rapid"), status(429), status(429))
    server.on(
        lichess.url("bullet"),
        ok(lichess_json("bullet", ("NewTop", 3300, 1)), modified=None),
    )
    got = run_lichess(conn, server)
    assert got.error == "lichess.org asked to slow down (HTTP 429). Try again in a few minutes."
    assert store.board(conn, "lichess", "bullet")[0].username == "DrNykterstein"  # as it was
    row = store.source(conn, "lichess")
    assert row is not None and row.last_error == got.error


def test_lichess_bad_answer(conn: sqlite3.Connection, server: Server) -> None:
    serve_sites(server)
    server.on(lichess.url("classical"), ok(b"<html>busy</html>", modified=None))
    got = run_lichess(conn, server)
    assert got.message == "Lichess: Lichess's Classical leaderboard couldn't be read."
    assert store.board_counts(conn, "lichess") == {}


def test_lichess_stop(conn: sqlite3.Connection, server: Server) -> None:
    serve_sites(server)
    with pytest.raises(net.Stopped):
        run_lichess(conn, server, stop=True)
    assert server.requests == []
    assert store.source(conn, "lichess") is None


# ---------------------------------------------------------------- updating Chess.com


def run_chesscom(
    conn: sqlite3.Connection, server: Server, waits: list[float] | None = None
) -> update.Outcome:
    with server.client() as http:
        return update.update_chesscom(
            conn,
            http,
            progress=lambda *_: None,
            stop=lambda: False,
            wait=(waits if waits is not None else []).append,
        )


def test_chesscom_update_and_304(conn: sqlite3.Connection, server: Server) -> None:
    serve_sites(server)
    assert run_chesscom(conn, server).message == "Chess.com: 4 leaderboards updated."
    first = store.source(conn, "chesscom")
    got = run_chesscom(conn, server)
    assert got == update.Outcome("chesscom", False, "Chess.com: already up to date.")
    assert server.requests[-1].headers["If-None-Match"] == '"cc-1"'
    row = store.source(conn, "chesscom")
    assert first is not None and row is not None
    assert row.fetched_at == first.fetched_at and row.checked_at != first.checked_at
    assert store.board_counts(conn, "chesscom") == {b: 2 for b in chesscom.BOARDS}


def test_chesscom_new_boards_replace_the_old(conn: sqlite3.Connection, server: Server) -> None:
    serve_sites(server)
    run_chesscom(conn, server)
    server.on(chesscom.URL, ok(chesscom_json(daily=[("Daily1", 2600)]), etag='"cc-2"'))
    assert run_chesscom(conn, server).message == "Chess.com: 1 leaderboard updated."
    assert store.board_counts(conn, "chesscom") == {"daily": 1}


def test_chesscom_429_waits(conn: sqlite3.Connection, server: Server) -> None:
    server.on(chesscom.URL, status(429, **{"Retry-After": "90"}), ok(chesscom_json()))
    waits: list[float] = []
    assert run_chesscom(conn, server, waits).error is None
    assert waits == [90.0]


def test_chesscom_failure(conn: sqlite3.Connection, server: Server) -> None:
    serve_sites(server)
    run_chesscom(conn, server)
    server.on(chesscom.URL, status(410))
    got = run_chesscom(conn, server)
    assert got.error == f"api.chess.com answered HTTP 410 for {chesscom.URL}."
    assert store.board_counts(conn, "chesscom") == {b: 2 for b in chesscom.BOARDS}


# ---------------------------------------------------------------- the User-Agent


def test_user_agent() -> None:
    assert net.user_agent() == net.USER_AGENT
    assert net.user_agent("  ") == net.USER_AGENT
    assert net.user_agent("me@example.org").endswith("(local chess app; contact: me@example.org)")
    assert net.user_agent("me@example.org\r\nX-Evil: 1") == net.USER_AGENT  # never a new header


def test_one_dispatches(conn: sqlite3.Connection, server: Server) -> None:
    from datetime import date

    serve_sites(server)
    with server.client() as http:
        got = update.one(
            conn,
            http,
            "chesscom",
            progress=lambda *_: None,
            stop=lambda: False,
            wait=lambda s: None,
            today=date(2026, 11, 12),
            contact="me@example.org",
        )
        assert got.source == "chesscom"
        with pytest.raises(ValueError, match="Unknown source"):
            update.one(
                conn,
                http,
                "fics",
                progress=lambda *_: None,
                stop=lambda: False,
                wait=lambda s: None,
                today=date(2026, 11, 12),
            )
    assert "contact: me@example.org" in server.requests[0].headers["User-Agent"]
