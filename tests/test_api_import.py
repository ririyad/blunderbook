"""Web import and FEN quick entry (CLAUDE.md §10, "Web import"), through FastAPI's
TestClient, against a temp config and database, with a scripted engine (no Stockfish)."""

import threading
import time
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
from typing import Any

import chess
import pytest
from fastapi.testclient import TestClient
from test_cli_import import FIXTURES, StubEngine, program

from blunderbook import config, importer
from blunderbook.api import jobs as jobs_module
from blunderbook.api.app import create_app
from blunderbook.core import engine
from blunderbook.core.engine import Line
from blunderbook.core.models import Eval
from blunderbook.db import connection, repo

URL = "http://127.0.0.1"
PGN = {"Content-Type": "application/x-chess-pgn"}
ELEPHANT_BEFORE = "r1bqkb1r/pppn1ppp/5n2/3p2B1/3P4/2N5/PP2PPPP/R2QKBNR w KQkq - 0 6"
ELEPHANT_AFTER = "r1bqkb1r/pppn1ppp/5n2/3N2B1/3P4/8/PP2PPPP/R2QKBNR b KQkq - 0 6"
BACK_RANK = "3r2k1/4qppp/8/8/8/1Q6/5PPP/2R3K1 w - - 0 32"
AFTER_RC7 = "3r2k1/2R1qppp/8/8/8/1Q6/5PPP/6K1 b - - 1 32"


class GatedEngine(StubEngine):
    """A stub that can pause at its ``gate_at``-th position until ``gate`` is set."""

    def __init__(self, table: dict[str, Line]) -> None:
        super().__init__(table)
        self.gate_at: int | None = None
        self.gate = threading.Event()
        self.reached = threading.Event()

    def lines(
        self, board: chess.Board, depth: int, multipv: int = 1, *, game: object = None
    ) -> list[Line]:
        if self.gate_at is not None and self.positions + 1 == self.gate_at:
            self.reached.set()
            assert self.gate.wait(10), "the test never opened the gate"
        return super().lines(board, depth, multipv, game=game)


@pytest.fixture
def cfg_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "home" / "config.toml"
    monkeypatch.setattr(config, "config_path", lambda: path)
    monkeypatch.delenv(config.STOCKFISH_ENV, raising=False)
    monkeypatch.setattr("shutil.which", lambda _: None)
    return path


@pytest.fixture
def ready(tmp_path: Path, cfg_file: Path) -> Path:
    """A config with your name and a (fake) Stockfish program."""
    exe = program(tmp_path / "sf")
    config.save(config.Config(my_names=("Rashed",), stockfish_path=str(exe)), cfg_file)
    return exe


@pytest.fixture
def sf(monkeypatch: pytest.MonkeyPatch) -> GatedEngine:
    stub = GatedEngine(
        {
            ELEPHANT_BEFORE: Line(Eval(cp=36), tuple(map(chess.Move.from_uci, ["e2e3", "f8e7"]))),
            ELEPHANT_AFTER: Line(Eval(cp=-409), (chess.Move.from_uci("f6d5"),)),
            BACK_RANK: Line(Eval(cp=30), (chess.Move.from_uci("b3c4"),)),
            AFTER_RC7: Line(Eval(cp=-100), (chess.Move.from_uci("e7c7"),)),
        }
    )
    monkeypatch.setattr(engine.Engine, "open", staticmethod(lambda command, **_: stub))
    return stub


@pytest.fixture
def client(db_file: Path) -> Iterator[TestClient]:
    with closing(connection.open_db(db_file, create=True)):
        pass
    with TestClient(create_app(db_file), base_url=URL) as test_client:
        yield test_client


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def start(client: TestClient, body: bytes, **headers: str) -> Any:
    return client.post("/api/import", content=body, headers={**PGN, **headers})


def wait(client: TestClient, job_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 10
    while True:
        response = client.get(f"/api/import/{job_id}")
        assert response.status_code == 200, response.text
        job: dict[str, Any] = response.json()
        if job["status"] != "running":
            return job
        assert time.monotonic() < deadline, job
        time.sleep(0.01)


def imported(client: TestClient, body: bytes, **headers: str) -> dict[str, Any]:
    response = start(client, body, **headers)
    assert response.status_code == 202, response.text
    return wait(client, response.json()["job_id"])


def counts(db_file: Path) -> tuple[int, int]:
    with closing(connection.connect(db_file)) as conn:
        totals = repo.totals(conn)
    return totals.games, totals.entries


# ---------------------------------------------------------------- import


def test_an_import_runs_to_the_end(client: TestClient, ready: Path, sf: GatedEngine) -> None:
    job = imported(client, fixture("qgd_elephant.pgn"))
    assert (job["status"], job["percent"], job["error"]) == ("done", 100, None)
    assert job["engine_name"] == "Stockfish 17.1"
    (game,) = job["games"]
    assert game["status"] == "imported"
    assert (game["players"], game["date"], game["my_color"]) == (
        "Rashed vs Karim S.",
        "2026-10-12",
        "white",
    )
    (entry,) = game["entries"]
    assert (entry["label"], entry["judgment"]) == ("6. Nxd5", "blunder")
    assert job["summary"] == "1 game read \N{MIDDLE DOT} 1 blunder added"
    listed = client.get("/api/blunders").json()
    assert [item["id"] for item in listed] == [entry["id"]]


def test_the_same_games_twice_add_nothing(
    client: TestClient, ready: Path, sf: GatedEngine, db_file: Path
) -> None:
    imported(client, fixture("qgd_elephant.pgn"))
    before, positions = counts(db_file), sf.positions
    job = imported(client, fixture("qgd_elephant.pgn"))
    (game,) = job["games"]
    assert (game["status"], game["reason"]) == ("duplicate", importer.ALREADY_IMPORTED)
    assert counts(db_file) == before
    assert sf.positions == positions  # nothing to analyse, so no engine


def test_a_file_with_problems_reports_each_game(
    client: TestClient, ready: Path, sf: GatedEngine
) -> None:
    job = imported(client, fixture("multi_game.pgn"))
    assert job["status"] == "done"
    rows = {g["number"]: g for g in job["games"]}
    assert [rows[n]["status"] for n in (1, 2, 3, 4)] == [
        "imported",
        "error",
        "imported",
        "needs_side",
    ]
    assert rows[2]["reason"] == "Illegal move 2. Ke3"
    assert rows[4]["reason"] == jobs_module.NEEDS_SIDE
    assert "1 needs side" in job["summary"] and "1 error" in job["summary"]


def test_windows_1252_text_is_read_with_a_note(
    client: TestClient, ready: Path, sf: GatedEngine
) -> None:
    text = (
        fixture("qgd_elephant.pgn")
        .decode("utf-8")
        .replace("[Event ", '[Annotator "Café"]\n[Event ', 1)
    )
    job = imported(client, text.encode("cp1252"))
    assert job["status"] == "done"
    assert jobs_module.READ_AS_CP1252 in job["notes"]
    assert job["games"][0]["status"] == "imported"


def test_text_with_no_games(client: TestClient, ready: Path, sf: GatedEngine) -> None:
    response = start(client, b"   \n")
    assert response.status_code == 422
    assert response.json()["detail"] == "No games found in this PGN."


def test_no_stockfish_starts_nothing(
    client: TestClient, cfg_file: Path, sf: GatedEngine, ready: Path
) -> None:
    config.save(config.Config(my_names=("Rashed",)), cfg_file)  # no path, nothing on PATH
    response = start(client, fixture("qgd_elephant.pgn"))
    assert response.status_code == 503
    assert response.json()["detail"].startswith("Can't analyse: No Stockfish found.")
    # The engine slot was given back: once Stockfish is set, an import runs.
    config.save(config.Config(my_names=("Rashed",), stockfish_path=str(ready)), cfg_file)
    assert imported(client, fixture("qgd_elephant.pgn"))["status"] == "done"


def test_one_import_at_a_time(client: TestClient, ready: Path, sf: GatedEngine) -> None:
    sf.gate_at = 3
    response = start(client, fixture("qgd_elephant.pgn"))
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    assert sf.reached.wait(5)
    running = client.get(f"/api/import/{job_id}").json()
    assert running["status"] == "running"
    assert running["games"][0]["status"] == "analysing"
    assert (running["game"], running["game_index"], running["games_to_analyse"]) == (1, 1, 1)
    assert 0 < running["percent"] < 100
    assert start(client, fixture("legal_trap.pgn")).status_code == 409
    fen = client.post("/api/fen", json={"fen": BACK_RANK, "move": "c1c7"})
    assert fen.status_code == 409
    assert fen.json()["detail"] == jobs_module.BUSY
    sf.gate.set()
    assert wait(client, job_id)["status"] == "done"


def test_stopping_keeps_the_games_before(
    client: TestClient, ready: Path, sf: GatedEngine, db_file: Path
) -> None:
    (first, *_) = importer.prepare(fixture("multi_game.pgn").decode(), ["Rashed"])
    assert first.game is not None
    sf.gate_at = len(first.game.plies) + 1 + 2  # 2 positions into game 3
    job_id = start(client, fixture("multi_game.pgn")).json()["job_id"]
    assert sf.reached.wait(5)
    jobs: jobs_module.ImportJobs = client.app.state.jobs  # type: ignore[attr-defined]
    stopper = threading.Thread(target=jobs.stop)
    stopper.start()
    time.sleep(0.05)
    sf.gate.set()
    stopper.join(5)
    job = wait(client, job_id)
    assert job["status"] == "stopped"
    assert job["error"] == f"The import was stopped. {jobs_module.AGAIN}"
    rows = {g["number"]: g["status"] for g in job["games"]}
    assert (rows[1], rows[3]) == ("imported", "not_analysed")
    assert counts(db_file)[0] == 1  # the game being analysed isn't saved
    assert sf.closed


def test_an_engine_failure_keeps_the_games_before(
    client: TestClient, ready: Path, sf: GatedEngine, db_file: Path
) -> None:
    (first, *_) = importer.prepare(fixture("multi_game.pgn").decode(), ["Rashed"])
    assert first.game is not None
    sf.fail_after = len(first.game.plies) + 3
    job = imported(client, fixture("multi_game.pgn"))
    assert job["status"] == "failed"
    assert job["error"] == f"Analysis stopped: Stockfish stopped unexpectedly. {jobs_module.AGAIN}"
    assert counts(db_file)[0] == 1
    # Importing again finishes the rest.
    sf.fail_after = None
    again = imported(client, fixture("multi_game.pgn"))
    assert {g["number"]: g["status"] for g in again["games"]}[3] == "imported"


def test_a_failed_daily_backup_is_a_note(
    client: TestClient, ready: Path, sf: GatedEngine, cfg_file: Path, tmp_path: Path
) -> None:
    imported(client, fixture("qgd_elephant.pgn"))  # an empty database isn't backed up
    blocker = tmp_path / "a file"
    blocker.write_bytes(b"")
    cfg = config.load(cfg_file)
    config.save(
        config.Config(
            my_names=cfg.my_names,
            stockfish_path=cfg.stockfish_path,
            backup=config.BackupConfig(dir=str(blocker / "bk")),
        ),
        cfg_file,
    )
    job = imported(client, fixture("blackburne_shilling.pgn"))
    assert job["status"] == "done"
    assert any(n.startswith("The daily backup didn't work:") for n in job["notes"])


def test_an_unknown_job(client: TestClient) -> None:
    response = client.get("/api/import/nope")
    assert response.status_code == 404


# ---------------------------------------------------------------- guards


def test_other_websites_cant_import(client: TestClient, ready: Path, sf: GatedEngine) -> None:
    response = start(client, fixture("qgd_elephant.pgn"), Origin="https://evil.example")
    assert response.status_code == 403
    fen = client.post(
        "/api/fen", json={"fen": BACK_RANK, "move": "c1c7"}, headers={"Origin": "null"}
    )
    assert fen.status_code == 403
    assert start(client, fixture("qgd_elephant.pgn"), Origin=URL).status_code == 202


@pytest.mark.parametrize("kind", ["text/plain", "application/json", ""])
def test_the_pgn_type_is_required(client: TestClient, kind: str) -> None:
    response = client.post("/api/import", content=b"1. e4 *", headers={"Content-Type": kind})
    assert response.status_code == 415


def test_more_than_10_mb_is_refused(client: TestClient) -> None:
    response = start(client, b" " * (10 * 1024 * 1024 + 1))
    assert response.status_code == 413


# ---------------------------------------------------------------- FEN


def fen(client: TestClient, **body: Any) -> Any:
    return client.post("/api/fen", json={"fen": BACK_RANK, "move": "c1c7", **body})


def test_a_fen_entry_is_logged_once(
    client: TestClient, ready: Path, sf: GatedEngine, db_file: Path
) -> None:
    response = fen(client, opponent="Coach", date="2026-11-01")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["result"] == "logged"
    assert body["message"].startswith("Logged 32. Rc7")
    assert body["message"].endswith(f"entry #{body['entry_id']}.")
    entry = client.get(f"/api/blunders/{body['entry_id']}").json()
    assert (entry["game"]["opponent"], entry["game"]["played_on"]) == ("Coach", "2026-11-01")

    positions = sf.positions
    again = fen(client, opponent="Coach", date="2026-11-01").json()
    assert (again["result"], again["entry_id"]) == ("already_logged", body["entry_id"])
    assert sf.positions == positions  # checked before Stockfish runs


def test_a_fen_entry_that_isnt_a_mistake(client: TestClient, ready: Path, sf: GatedEngine) -> None:
    sf.table[BACK_RANK] = Line(Eval(cp=30), (chess.Move.from_uci("c1c7"),))
    body = fen(client).json()
    assert body == {
        "result": "best_move",
        "message": "32. Rc7 is Stockfish's own choice here. Nothing was logged.",
        "entry_id": None,
        "notes": [],
    }


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"fen": "not a position", "move": "e2e4"}, 422),
        ({"fen": BACK_RANK, "move": "e2e4"}, 422),  # not a legal move
        ({"fen": BACK_RANK}, 422),
        ({"fen": BACK_RANK, "move": "c1c7", "side": "white"}, 422),
        ({"fen": BACK_RANK, "move": "c1c7", "date": "yesterday"}, 422),
    ],
)
def test_a_bad_fen_entry(
    client: TestClient, ready: Path, sf: GatedEngine, body: dict[str, Any], status: int
) -> None:
    response = client.post("/api/fen", json=body)
    assert response.status_code == status
    assert sf.positions == 0


# ---------------------------------------------------------------- the import's name (Games tab)


def import_labels(db_file: Path) -> list[tuple[str, str]]:
    with closing(connection.connect(db_file, mode="ro")) as conn:
        rows = conn.execute("SELECT label, kind FROM imports ORDER BY id").fetchall()
    return [tuple(r) for r in rows]


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        (
            {"X-Pgn-Name": "blitz%20week%20%E2%80%94%20Nov.pgn"},
            ("blitz week \u2014 Nov.pgn", "file"),
        ),
        ({"X-Pgn-Name": "C%3A%5Cgames%5Cclub.pgn"}, ("club.pgn", "file")),
        ({}, ("Pasted PGN", "paste")),
    ],
    ids=["file", "path", "pasted"],
)
def test_the_import_is_named(
    client: TestClient,
    ready: Path,
    sf: GatedEngine,
    db_file: Path,
    headers: dict[str, str],
    expected: tuple[str, str],
) -> None:
    job = imported(client, fixture("qgd_elephant.pgn"), **headers)
    assert job["status"] == "done", job
    assert import_labels(db_file) == [expected]
