"""The Patterns API (CLAUDE.md §7.9, §10) against a real temp database."""

import dataclasses
from collections.abc import Iterator
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_api_blunders import NOW, URL, elephant, fen_entry, scholars, sql

from blunderbook.api.app import create_app
from blunderbook.api.schemas import PatternsOut
from blunderbook.core import patterns
from blunderbook.db import connection, repo


@pytest.fixture
def ids(db_file: Path) -> dict[str, int]:
    made: dict[str, int] = {}
    with closing(connection.open_db(db_file, create=True)) as conn:
        for minutes, (name, make) in enumerate(
            (("elephant", elephant), ("scholars", scholars), ("fen", fen_entry))
        ):
            game, blunder = make()
            saved = repo.add_game(conn, game, [blunder], now=NOW + timedelta(minutes=minutes))
            assert saved is not None
            made[name] = saved.blunder_ids[0]
    return made


@pytest.fixture
def client(db_file: Path) -> Iterator[TestClient]:
    with TestClient(create_app(db_file), base_url=URL) as test_client:
        yield test_client


def test_patterns_of_an_empty_database(client: TestClient, db_file: Path) -> None:
    with closing(connection.open_db(db_file, create=True)):
        pass
    body = client.get("/api/patterns").json()
    assert body["total"] == 0
    assert body["solved_pct"] is None
    assert body["causes"] == [] and body["history"] == [] and body["biggest_leak"] is None


def test_patterns_of_three_entries(client: TestClient, ids: dict[str, int], db_file: Path) -> None:
    # Confirm one cause on the Elephant; Scholar's mate and the FEN entry keep their suggestions.
    client.patch(f"/api/blunders/{ids['elephant']}", json={"causes": ["Miscalculated a line"]})
    tries = [("scholars", "g7g6", True), ("fen", None, False), ("fen", "g2g3", True)]
    for name, move, solved in tries:
        result = client.post(f"/api/retest/{ids[name]}/attempt", json={"move_uci": move}).json()
        assert result["solved"] is solved
    sql(
        db_file,
        "UPDATE blunders SET time_spent_s = 2, clock_left_s = 12 WHERE id = ?",
        ids["scholars"],
    )

    response = client.get("/api/patterns")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 3
    assert body["by_source"] == [
        {"source": "lichess", "count": 1},
        {"source": "chesscom", "count": 1},
        {"source": "fen", "count": 1},
    ]
    assert body["due"] == 1  # only the Elephant: the other two were re-tested
    assert body["retests_done"] == 3
    assert (body["retested"], body["solved"], body["solved_pct"]) == (2, 2, 100)
    assert (body["timed"], body["fast"], body["with_clock"], body["low_clock"]) == (1, 1, 1, 1)
    assert body["causes"] == [
        {"cause": "Missed their threat", "confirmed": 0, "suggested": 2},
        {"cause": "Miscalculated a line", "confirmed": 1, "suggested": 0},
        {"cause": "Moved too fast", "confirmed": 0, "suggested": 1},
    ]
    assert body["biggest_leak"] == "Missed their threat"
    assert body["by_speed"] == [{"speed": "blitz", "count": 1}, {"speed": None, "count": 2}]

    first, second = body["history"]
    assert first["id"] == ids["fen"]  # re-tested last
    assert (first["attempts"], first["status"], first["played_san"]) == (2, "solved", "Rc7")
    assert (second["id"], second["attempts"], second["opponent"]) == (
        ids["scholars"],
        1,
        "quickmate77",
    )
    assert second["due_on"] == (date.today() + timedelta(days=1)).isoformat()


def test_the_schema_matches_the_core() -> None:
    fields = {f.name for f in dataclasses.fields(patterns.Patterns)}
    assert fields == set(PatternsOut.model_fields)
