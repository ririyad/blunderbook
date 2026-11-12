"""The Rankings tab's routes and page (ROADMAP 16.3): the status, each source's list, and the
Update button's background job, against a fake server."""

import time
from collections.abc import Iterator
from contextlib import closing
from datetime import date
from pathlib import Path

import pytest
from blunderbook_rankings import extension, fide, jobs, routes, store, update
from fastapi.testclient import TestClient
from rankings_fakes import (  # noqa: F401  (fixtures)
    Server,
    cfg_file,
    month_zip,
    ok,
    player,
    serve_fide,
    serve_sites,
    server,
    status,
)

from blunderbook import config, ext, host, webcheck
from blunderbook.api.app import create_app
from blunderbook.db import connection

URL = "http://127.0.0.1"
API = "/api/ext/rankings"

OCT = [
    player(1, 2800, name="Alpha, A", fed="NOR", title="GM"),
    player(2, 2790, name="Bravo, B", fed="USA", title="GM"),
    player(3, 2700, name="Charlie, C", fed="NOR"),
    player(5, 2400, name="Echo, E", fed="NOR", sex="F", born="2010"),
]
NOV = [
    player(2, 2810, name="Bravo, B", fed="USA", title="GM"),
    player(1, 2800, name="Alpha, A", fed="NOR", title="GM"),
    player(4, 2750, name="Delta, D", fed="IND", born="2008"),
    player(3, 2690, name="Charlie, C", fed="NOR"),
    player(5, 2420, name="Echo, E", fed="NOR", sex="F", born="2010"),
]


@pytest.fixture(autouse=True)
def today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routes, "_today", lambda: date(2026, 11, 12))


@pytest.fixture
def db_file(cfg_file: Path) -> Path:
    path = config.db_path()
    with closing(connection.open_db(path, create=True)):
        pass
    with closing(host.open_db(extension)):
        pass
    return path


@pytest.fixture
def client(db_file: Path) -> Iterator[TestClient]:
    with TestClient(create_app(db_file, [extension]), base_url=URL) as c:
        yield c


def seed(server: Server) -> None:
    """October's FIDE lists, then November's in their place, and both sites' boards."""
    with closing(host.open_db(extension)) as conn, server.client() as http:
        for i, (month, players) in enumerate((("oct26", OCT), ("nov26", NOV))):
            for speed in fide.SPEEDS:
                server.on(fide.url(speed), ok(month_zip(speed, month, *players), etag=f'"{i}"'))
            update.update_fide(
                conn, http, progress=lambda *_: None, stop=lambda: False, wait=lambda s: None,
                today=date(2026, 11, 12),
            )  # fmt: skip
        serve_sites(server)
        for name in ("lichess", "chesscom"):
            update.one(
                conn, http, name, progress=lambda *_: None, stop=lambda: False,
                wait=lambda s: None, today=date(2026, 11, 12),
            )  # fmt: skip


def get(client: TestClient, path: str, **params: str) -> dict:  # type: ignore[type-arg]
    got = client.get(API + path, params=params)
    assert got.status_code == 200, got.text
    return got.json()  # type: ignore[no-any-return]


# ---------------------------------------------------------------- status


def test_status_before_any_update(client: TestClient) -> None:
    got = get(client, "/status")
    assert got["job_id"] is None
    assert [s["source"] for s in got["sources"]] == ["fide", "lichess", "chesscom"]
    fide_row = got["sources"][0]
    assert fide_row == {
        "source": "fide",
        "title": "FIDE",
        "list_label": None,
        "fetched_at": None,
        "checked_at": None,
        "last_error": None,
        "stale": False,
        "size": "about 35 MB",
        "about_url": "https://ratings.fide.com/",
    }


def test_status_after_updates(client: TestClient, server: Server) -> None:
    seed(server)
    got = get(client, "/status")
    fide_row, lichess_row, chesscom_row = got["sources"]
    assert fide_row["list_label"] == "November 2026" and not fide_row["stale"]
    assert lichess_row["fetched_at"] is not None and chesscom_row["fetched_at"] is not None


def test_status_stale(client: TestClient, server: Server, monkeypatch: pytest.MonkeyPatch) -> None:
    seed(server)
    monkeypatch.setattr(routes, "_today", lambda: date(2026, 12, 2))
    assert get(client, "/status")["sources"][0]["stale"] is True


# ---------------------------------------------------------------- FIDE


def test_fide_before_any_update(client: TestClient) -> None:
    got = get(client, "/fide")
    assert (got["month"], got["players"], got["federations"]) == (None, [], [])
    assert [o["key"] for o in got["speeds"]] == ["standard", "rapid", "blitz"]
    assert [o["key"] for o in got["lists"]] == ["open", "women", "juniors", "girls"]


def test_fide_world(client: TestClient, server: Server) -> None:
    seed(server)
    got = get(client, "/fide", speed="blitz")
    assert (got["month"], got["month_label"]) == ("2026-11", "November 2026")
    assert (got["speed"], got["category"], got["fed"]) == ("blitz", "open", None)
    assert got["federations"] == ["IND", "NOR", "USA"]
    rows = [(p["rank"], p["name"], p["rating"]) for p in got["players"]]
    assert rows == [  # November's only: October's list is gone
        (1, "Bravo, B", 2810),
        (2, "Alpha, A", 2800),
        (3, "Delta, D", 2750),
        (4, "Charlie, C", 2690),
        (5, "Echo, E", 2420),
    ]
    assert set(got["players"][0]) == {
        "rank", "fide_id", "name", "title", "fed", "rating", "games", "born", "url",
    }  # fmt: skip
    first = got["players"][0]
    assert first["url"] == "https://ratings.fide.com/profile/2"
    assert (first["title"], first["fed"], first["born"], first["games"]) == ("GM", "USA", 1990, 9)


def test_fide_federation_and_lists(client: TestClient, server: Server) -> None:
    seed(server)

    def names(**params: str) -> list[str]:
        return [p["name"] for p in get(client, "/fide", **params)["players"]]

    assert names(fed="NOR") == ["Alpha, A", "Charlie, C", "Echo, E"]
    assert names(list="women") == ["Echo, E"]
    assert names(list="juniors") == ["Delta, D", "Echo, E"]
    assert names(list="girls", fed="NOR") == ["Echo, E"]
    assert names(fed="BAN") == []
    assert [p["rank"] for p in get(client, "/fide", fed="NOR")["players"]] == [1, 2, 3]


@pytest.mark.parametrize(
    "params",
    [{"speed": "bullet"}, {"list": "seniors"}, {"fed": "nor"}, {"fed": "NORW"}],
)
def test_fide_bad_filters(client: TestClient, params: dict[str, str]) -> None:
    assert client.get(API + "/fide", params=params).status_code == 422


# ---------------------------------------------------------------- Lichess and Chess.com


def test_boards_before_any_update(client: TestClient) -> None:
    got = get(client, "/lichess")
    assert (got["source"], got["board"], got["fetched_at"], got["players"]) == (
        "lichess",
        "blitz",
        None,
        [],
    )
    assert [o["key"] for o in got["boards"]] == list(update.lichess.BOARDS)


def test_boards(client: TestClient, server: Server) -> None:
    seed(server)
    got = get(client, "/lichess", board="bullet")
    assert got["players"] == [
        {
            "rank": 1,
            "username": "DrNykterstein",
            "title": "GM",
            "rating": 3200,
            "progress": 12,
            "url": "https://lichess.org/@/DrNykterstein",
        }
    ]
    got = get(client, "/chesscom")
    assert got["board"] == "live_blitz"
    assert [(p["username"], p["url"]) for p in got["players"]] == [
        ("Hikaru", "https://www.chess.com/member/Hikaru"),
        ("MagnusCarlsen", "https://www.chess.com/member/MagnusCarlsen"),
    ]


@pytest.mark.parametrize(
    ("path", "board"), [("/lichess", "correspondence"), ("/chesscom", "tactics")]
)
def test_bad_boards(client: TestClient, path: str, board: str) -> None:
    assert client.get(API + path, params={"board": board}).status_code == 422


# ---------------------------------------------------------------- the Update button


def wait_for(client: TestClient, job_id: str) -> dict:  # type: ignore[type-arg]
    for _ in range(200):
        got = get(client, f"/update/{job_id}")
        if got["status"] != "running":
            return got
        time.sleep(0.02)
    raise AssertionError("the update didn't finish")


def test_update_button(client: TestClient, server: Server) -> None:
    serve_fide(server)
    serve_sites(server)
    started = client.post(API + "/update", json={"source": "all"})
    assert started.status_code == 202, started.text
    job = wait_for(client, started.json()["job_id"])
    assert job["status"] == "done" and job["percent"] == 100 and job["error"] is None
    assert [(o["source"], o["changed"], o["message"]) for o in job["outcomes"]] == [
        ("fide", True, "FIDE November 2026: standard, rapid and blitz lists updated."),
        ("lichess", True, "Lichess: 5 leaderboards updated."),
        ("chesscom", True, "Chess.com: 4 leaderboards updated."),
    ]
    assert get(client, "/fide")["month"] == "2026-11"
    assert get(client, "/status")["job_id"] is None


def test_update_one_source(client: TestClient, server: Server) -> None:
    serve_sites(server)
    job = wait_for(
        client, client.post(API + "/update", json={"source": "chesscom"}).json()["job_id"]
    )
    assert [o["source"] for o in job["outcomes"]] == ["chesscom"]
    assert {r.url.host for r in server.requests} == {"api.chess.com"}


def test_update_failure(client: TestClient, server: Server) -> None:
    server.on(fide.url("standard"), status(502))
    job = wait_for(client, client.post(API + "/update", json={"source": "fide"}).json()["job_id"])
    assert job["status"] == "done"
    outcome = job["outcomes"][0]
    assert outcome["error"] == f"ratings.fide.com answered HTTP 502 for {fide.url('standard')}."
    assert get(client, "/status")["sources"][0]["last_error"] == outcome["error"]


def test_update_from_another_site_is_refused(client: TestClient, server: Server) -> None:
    got = client.post(
        API + "/update", json={"source": "all"}, headers={"Origin": "https://evil.example"}
    )
    assert got.status_code == 403
    assert server.requests == []


@pytest.mark.parametrize("body", [{"source": "fics"}, {}, {"source": "all", "force": True}])
def test_update_bad_body(client: TestClient, body: dict[str, object]) -> None:
    assert client.post(API + "/update", json=body).status_code == 422


def test_one_update_at_a_time(client: TestClient, server: Server) -> None:
    serve_sites(server)
    jobs_ = client.app.state.rankings_jobs  # type: ignore[attr-defined]
    held = jobs.Job("held", ("lichess",))
    jobs_._latest = held
    got = client.post(API + "/update", json={"source": "lichess"})
    assert got.status_code == 409
    assert got.json()["detail"] == "An update is already running. Wait for it to finish."
    assert get(client, "/status")["job_id"] == "held"
    held.finish("done")
    assert client.post(API + "/update", json={"source": "lichess"}).status_code == 202


def test_unknown_job(client: TestClient) -> None:
    got = client.get(API + "/update/nope")
    assert got.status_code == 404
    assert "restarted" in got.json()["detail"]


def test_stop_keeps_the_lists(cfg_file: Path, server: Server) -> None:
    """Stopping serve stops the update: the source being updated isn't changed."""
    serve_fide(server)
    runner = jobs.Jobs(lambda: host.open_db(extension))
    runner._stop.set()  # stopped before its first step
    job = runner.start("fide")
    runner.stop()
    view = job.view()
    assert view.status == "stopped"
    assert view.error == "Stopped. The FIDE lists weren't changed."
    with closing(host.open_db(extension)) as conn:
        assert store.source(conn, "fide") is None


def test_job_progress() -> None:
    job = jobs.Job("x", ("fide", "lichess"))
    job.step(1)("Downloading Lichess's Blitz leaderboard", 0.5)
    view = job.view()
    assert (view.percent, view.label) == (75, "Downloading Lichess's Blitz leaderboard")
    job.finish("done")
    assert job.view().percent == 100


# ---------------------------------------------------------------- the page


def test_the_tab(client: TestClient) -> None:
    assert client.get("/api/extensions").json() == [
        {"name": "rankings", "title": "Rankings", "css": True}
    ]
    page = client.get("/ext/rankings/view.js")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/javascript")


def test_the_page_passes_the_checks(tmp_path: Path) -> None:
    folder = ext.web_folder(extension)
    assert folder is not None
    app = create_app(tmp_path / "blunderbook.db", [extension])
    assert webcheck.problems(folder, app, prefix="rankings") == []


def test_only_the_update_changes_anything() -> None:
    """Every route is a GET but the Update button, which only the page may call (§10)."""
    changes = [
        (r.path, r.dependencies)  # type: ignore[attr-defined]
        for r in routes.router.routes
        if getattr(r, "methods", set()) - {"GET"}
    ]
    assert [path for path, _ in changes] == ["/update"]
    assert [d.dependency for d in changes[0][1]] == [host.same_origin]


def test_net_is_never_reached_by_a_get(client: TestClient, server: Server) -> None:
    for path in ("/status", "/fide", "/lichess", "/chesscom"):
        get(client, path)
    assert server.requests == []
