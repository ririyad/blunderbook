"""The Library's routes and page (ROADMAP 11.2): the index, one entry with the FEN after
every move, and no practise answer anywhere before 11.3 asks for an attempt."""

from collections.abc import Iterator
from pathlib import Path

import chess
import pytest
from blunderbook_library import content, extension, routes
from fastapi.testclient import TestClient

from blunderbook import ext, webcheck
from blunderbook.api.app import create_app

URL = "http://127.0.0.1"


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(tmp_path / "blunderbook.db", [extension]), base_url=URL) as c:
        yield c


def test_the_index_lists_every_entry_in_kind_order(client: TestClient) -> None:
    listed = client.get("/api/ext/library/entries").json()
    assert len(listed) == 15
    kinds = [e["kind"] for e in listed]
    assert kinds == sorted(kinds, key=list(content.KINDS).index)
    legal = next(e for e in listed if e["id"] == "legal-trap")
    assert legal == {
        "id": "legal-trap",
        "kind": "trap",
        "name": "Légal's trap",
        "side": "black",
        "opening": "Philidor Defence",
        "eco": "C41",
    }


def test_an_entry_has_the_fen_after_every_move(client: TestClient) -> None:
    got = client.get("/api/ext/library/entries/legal-trap").json()
    assert got["name"] == "Légal's trap"
    assert got["idea"].startswith("Your bishop on g4 pins")
    assert got["start_fen"] == chess.STARTING_FEN
    moves = got["moves"]
    assert [m["label"] for m in moves[:3]] == ["1. e4", "1... e5", "2. Nf3"]
    assert moves[-1] == {
        "label": "5. Nxe5",
        "san": "Nxe5",
        "uci": "f3e5",
        "move_no": 5,
        "color": "white",
        "fen": moves[-1]["fen"],
    }
    board = chess.Board()
    for m in moves:
        board.push_uci(m["uci"])
        assert m["fen"] == board.fen(), m["label"]


def test_each_reply_is_played_out_from_the_end_of_the_line(client: TestClient) -> None:
    got = client.get("/api/ext/library/entries/legal-trap").json()
    loses, holds = got["next"]
    assert [m["label"] for m in loses["moves"]] == ["5... Bxd1", "6. Bxf7+", "6... Ke7", "7. Nd5#"]
    assert loses["loses"] is True
    assert loses["says"].startswith("Takes the queen.")
    assert chess.Board(loses["moves"][-1]["fen"]).is_checkmate()
    assert [m["label"] for m in holds["moves"]] == ["5... dxe5", "6. Qxg4"]
    assert holds["loses"] is False
    board = chess.Board(got["moves"][-1]["fen"])
    for m in holds["moves"]:
        board.push_uci(m["uci"])
        assert m["fen"] == board.fen()


def test_a_tactic_from_a_fen_has_its_start_position(client: TestClient) -> None:
    entry = next(e for e in content.load().entries if e.id == "back-rank-mate")
    got = client.get("/api/ext/library/entries/back-rank-mate").json()
    assert got["start_fen"] == entry.start_fen
    assert len(got["moves"]) == len(entry.moves)


def test_every_entry_can_be_opened(client: TestClient) -> None:
    for summary in client.get("/api/ext/library/entries").json():
        got = client.get(f"/api/ext/library/entries/{summary['id']}")
        assert got.status_code == 200, summary["id"]


def test_an_unknown_entry_is_a_404(client: TestClient) -> None:
    got = client.get("/api/ext/library/entries/no-such-trap")
    assert got.status_code == 404
    assert got.json() == {"detail": "There's no 'no-such-trap' in the Library."}


def test_no_practise_answer_is_sent(client: TestClient) -> None:
    """Answers come with an attempt in 11.3, never before (as core's Re-test queue)."""
    for entry in content.load().entries:
        text = client.get(f"/api/ext/library/entries/{entry.id}").text
        assert "practise" not in text and "answers" not in text and "prompt" not in text
        # The line's own moves are on the page anyway; any other answer would be a leak.
        shown = {m.uci for m in entry.moves} | {
            m.uci for n in entry.next for m in (n.move, *n.line)
        }
        for practise in entry.practise:
            for answer in practise.answers:
                if answer.uci not in shown:
                    assert f'"{answer.uci}"' not in text, (entry.id, answer.san)


def test_the_tab_is_listed(client: TestClient) -> None:
    assert client.get("/api/extensions").json() == [
        {"name": "library", "title": "Library", "css": True}
    ]
    page = client.get("/ext/library/view.js")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/javascript")


def test_the_page_passes_the_checks(tmp_path: Path) -> None:
    folder = ext.web_folder(extension)
    assert folder is not None
    assert webcheck.problems(folder, create_app(tmp_path / "blunderbook.db", [extension])) == []


def test_entries_are_read_once() -> None:
    assert routes.entries() is routes.entries()
