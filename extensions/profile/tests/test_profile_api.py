"""The Profile tab's routes and page (ROADMAP 17.3): what's kept, your rating from your games,
and the "Refresh ratings" button, with the sites faked at ``host.fetch_ratings``."""

import re
from collections.abc import Iterator
from contextlib import closing
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from blunderbook_profile import extension, routes, store
from fastapi.testclient import TestClient
from profile_fakes import (  # noqa: F401  (fixtures)
    CHESSCOM,
    LICHESS,
    Sites,
    cfg_file,
    fill_log,
    new_game,
    save_config,
    sites,
)

from blunderbook import config, ext, host, webcheck
from blunderbook.api.app import create_app
from blunderbook.core.models import Rating
from blunderbook.db import connection

URL = "http://127.0.0.1"
API = "/api/ext/profile"


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


def get(client: TestClient) -> Any:
    response = client.get(API)
    assert response.status_code == 200, response.text
    return response.json()


def press(client: TestClient, site: str | None = None) -> Any:
    response = client.post(API + "/refresh", json={} if site is None else {"site": site})
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------- what's kept


def test_before_any_refresh(client: TestClient, sites: Sites) -> None:
    assert get(client) == {
        "sites": [
            {
                "source": "lichess",
                "title": "Lichess",
                "username": "rashed",
                "fetched": None,
                "from_games": [],
                "problem": None,
            },
            {
                "source": "chesscom",
                "title": "Chess.com",
                "username": "rashed_blitz",
                "fetched": None,
                "from_games": [],
                "problem": None,
            },
        ],
        "warnings": [],
    }
    assert sites.asked == []  # opening the tab asks no site


def test_no_usernames(client: TestClient, cfg_file: Path) -> None:
    save_config(cfg_file, lichess="", chesscom="")
    assert [s["username"] for s in get(client)["sites"]] == ["", ""]


def test_your_rating_from_your_games(client: TestClient) -> None:
    fill_log(
        new_game(1, "lichess", "blitz", date(2026, 11, 1), 1640),
        new_game(2, "lichess", "blitz", date(2026, 11, 9), 1647, me="black"),
        new_game(3, "lichess", "bullet", date(2026, 10, 2), 1512),
        new_game(4, "chesscom", "rapid", date(2026, 10, 7), 1655),
        new_game(5, "otb", "classical", date(2026, 11, 10), 1800),
    )
    lichess, chesscom = get(client)["sites"]
    assert lichess["from_games"] == [
        {
            "speed": "bullet",
            "label": "Bullet",
            "rating": 1512,
            "played_on": "2026-10-02",
            "game_id": 3,
        },
        {
            "speed": "blitz",
            "label": "Blitz",
            "rating": 1647,
            "played_on": "2026-11-09",
            "game_id": 2,
        },
    ]
    assert [(g["speed"], g["rating"]) for g in chesscom["from_games"]] == [("rapid", 1655)]


# ---------------------------------------------------------------- Refresh ratings


def test_refresh_asks_both_sites_and_keeps_the_answers(client: TestClient, sites: Sites) -> None:
    answer = press(client)
    assert sites.asked == ["lichess", "chesscom"]
    assert answer == get(client)  # what it says is what's kept
    lichess, chesscom = answer["sites"]
    assert lichess["problem"] is None and chesscom["problem"] is None
    fetched = lichess["fetched"]
    assert fetched["username"] == "Rashed"  # as Lichess spells it
    assert fetched["since"] is None
    assert datetime.fromisoformat(fetched["fetched_at"]).tzinfo is not None
    assert fetched["ratings"] == [
        {
            "kind": "blitz",
            "label": "Blitz",
            "rating": 1647,
            "provisional": False,
            "change": None,
            "games": 812,
            "best": 1712,
            "best_at": "2026-08-14T18:22:00Z",
            "wins": 401,
            "losses": 392,
            "draws": 47,
        },
        {
            "kind": "classical",
            "label": "Classical",
            "rating": 1702,
            "provisional": True,
            "change": None,
            "games": 3,
            "best": None,
            "best_at": None,
            "wins": None,
            "losses": None,
            "draws": None,
        },
        {
            "kind": "daily",
            "label": "Correspondence",
            "rating": 1611,
            "provisional": False,
            "change": None,
            "games": 9,
            "best": None,
            "best_at": None,
            "wins": None,
            "losses": None,
            "draws": None,
        },
        {
            "kind": "puzzle",
            "label": "Puzzles",
            "rating": 1985,
            "provisional": False,
            "change": None,
            "games": 2104,
            "best": None,
            "best_at": None,
            "wins": None,
            "losses": None,
            "draws": None,
        },
    ]
    puzzles = chesscom["fetched"]["ratings"][-1]
    assert (puzzles["label"], puzzles["rating"], puzzles["best"]) == ("Puzzles", None, 2104)


def test_refresh_one_site(client: TestClient, sites: Sites) -> None:
    lichess, chesscom = press(client, "chesscom")["sites"]
    assert sites.asked == ["chesscom"]
    assert lichess["fetched"] is None and chesscom["fetched"] is not None


def test_the_change_since_the_fetch_before(client: TestClient, sites: Sites) -> None:
    with closing(host.open_db(extension)) as conn:
        earlier = store.save(conn, LICHESS, at=datetime.now(UTC) - timedelta(days=7))
    sites.answers["lichess"] = replace(
        LICHESS,
        ratings=(
            Rating(kind="bullet", rating=1500, games=1),
            Rating(kind="blitz", rating=1659, games=830),
            Rating(kind="classical", rating=1702, games=3),
            Rating(kind="puzzle", rating=1970, games=2150),
        ),
    )
    fetched = press(client, "lichess")["sites"][0]["fetched"]
    assert fetched["since"] == earlier.day.isoformat()
    assert {r["kind"]: r["change"] for r in fetched["ratings"]} == {
        "bullet": None,
        "blitz": 12,
        "classical": 0,
        "puzzle": -15,
    }


def test_one_site_failing_keeps_what_you_had(client: TestClient, sites: Sites) -> None:
    press(client)
    sites.answers["lichess"] = "Lichess is limiting requests right now (HTTP 429). Try again."
    lichess, chesscom = press(client)["sites"]
    assert lichess["problem"] == "Lichess is limiting requests right now (HTTP 429). Try again."
    assert lichess["fetched"]["ratings"][0]["rating"] == 1647  # the ratings you had
    assert chesscom["problem"] is None and chesscom["fetched"] is not None
    assert get(client)["sites"][0]["problem"] is None  # a problem isn't kept


def test_a_site_with_no_username_is_skipped(
    client: TestClient, sites: Sites, cfg_file: Path
) -> None:
    save_config(cfg_file, chesscom="")
    press(client)
    assert sites.asked == ["lichess"]
    refused = client.post(API + "/refresh", json={"site": "chesscom"})
    assert refused.status_code == 409
    assert refused.json()["detail"] == (
        "Set your Chess.com username under [chesscom] in config.toml."
    )


def test_refresh_with_no_usernames(client: TestClient, sites: Sites, cfg_file: Path) -> None:
    save_config(cfg_file, lichess="", chesscom="")
    refused = client.post(API + "/refresh", json={})
    assert refused.status_code == 409
    assert refused.json()["detail"].startswith("No usernames yet: set yours under [lichess]")
    assert sites.asked == []


def test_refresh_from_another_site_is_refused(client: TestClient, sites: Sites) -> None:
    refused = client.post(API + "/refresh", json={}, headers={"Origin": "https://evil.example"})
    assert refused.status_code == 403
    assert sites.asked == []


def test_refresh_bad_body(client: TestClient, sites: Sites) -> None:
    assert client.post(API + "/refresh", json={"site": "fide"}).status_code == 422
    assert sites.asked == []


def test_one_refresh_at_a_time(client: TestClient, sites: Sites) -> None:
    assert routes._refreshing.acquire(blocking=False)
    try:
        refused = client.post(API + "/refresh", json={})
    finally:
        routes._refreshing.release()
    assert refused.status_code == 409
    assert refused.json()["detail"] == "Your ratings are being fetched already."
    assert sites.asked == []
    press(client)  # and it's free again


def test_refresh_takes_the_daily_backup(client: TestClient, sites: Sites, cfg_file: Path) -> None:
    with closing(connection.open_db(config.db_path())) as conn:
        conn.execute(
            "INSERT INTO imports (label, kind, started_at) VALUES ('x', 'file', '2026-01-01')"
        )
    assert press(client)["warnings"] == []
    folder = config.backup_folder(config.load(cfg_file))
    assert any(p.name.startswith("blunderbook-") for p in folder.iterdir())


def test_a_broken_config_is_a_503(client: TestClient, sites: Sites, cfg_file: Path) -> None:
    cfg_file.write_text("engine_depth = 'deep'\n")
    assert client.get(API).status_code == 503
    assert client.post(API + "/refresh", json={}).status_code == 503
    assert sites.asked == []


# ---------------------------------------------------------------- the page


def test_the_tab(client: TestClient) -> None:
    assert client.get("/api/extensions").json() == [
        {"name": "profile", "title": "Profile", "css": True}
    ]
    page = client.get("/ext/profile/view.js")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/javascript")


def test_the_page_passes_the_checks(tmp_path: Path) -> None:
    folder = ext.web_folder(extension)
    assert folder is not None
    app = create_app(tmp_path / "blunderbook.db", [extension])
    assert webcheck.problems(folder, app, prefix="profile") == []


def test_only_the_refresh_changes_anything() -> None:
    """Every route is a GET but the Refresh button, which only the page may call (§10)."""
    changes = [
        (r.path, r.dependencies)  # type: ignore[attr-defined]
        for r in routes.router.routes
        if getattr(r, "methods", set()) - {"GET"}
    ]
    assert [path for path, _ in changes] == ["/refresh"]
    assert [d.dependency for d in changes[0][1]] == [host.same_origin]


def test_the_page_reads_only_what_the_api_sends() -> None:
    """Every field view.js reads off the answer, a site, a fetch, a rating or a game is in
    that part's schema. In view.js those are always called data, s, f, r and g."""
    folder = ext.web_folder(extension)
    assert folder is not None
    text = (folder / "view.js").read_text("utf-8")
    parts = {
        "data": routes.ProfileOut,
        "s": routes.SiteOut,
        "f": routes.FetchOut,
        "r": routes.RatingOut,
        "g": routes.GameRatingOut,
    }
    for name, model in parts.items():
        read = set(re.findall(rf"\b{name}\.([a-z_]+)\b", text))
        assert read, name
        assert read <= set(model.model_fields), (name, read - set(model.model_fields))
