"""The Games tab's routes (CLAUDE.md §10): every game you imported, with its import and its
entries by judgment, and one game with its moves."""

from collections.abc import Iterator
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_api_blunders import NOW, URL, elephant, fen_entry, scholars

from blunderbook.api.app import create_app
from blunderbook.core.models import Batch
from blunderbook.db import connection, repo


@pytest.fixture
def ids(db_file: Path) -> dict[str, int]:
    """The Elephant trap (a loss, one blunder) and a clean win from blitz-week.pgn; Scholar's
    mate pasted; an older game with no import; a FEN entry. Game ids by name."""
    made: dict[str, int] = {}
    with closing(connection.open_db(db_file, create=True)) as conn:
        week = repo.add_import(conn, Batch("blitz-week.pgn", "file"), now=NOW)
        paste = repo.add_import(conn, Batch("Pasted PGN", "paste"), now=NOW)
        game, blunder = elephant()
        clean = replace(game, fingerprint="fp-clean", result="1-0", black="Ünal")
        older = replace(game, fingerprint="fp-older", played_on=None)
        sch_game, sch_blunder = scholars()
        fen_game, fen_blunder = fen_entry()
        for name, g, blunders, import_id, minutes in (
            ("elephant", game, [blunder], week, 0),
            ("clean", clean, [], week, 1),
            ("scholars", sch_game, [sch_blunder], paste, 2),
            ("older", older, [], None, -60 * 24 * 3),  # three days earlier
            ("fen", fen_game, [fen_blunder], None, 3),
        ):
            saved = repo.add_game(
                conn, g, blunders, now=NOW + timedelta(minutes=minutes), import_id=import_id
            )
            assert saved is not None
            made[name] = saved.game_id
    return made


@pytest.fixture
def client(db_file: Path) -> Iterator[TestClient]:
    with TestClient(create_app(db_file), base_url=URL) as test_client:
        yield test_client


def names(ids: dict[str, int], games: list[dict[str, Any]]) -> list[str]:
    by_id = {v: k for k, v in ids.items()}
    return [by_id[g["id"]] for g in games]


def test_the_list(client: TestClient, ids: dict[str, int]) -> None:
    games = client.get("/api/games").json()
    # Newest first: the older game has no date, so its import day (2 Nov) counts; the two
    # blitz-week games share 12 Oct, newest saved first. No FEN entry.
    assert names(ids, games) == ["older", "scholars", "clean", "elephant"]
    older, scholars_row, clean, elephant_row = games
    assert {k: elephant_row[k] for k in ("opponent", "result", "outcome", "my_color")} == {
        "opponent": "Karim S.",
        "result": "0-1",
        "outcome": "lost",
        "my_color": "white",
    }
    counts = (elephant_row["blunders"], elephant_row["mistakes"], elephant_row["inaccuracies"])
    assert counts == (1, 0, 0)
    assert elephant_row["batch"] == {
        "id": 1,
        "label": "blitz-week.pgn",
        "kind": "file",
        "started_at": "2026-11-05T09:30:00Z",
    }
    assert (clean["outcome"], clean["blunders"], clean["opponent"]) == ("won", 0, "Ünal")
    assert scholars_row["batch"]["label"] == "Pasted PGN"
    assert (scholars_row["my_color"], scholars_row["outcome"]) == ("black", "lost")
    assert older["batch"] is None
    assert older["imported_at"] == "2026-11-02T09:30:00Z"  # the page groups it by this day


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("result=won", ["clean"]),
        ("result=lost", ["older", "scholars", "elephant"]),
        ("result=drawn", []),
        ("blunders=clean", ["older", "clean"]),
        ("blunders=with", ["scholars", "elephant"]),
        ("source=chesscom", ["scholars"]),
        ("speed=blitz", ["older", "clean", "elephant"]),
        ("q=%C3%BCNAL", ["clean"]),  # "üNAL": ignores case beyond ASCII
        ("q=karim", ["older", "elephant"]),
        ("result=lost&blunders=clean", ["older"]),
    ],
)
def test_filters(client: TestClient, ids: dict[str, int], query: str, expected: list[str]) -> None:
    response = client.get(f"/api/games?{query}")
    assert response.status_code == 200, response.text
    assert names(ids, response.json()) == expected


@pytest.mark.parametrize(
    "query", ["result=win", "blunders=some", "speed=fast", "source=web", "q=" + "x" * 101]
)
def test_bad_filters(client: TestClient, ids: dict[str, int], query: str) -> None:
    assert client.get(f"/api/games?{query}").status_code == 422


def test_one_game(client: TestClient, ids: dict[str, int]) -> None:
    response = client.get(f"/api/games/{ids['elephant']}")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["outcome"] == "lost"
    assert data["batch"]["label"] == "blitz-week.pgn"
    assert data["imported_at"] == "2026-11-05T09:30:00Z"
    game = data["game"]
    assert game["id"] == ids["elephant"] and game["opponent"] == "Karim S."
    assert [m["san"] for m in game["moves"]][:5] == ["d4", "d5", "c4", "e6", "Nc3"]
    assert game["moves"][10]["san"] == "Nxd5"
    (entry,) = data["entries"]
    assert {k: entry[k] for k in ("ply", "move_no", "played_san", "judgment", "status")} == {
        "ply": 10,
        "move_no": 6,
        "played_san": "Nxd5",
        "judgment": "blunder",
        "status": "new",
    }


def test_a_clean_game(client: TestClient, ids: dict[str, int]) -> None:
    data = client.get(f"/api/games/{ids['clean']}").json()
    assert data["entries"] == [] and data["outcome"] == "won"
    same_moves = client.get(f"/api/games/{ids['elephant']}").json()["game"]["moves"]
    assert data["game"]["moves"] == same_moves


def test_an_older_game_has_no_import(client: TestClient, ids: dict[str, int]) -> None:
    assert client.get(f"/api/games/{ids['older']}").json()["batch"] is None


@pytest.mark.parametrize("which", ["fen", "missing"])
def test_no_such_game(client: TestClient, ids: dict[str, int], which: str) -> None:
    game_id = ids["fen"] if which == "fen" else 999
    response = client.get(f"/api/games/{game_id}")
    assert (response.status_code, response.json()) == (404, {"detail": f"No game #{game_id}."})


def test_no_games_yet(client: TestClient, db_file: Path) -> None:
    with closing(connection.open_db(db_file, create=True)):
        pass
    assert client.get("/api/games").json() == []


def test_the_log_detail_still_has_its_game(client: TestClient, ids: dict[str, int]) -> None:
    """The entry detail now builds its game with the same code as the game page."""
    (item,) = [i for i in client.get("/api/blunders").json() if i["played_san"] == "Nxd5"]
    entry = client.get(f"/api/blunders/{item['id']}").json()
    page = client.get(f"/api/games/{ids['elephant']}").json()
    assert entry["game"] == page["game"]
