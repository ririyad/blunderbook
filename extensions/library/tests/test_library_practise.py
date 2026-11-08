"""Library practise (ROADMAP 11.3): the queue, attempts and hints, scheduled by core's Re-test
rules (CLAUDE.md §7.8) and kept in library.db. The queue never gives an answer away."""

import sqlite3
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

import pytest
from blunderbook_library import content, extension, progress, routes
from fastapi.testclient import TestClient
from test_library_api import client, db_file  # noqa: F401  (fixtures)
from typer.testing import CliRunner

from blunderbook import cli, ext

API = "/api/ext/library/practise"
DAY = date(2026, 11, 8)
ITEM_FIELDS = {
    "entry_id", "n", "name", "kind", "side", "fen", "prompt", "last_move", "legal_uci",
    "status", "due_on",
}  # fmt: skip


@pytest.fixture(autouse=True)
def on_day(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routes, "today", lambda: DAY)


def set_day(monkeypatch: pytest.MonkeyPatch, day: date) -> None:
    monkeypatch.setattr(routes, "today", lambda: day)


def positions() -> int:
    return sum(len(e.practise) for e in content.load().entries)


def tries(db_file: Path, entry_id: str) -> list[sqlite3.Row]:  # noqa: F811
    entry = routes.entries()[entry_id]
    with closing(sqlite3.connect(ext.db_path(extension, db_file))) as conn:
        conn.row_factory = sqlite3.Row
        return progress.attempts(conn, (entry_id, entry.practise[0].fen))


def attempt(client: TestClient, entry_id: str, move: str | None, **more: object) -> dict:  # noqa: F811
    got = client.post(f"{API}/{entry_id}/1/attempt", json={"move_uci": move, **more})
    assert got.status_code == 200, got.text
    return got.json()


# ---------------------------------------------------------------- the queue


def test_every_position_is_new_and_due_at_first(client: TestClient) -> None:  # noqa: F811
    got = client.get(API).json()
    assert len(got["items"]) == got["total"] == positions()
    assert got["next_due_on"] is None
    first = got["items"][0]
    assert first["entry_id"] == "caro-kann-defence"  # the Library's order
    assert (first["status"], first["due_on"]) == ("new", DAY.isoformat())


def test_the_queue_never_gives_the_answer_away(client: TestClient) -> None:  # noqa: F811
    """No answers, no replies and no idea (it explains the answer), as core's Re-test."""
    got = client.get(API, params={"all": 1})
    for item in got.json()["items"]:
        assert set(item) == ITEM_FIELDS
    for entry in content.load().entries:
        assert entry.idea not in got.text
        for n in entry.next:
            assert n.says not in got.text


def test_an_item_shows_the_position_and_the_move_before_it(client: TestClient) -> None:  # noqa: F811
    items = client.get(API, params={"entry": "legal-trap"}).json()["items"]
    (legal,) = items
    entry = routes.entries()["legal-trap"]
    assert legal["fen"] == entry.practise[0].fen
    assert legal["side"] == "black"
    assert legal["last_move"] == "5. Nxe5"
    assert "d6e5" in legal["legal_uci"] and "g4d1" in legal["legal_uci"]
    (tactic,) = client.get(API, params={"entry": "back-rank-mate"}).json()["items"]
    assert tactic["last_move"] is None  # it starts from its own position


def test_a_solved_position_waits_and_the_entry_shows_it(client: TestClient) -> None:  # noqa: F811
    attempt(client, "legal-trap", "d6e5")
    due = client.get(API).json()
    assert "legal-trap" not in [i["entry_id"] for i in due["items"]]
    assert (len(due["items"]), due["total"]) == (positions() - 1, positions())
    assert due["next_due_on"] == (DAY + timedelta(days=1)).isoformat()
    # Still there to practise on purpose: the entry's positions and "all".
    (item,) = client.get(API, params={"entry": "legal-trap"}).json()["items"]
    assert (item["status"], item["due_on"]) == ("solved", "2026-11-09")
    assert len(client.get(API, params={"all": 1}).json()["items"]) == positions()
    counts = client.get("/api/ext/library/entries/legal-trap").json()["practise"]
    assert counts == {"positions": 1, "tried": 1, "solved": 1, "due": 0}


def test_due_positions_come_first(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    attempt(client, "legal-trap", "g4d1")  # missed: due tomorrow
    set_day(monkeypatch, DAY + timedelta(days=3))
    items = client.get(API).json()["items"]
    assert items[0]["entry_id"] == "legal-trap"  # due since the 9th, before the new ones
    assert items[0]["status"] == "missed"


def test_unknown_entry_in_the_queue_is_a_404(client: TestClient) -> None:  # noqa: F811
    got = client.get(API, params={"entry": "nope"})
    assert got.status_code == 404


# ---------------------------------------------------------------- attempts


def test_a_sound_reply_solves_it(client: TestClient, db_file: Path) -> None:  # noqa: F811
    got = attempt(client, "legal-trap", "d6e5")
    assert got["solved"] is True
    assert (got["move_san"], got["answer_san"], got["answers"]) == ("dxe5", "dxe5", ["dxe5"])
    assert got["move_fen"].startswith("rn1qkbnr/ppp2p1p/6p1/4p3/2B1P1b1/2N5/PPPP1PPP/R1BQK2R w")
    assert got["your_reply"] == {
        "move": "5... dxe5",
        "line": "6. Qxg4",
        "says": "Takes the knight. White wins the bishop back and is a pawn up, "
        "but the game goes on.",
        "loses": False,
    }
    assert got["answer_reply"] is None  # the same move
    assert got["idea"].startswith("Your bishop on g4 pins")
    assert (got["status"], got["streak"], got["due_on"], got["next_in_days"]) == (
        "solved", 1, "2026-11-09", 1,
    )  # fmt: skip
    (tried,) = tries(db_file, "legal-trap")
    assert (tried["move_uci"], tried["solved"], tried["used_hint"]) == ("d6e5", 1, 0)


def test_falling_into_the_trap(client: TestClient) -> None:  # noqa: F811
    got = attempt(client, "legal-trap", "g4d1")
    assert got["solved"] is False
    assert got["your_reply"]["move"] == "5... Bxd1"
    assert got["your_reply"]["line"] == "6. Bxf7+ Ke7 7. Nd5#"
    assert got["your_reply"]["loses"] is True
    assert got["answer_reply"]["move"] == "5... dxe5"
    assert (got["status"], got["streak"], got["next_in_days"]) == ("missed", 0, 1)


def test_another_right_answer(client: TestClient) -> None:  # noqa: F811
    got = attempt(client, "scholars-mate", "d8e7")
    assert got["solved"] is True
    assert (got["answer_san"], got["answers"]) == ("Qe7", ["g6", "Qe7"])
    assert got["your_reply"] is None  # the entry says nothing about Qe7
    assert got["line_next"] is None  # the line ends here


def test_another_right_answer_than_the_line_s(client: TestClient) -> None:  # noqa: F811
    got = attempt(client, "philidor-defence", "b8c6")
    assert got["solved"] is True
    assert got["line_next"] == "2... d6"
    assert attempt(client, "philidor-defence", "d7d6")["line_next"] is None


def test_the_answer_shown_when_you_miss(client: TestClient) -> None:  # noqa: F811
    got = attempt(client, "elephant-trap", "c3d5")
    assert got["solved"] is False
    assert got["your_reply"]["loses"] is True
    assert (got["answer_san"], got["answer_reply"]["move"]) == ("e3", "6. e3")


def test_giving_up(client: TestClient, db_file: Path) -> None:  # noqa: F811
    got = attempt(client, "legal-trap", None)
    assert (got["solved"], got["move_uci"], got["move_fen"]) == (False, None, None)
    assert got["your_reply"] is None
    assert got["answer_reply"]["move"] == "5... dxe5"
    (tried,) = tries(db_file, "legal-trap")
    assert tried["move_uci"] is None


def test_the_schedule_is_core_s(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    """1, then 3 days after solves; a miss goes back to tomorrow (CLAUDE.md §7.8)."""
    assert attempt(client, "legal-trap", "d6e5")["due_on"] == "2026-11-09"
    set_day(monkeypatch, date(2026, 11, 9))
    second = attempt(client, "legal-trap", "d6e5")
    assert (second["streak"], second["due_on"]) == (2, "2026-11-12")
    set_day(monkeypatch, date(2026, 11, 12))
    third = attempt(client, "legal-trap", "g4d1")
    assert (third["streak"], third["due_on"]) == (0, "2026-11-13")


def test_the_hint_is_the_square_the_answer_starts_from(client: TestClient, db_file: Path) -> None:  # noqa: F811
    assert client.get(f"{API}/legal-trap/1/hint").json() == {"from_square": "d6"}
    attempt(client, "legal-trap", "d6e5", used_hint=True)
    (tried,) = tries(db_file, "legal-trap")
    assert tried["used_hint"] == 1


def test_a_promotion_without_a_piece_is_a_queen() -> None:
    """The same rule as Re-test, from core: e7e8 is e7e8q."""
    assert routes.retest.read_move("8/4P2k/8/8/8/8/8/K7 w - - 0 1", "e7e8") is not None


def test_an_illegal_move_records_nothing(client: TestClient, db_file: Path) -> None:  # noqa: F811
    got = client.post(f"{API}/legal-trap/1/attempt", json={"move_uci": "e1e5"})
    assert got.status_code == 422
    assert got.json() == {"detail": "'e1e5' isn't a legal move in this position."}
    assert tries(db_file, "legal-trap") == []


@pytest.mark.parametrize(
    ("path", "detail"),
    [
        ("nope/1", "There's no 'nope' in the Library."),
        ("legal-trap/2", "Légal's trap has no practise position 2."),
        ("legal-trap/0", "Légal's trap has no practise position 0."),
    ],
)
def test_unknown_positions_are_a_404(client: TestClient, path: str, detail: str) -> None:  # noqa: F811
    got = client.post(f"{API}/{path}/attempt", json={"move_uci": None})
    assert (got.status_code, got.json()) == (404, {"detail": detail})
    assert client.get(f"{API}/{path}/hint").status_code == 404


def test_only_the_page_can_record_an_attempt(client: TestClient) -> None:  # noqa: F811
    got = client.post(
        f"{API}/legal-trap/1/attempt",
        json={"move_uci": "d6e5"},
        headers={"Origin": "https://evil.example"},
    )
    assert got.status_code == 403
    page = client.post(
        f"{API}/legal-trap/1/attempt",
        json={"move_uci": "d6e5"},
        headers={"Origin": "http://127.0.0.1"},
    )
    assert page.status_code == 200


def test_other_fields_are_refused(client: TestClient) -> None:  # noqa: F811
    got = client.post(f"{API}/legal-trap/1/attempt", json={"move_uci": "d6e5", "solved": True})
    assert got.status_code == 422


# ---------------------------------------------------------------- library.db


def test_progress_is_backed_up_with_blunderbook(client: TestClient, db_file: Path) -> None:  # noqa: F811
    attempt(client, "legal-trap", "d6e5")
    result = CliRunner().invoke(cli.app, ["backup"])
    assert result.exit_code == 0, result.output
    assert "library" in result.output
    backups = sorted((db_file.parent / "backups").glob("library-*.db"))
    assert len(backups) == 1
    with closing(sqlite3.connect(backups[0])) as conn:
        assert conn.execute("SELECT entry_id, status FROM progress").fetchall() == [
            ("legal-trap", "solved")
        ]


def test_your_log_is_left_alone(client: TestClient, db_file: Path) -> None:  # noqa: F811
    attempt(client, "legal-trap", "d6e5")
    with closing(sqlite3.connect(db_file)) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "progress" not in tables and "attempts" not in tables
