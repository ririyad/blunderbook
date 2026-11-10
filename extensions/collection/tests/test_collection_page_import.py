"""Adding games on the page (ROADMAP 12.4): the import route and its job, what it refuses,
stopping it when serve stops, and your Log entries on a collection's game."""

import time
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import chess
import pytest
from blunderbook_collection import collect, extension, store
from collection_fakes import (  # noqa: F401  (fixtures)
    CLASSICS,
    FakeEngine,
    cfg_file,
    fake,
    no_engine,
)
from fastapi.testclient import TestClient
from test_collection_api import LEGAL, MORPHY, Scripted

from blunderbook import config, host, importer
from blunderbook.api.app import create_app
from blunderbook.core.engine import Line
from blunderbook.core.models import Thresholds
from blunderbook.db import connection

URL = "http://127.0.0.1"
PGN = {"Content-Type": "application/x-chess-pgn"}


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


def start(client: TestClient, text: str, into: str = "Classics") -> str:
    got = client.post(
        "/api/ext/collection/import", params={"into": into}, content=text.encode(), headers=PGN
    )
    assert got.status_code == 202, got.text
    return got.json()["job_id"]  # type: ignore[no-any-return]


def finished(client: TestClient, job_id: str) -> dict:  # type: ignore[type-arg]
    for _ in range(400):
        job = client.get(f"/api/ext/collection/import/{job_id}").json()
        if job["status"] != "running":
            return job  # type: ignore[no-any-return]
        time.sleep(0.01)
    raise AssertionError("the import didn't finish")


# ---------------------------------------------------------------- the import


def test_games_are_added_in_the_background(client: TestClient, fake: FakeEngine) -> None:
    job = finished(client, start(client, MORPHY + "\n\n" + LEGAL))
    assert (job["status"], job["collection"], job["created"], job["percent"]) == (
        "done",
        "Classics",
        True,
        100,
    )
    assert job["summary"] == "2 games read \N{MIDDLE DOT} 2 added"
    assert [(g["number"], g["status"], g["game_id"]) for g in job["games"]] == [
        (1, "added", 1),
        (2, "added", 2),
    ]
    assert job["games"][0]["players"] == "Paul Morphy vs Duke Karl / Count Isouard"
    assert job["engine_name"] == "Stockfish 17.1"
    assert (fake.opened, fake.closed) == (1, 1)
    listed = client.get("/api/ext/collection/collections").json()
    assert listed["collections"] == [{"id": job["collection_id"], "name": "Classics", "games": 2}]


def test_again_adds_nothing_and_another_collection_reuses_the_analysis(
    client: TestClient, fake: FakeEngine
) -> None:
    finished(client, start(client, MORPHY))
    again = finished(client, start(client, MORPHY, into="  classics "))
    assert (again["collection"], again["games"][0]["status"]) == ("Classics", "member")
    assert again["summary"] == "1 game read \N{MIDDLE DOT} 0 added \N{MIDDLE DOT} 1 skipped"
    other = finished(client, start(client, MORPHY, into="Morphy"))
    assert other["games"][0]["status"] == "added_known"
    assert fake.opened == 1  # neither needed Stockfish


def test_a_bad_game_and_windows_1252(client: TestClient, fake: FakeEngine) -> None:
    text = '[White "Ren\xe9"]\n[Black "B"]\n\n1. e4 e5 2. Ke3 *\n\n' + MORPHY
    got = client.post(
        "/api/ext/collection/import",
        params={"into": "Mixed"},
        content=text.encode("cp1252"),
        headers=PGN,
    )
    assert got.status_code == 202
    job = finished(client, got.json()["job_id"])
    assert job["notes"][0] == "Read as Windows-1252 (the file isn't UTF-8)."
    assert [g["status"] for g in job["games"]] == ["error", "added"]
    assert job["games"][0]["reason"]


def test_no_stockfish_is_a_failed_import(client: TestClient, no_engine: None) -> None:
    job = finished(client, start(client, MORPHY))
    assert job["status"] == "failed"
    assert job["error"].startswith("Analysis stopped: Can't analyse: Stockfish wasn't found.")
    assert job["games"][0]["status"] == "not_analysed"
    assert job["collection_id"] is None


WRONG_TYPE = "Send the PGN as application/x-chess-pgn."
NOT_THE_PAGE = "Only the Blunderbook page can do this."
TOO_LONG = "A collection's name can be at most 60 characters."
TOO_BIG = "That PGN is over 10 MB. Split it into smaller files."
ELEVEN_MB = str(11 * 1024 * 1024)


@pytest.mark.parametrize(
    ("kwargs", "status", "detail"),
    [
        ({"headers": {"Content-Type": "text/plain"}}, 415, WRONG_TYPE),
        ({"headers": {**PGN, "Origin": "https://example.com"}}, 403, NOT_THE_PAGE),
        ({"headers": PGN, "content": b"\n\n"}, 422, "No games found in this PGN."),
        ({"headers": PGN, "params": {"into": "  "}}, 422, "Give the collection a name."),
        ({"headers": PGN, "params": {"into": "x" * 61}}, 422, TOO_LONG),
        ({"headers": {**PGN, "Content-Length": ELEVEN_MB}}, 413, TOO_BIG),
    ],
)
def test_the_import_refuses(
    client: TestClient,
    fake: FakeEngine,
    kwargs: dict,
    status: int,
    detail: str,  # type: ignore[type-arg]
) -> None:
    sent = {"params": {"into": "Classics"}, "content": MORPHY.encode(), **kwargs}
    got = client.post("/api/ext/collection/import", **sent)
    assert (got.status_code, got.json()["detail"]) == (status, detail)
    assert client.get("/api/ext/collection/collections").json()["collections"] == []


def test_an_unknown_import_is_a_404(client: TestClient) -> None:
    got = client.get("/api/ext/collection/import/nope")
    assert got.status_code == 404


class Slow(FakeEngine):
    """A FakeEngine that takes a little while over each position."""

    def lines(
        self, board: chess.Board, depth: int, multipv: int = 1, *, game: object = None
    ) -> list[Line]:
        time.sleep(0.01)
        return super().lines(board, depth, multipv, game=game)


def test_one_import_at_a_time(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host, "engine", Slow())
    first = start(client, MORPHY)
    got = client.post(
        "/api/ext/collection/import", params={"into": "Other"}, content=LEGAL.encode(), headers=PGN
    )
    assert (got.status_code, got.json()["detail"]) == (
        409,
        "Games are already being added to a collection. Wait for it to finish.",
    )
    assert finished(client, first)["status"] == "done"
    assert finished(client, start(client, LEGAL, into="Other"))["status"] == "done"


def test_stopping_serve_stops_the_import(db_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    slow = Slow()
    monkeypatch.setattr(host, "engine", slow)
    app = create_app(db_file, [extension])
    with TestClient(app, base_url=URL) as c:
        job_id = start(c, MORPHY)
        while not slow.calls:
            time.sleep(0.005)
    job = app.state.collection_jobs.get(job_id).view()
    assert job.status == "stopped"
    assert job.error.startswith("The import was stopped.")
    assert slow.closed == 1
    with closing(host.open_db(extension)) as conn:
        assert store.collections(conn) == []  # the game being analysed isn't saved


def test_collect_add_checks_should_stop(fake: FakeEngine, db_file: Path) -> None:
    with closing(host.open_db(extension)) as conn:
        queued = collect.queue(conn, MORPHY, "Classics")
        result = collect.add(conn, "Classics", queued, fake, depth=8, should_stop=lambda: True)  # type: ignore[arg-type]
    assert result.stopped and not result.added and fake.calls == []


# ---------------------------------------------------------------- your Log


def test_a_game_lists_your_log_entries_from_its_positions(
    client: TestClient, fake: FakeEngine, db_file: Path
) -> None:
    finished(client, start(client, MORPHY + "\n\n" + LEGAL))
    # Your own game: you were Black in Légal's game, and 5... Bxd1 is in your Log.
    (queued,) = importer.prepare(LEGAL, ["Saint Brie"])
    analysed = importer.analyse(queued, Scripted(), depth=8, thresholds=Thresholds())
    with closing(connection.connect(db_file)) as conn:
        saved = importer.save(conn, analysed)
    assert saved is not None
    (entry_id,) = saved.blunder_ids
    legal = client.get("/api/ext/collection/games/2").json()
    assert legal["yours"] == [
        {
            "id": entry_id,
            "label": "5... Bxd1",
            "judgment": "blunder",
            "status": "new",
            "source": "otb",
            "opponent": "Kermur de Legal",
            "played_on": None,
            "ply": 9,
        }
    ]
    assert client.get("/api/ext/collection/games/1").json()["yours"] == []
