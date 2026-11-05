"""The Re-test API (CLAUDE.md §7.8, §10) against a real temp database: the queue (and that it
never gives the answer away), attempts and their scheduling, and the hint."""

import json
from collections.abc import Iterator
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import chess
import pytest
from fastapi.testclient import TestClient
from test_api_blunders import NOW, URL, elephant, fen_entry, scholars, sql

from blunderbook.api.app import create_app
from blunderbook.db import connection, repo

TODAY = date.today()  # the routes use the local date too
LESSON = "Look for Bb4+ before grabbing the pawn."

# The only fields a queue item may carry. A new one is a conscious change: it must not
# hint at the answer.
ITEM_FIELDS = {
    "id",
    "fen",
    "my_color",
    "move_no",
    "legal_uci",
    "source",
    "site_label",
    "opponent",
    "played_on",
    "due_on",
}


@pytest.fixture
def ids(db_file: Path) -> dict[str, int]:
    """The Log tests' three entries, all due: the Elephant, Scholar's mate, a FEN entry."""
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


def queue(client: TestClient, query: str = "") -> dict[str, Any]:
    response = client.get("/api/retest/queue" + query)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def queued(client: TestClient, query: str = "") -> list[int]:
    return [item["id"] for item in queue(client, query)["items"]]


def attempt(client: TestClient, blunder_id: int, move: str | None, **extra: Any) -> Any:
    response = client.post(f"/api/retest/{blunder_id}/attempt", json={"move_uci": move, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def set_due(db_file: Path, blunder_id: int, day: date) -> None:
    sql(db_file, "UPDATE blunders SET due_on = ? WHERE id = ?", day.isoformat(), blunder_id)


def attempts(db_file: Path, blunder_id: int) -> list[Any]:
    with closing(connection.connect(db_file)) as conn:
        return repo.list_attempts(conn, blunder_id)


# ---------------------------------------------------------------- queue


def test_new_entries_are_due_and_ordered(client: TestClient, ids: dict[str, int]) -> None:
    # Same due date, so the most recent game comes first; the FEN entry has no date.
    assert queued(client) == [ids["scholars"], ids["elephant"], ids["fen"]]


def test_the_oldest_due_date_comes_first(
    client: TestClient, ids: dict[str, int], db_file: Path
) -> None:
    set_due(db_file, ids["fen"], TODAY - timedelta(days=2))
    set_due(db_file, ids["elephant"], TODAY - timedelta(days=1))
    assert queued(client) == [ids["fen"], ids["elephant"], ids["scholars"]]


def test_entries_due_later_wait(client: TestClient, ids: dict[str, int], db_file: Path) -> None:
    later = TODAY + timedelta(days=3)
    set_due(db_file, ids["elephant"], later)
    set_due(db_file, ids["fen"], TODAY + timedelta(days=9))
    body = queue(client)
    assert [item["id"] for item in body["items"]] == [ids["scholars"]]
    assert body["total"] == 3
    assert body["next_due_on"] == later.isoformat()


def test_practise_all_gives_every_entry(
    client: TestClient, ids: dict[str, int], db_file: Path
) -> None:
    set_due(db_file, ids["elephant"], TODAY + timedelta(days=3))
    assert queued(client, "?all=1") == [ids["scholars"], ids["fen"], ids["elephant"]]


def test_empty_queue(client: TestClient, db_file: Path) -> None:
    with closing(connection.open_db(db_file, create=True)):
        pass
    assert queue(client) == {"items": [], "total": 0, "next_due_on": None}


def test_an_item_has_the_position_and_its_legal_moves(
    client: TestClient, ids: dict[str, int]
) -> None:
    (item,) = [i for i in queue(client)["items"] if i["id"] == ids["elephant"]]
    assert item["fen"] == "r1bqkb1r/pppn1ppp/5n2/3p2B1/3P4/2N5/PP2PPPP/R2QKBNR w KQkq - 0 6"
    assert item["my_color"] == "white"
    assert item["move_no"] == 6
    assert item["opponent"] == "Karim S."
    assert item["site_label"] == "Lichess"
    assert item["played_on"] == "2026-10-12"
    board = chess.Board(item["fen"])
    assert sorted(item["legal_uci"]) == sorted(m.uci() for m in board.legal_moves)


def test_the_queue_never_gives_the_answer_away(
    client: TestClient, ids: dict[str, int], db_file: Path
) -> None:
    for blunder_id in ids.values():
        response = client.patch(
            f"/api/blunders/{blunder_id}",
            json={"lesson": LESSON, "thinking": "I thought the pawn was free."},
        )
        assert response.status_code == 200
    raw = client.get("/api/retest/queue?all=1").text
    items = json.loads(raw)["items"]
    assert len(items) == 3
    for item in items:
        assert set(item) == ITEM_FIELDS
    for secret in (
        "best",
        "accept",
        "played_uci",
        "played_san",
        "refutation",
        "lesson",
        "thinking",
        "judgment",
        "eval",
        "Nxd5",  # the move played in the game
        "6. e3",  # the best line
        "a line",  # the refutation
        LESSON,
        "pawn was free",
    ):
        assert secret not in raw, secret


# ---------------------------------------------------------------- attempts


def test_a_solve_is_recorded_and_rescheduled(
    client: TestClient, ids: dict[str, int], db_file: Path
) -> None:
    client.patch(f"/api/blunders/{ids['elephant']}", json={"lesson": LESSON})
    result = attempt(client, ids["elephant"], "e2e3")
    assert result == {
        "id": ids["elephant"],
        "solved": True,
        "move_uci": "e2e3",
        "move_san": "e3",
        "move_fen": "r1bqkb1r/pppn1ppp/5n2/3p2B1/3P4/2N1P3/PP3PPP/R2QKBNR b KQkq - 0 6",
        "best_uci": "e2e3",
        "best_san": "e3",
        "best_line_san": "6. e3",
        "played_uci": "c3d5",
        "played_san": "Nxd5",
        "refutation_san": "a line",
        "judgment": "blunder",
        "lesson": LESSON,
        "status": "solved",
        "streak": 1,
        "due_on": (TODAY + timedelta(days=1)).isoformat(),
        "next_in_days": 1,
    }
    (tried,) = attempts(db_file, ids["elephant"])
    assert (tried.move_uci, tried.solved, tried.used_hint) == ("e2e3", True, False)
    assert ids["elephant"] not in queued(client)


def test_a_streak_climbs_the_intervals(
    client: TestClient, ids: dict[str, int], db_file: Path
) -> None:
    sql(db_file, "UPDATE blunders SET streak = 2, status = 'solved' WHERE id = ?", ids["fen"])
    result = attempt(client, ids["fen"], "g2g3")
    assert (result["streak"], result["next_in_days"]) == (3, 7)


def test_the_game_move_is_a_miss(client: TestClient, ids: dict[str, int], db_file: Path) -> None:
    sql(db_file, "UPDATE blunders SET streak = 4, status = 'solved' WHERE id = ?", ids["elephant"])
    result = attempt(client, ids["elephant"], "c3d5")
    assert result["solved"] is False
    assert (result["move_uci"], result["move_san"]) == ("c3d5", "Nxd5")
    assert (result["status"], result["streak"], result["next_in_days"]) == ("missed", 0, 1)
    assert result["best_san"] == "e3"


def test_giving_up_is_a_miss(client: TestClient, ids: dict[str, int], db_file: Path) -> None:
    result = attempt(client, ids["scholars"], None)
    assert result["solved"] is False
    assert (result["move_uci"], result["move_san"], result["move_fen"]) == (None, None, None)
    assert result["status"] == "missed"
    (tried,) = attempts(db_file, ids["scholars"])
    assert tried.move_uci is None and tried.solved is False


def test_using_the_hint_is_recorded_but_doesnt_change_the_schedule(
    client: TestClient, ids: dict[str, int], db_file: Path
) -> None:
    result = attempt(client, ids["scholars"], "g7g6", used_hint=True)
    assert (result["solved"], result["streak"], result["next_in_days"]) == (True, 1, 1)
    (tried,) = attempts(db_file, ids["scholars"])
    assert tried.used_hint is True


def test_practising_early_reschedules_too(
    client: TestClient, ids: dict[str, int], db_file: Path
) -> None:
    set_due(db_file, ids["elephant"], TODAY + timedelta(days=20))
    result = attempt(client, ids["elephant"], "a2a3")
    assert result["status"] == "missed"
    assert result["due_on"] == (TODAY + timedelta(days=1)).isoformat()


@pytest.mark.parametrize("move", ["e2e5", "e7e5", "zz", "", "0000", "e2e3e4"])
def test_an_illegal_move_changes_nothing(
    client: TestClient, ids: dict[str, int], db_file: Path, move: str
) -> None:
    response = client.post(f"/api/retest/{ids['elephant']}/attempt", json={"move_uci": move})
    assert response.status_code == 422
    assert "isn't a legal move" in response.json()["detail"]
    assert attempts(db_file, ids["elephant"]) == []
    assert queue(client)["items"][1]["id"] == ids["elephant"]  # still due, unchanged


@pytest.mark.parametrize(
    "body",
    [{}, {"move_uci": "e2e3", "solved": True}, {"move_uci": 5}, {"move_uci": "e2e3", "x": 1}],
)
def test_a_bad_attempt_body_is_refused(
    client: TestClient, ids: dict[str, int], db_file: Path, body: Any
) -> None:
    response = client.post(f"/api/retest/{ids['elephant']}/attempt", json=body)
    assert response.status_code == 422
    assert attempts(db_file, ids["elephant"]) == []


def test_attempt_on_a_missing_entry(client: TestClient, ids: dict[str, int]) -> None:
    response = client.post("/api/retest/999/attempt", json={"move_uci": "e2e3"})
    assert response.status_code == 404
    assert response.json()["detail"] == "No entry #999."


def test_deleting_an_entry_deletes_its_attempts(
    client: TestClient, ids: dict[str, int], db_file: Path
) -> None:
    attempt(client, ids["elephant"], "e2e3")
    assert client.delete(f"/api/blunders/{ids['elephant']}").status_code == 204
    assert attempts(db_file, ids["elephant"]) == []


# ---------------------------------------------------------------- hint


def test_the_hint_is_only_the_from_square(client: TestClient, ids: dict[str, int]) -> None:
    response = client.get(f"/api/retest/{ids['elephant']}/hint")
    assert response.status_code == 200
    assert response.json() == {"from_square": "e2"}


def test_hint_for_a_missing_entry(client: TestClient, ids: dict[str, int]) -> None:
    assert client.get("/api/retest/999/hint").status_code == 404
