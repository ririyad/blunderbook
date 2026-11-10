"""The Collection's routes and page (ROADMAP 12.3): the collections, a collection's stats with
the CLI's filters, its players, and one game with every move judged, from evals made up for
the test (Légal's 5... Bxd1 lets White mate)."""

from collections.abc import Iterator
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import chess
import pytest
from blunderbook_collection import collect, extension, routes
from collection_fakes import (  # noqa: F401  (fixtures)
    CLASSICS,
    FakeEngine,
    cfg_file,
)
from fastapi.testclient import TestClient

from blunderbook import config, ext, host, webcheck
from blunderbook.api.app import create_app
from blunderbook.core import pgn
from blunderbook.core.engine import Line
from blunderbook.core.models import Eval, Thresholds
from blunderbook.db import connection

URL = "http://127.0.0.1"
TEXT = CLASSICS.read_text("utf-8")
MORPHY = TEXT.split("\n\n[Event")[0]
LEGAL = "[Event" + TEXT.split("\n\n[Event")[1]


class Scripted(FakeEngine):
    """FakeEngine, with Légal's game scored: +0.20 until 5... Bxd1, then White mates."""

    def __init__(self) -> None:
        super().__init__()
        plies = pgn.parse(LEGAL).games[0].plies
        move = chess.Move.from_uci
        bxd1, bxf7, ke7, nd5 = plies[9], plies[10], plies[11], plies[12]
        self.table = {
            bxd1.fen_before: Line(Eval(cp=20), (move("d6e5"),)),
            bxf7.fen_before: Line(Eval(mate=2), (move(bxf7.uci), move(ke7.uci))),
            ke7.fen_before: Line(Eval(mate=1), (move(ke7.uci), move(nd5.uci))),
            nd5.fen_before: Line(Eval(mate=1), (move(nd5.uci),)),
        }

    def lines(
        self, board: chess.Board, depth: int, multipv: int = 1, *, game: object = None
    ) -> list[Line]:
        found = self.table.get(board.fen())
        if found is not None:
            self.calls.append(board.fen())
            return [found]
        return super().lines(board, depth, multipv, game=game)


@pytest.fixture
def db_file(cfg_file: Path) -> Path:
    """Blunderbook's database, and collection.db with Morphy's game and Légal's in
    "Classics", Légal's in "Traps" too."""
    path = config.db_path()
    with closing(connection.open_db(path, create=True)):
        pass
    engine = Scripted()
    with closing(host.open_db(extension)) as conn:
        for name, text in (("Classics", MORPHY + "\n\n" + LEGAL), ("Traps", LEGAL)):
            collect.add(conn, name, collect.queue(conn, text, name), engine, depth=8)  # type: ignore[arg-type]
    return path


@pytest.fixture
def client(db_file: Path) -> Iterator[TestClient]:
    with TestClient(create_app(db_file, [extension]), base_url=URL) as c:
        yield c


def stats(client: TestClient, **params: str) -> dict:  # type: ignore[type-arg]
    got = client.get("/api/ext/collection/stats", params=params)
    assert got.status_code == 200, got.text
    return got.json()  # type: ignore[no-any-return]


# ---------------------------------------------------------------- the collections


def test_the_collections(client: TestClient) -> None:
    assert client.get("/api/ext/collection/collections").json() == {
        "collections": [
            {"id": 1, "name": "Classics", "games": 2},
            {"id": 2, "name": "Traps", "games": 1},
        ],
        "games": 2,
    }


def test_no_collections_yet(cfg_file: Path) -> None:
    path = config.db_path()
    with closing(connection.open_db(path, create=True)):
        pass
    with closing(ext.open_db(extension, config.load(cfg_file))):
        pass
    with TestClient(create_app(path, [extension]), base_url=URL) as c:
        assert c.get("/api/ext/collection/collections").json() == {"collections": [], "games": 0}
        assert stats(c)["total"] == 0


# ---------------------------------------------------------------- stats


def test_a_collections_stats(client: TestClient) -> None:
    got = stats(client, collection="1")
    assert (got["title"], got["collection"], got["total"], got["games"]) == ("Classics", 1, 2, 2)
    assert got["labels"] == ["White", "Black"]
    assert got["score"] == {"won": 2, "drawn": 0, "lost": 0, "unfinished": 0}
    white, black = got["sides"]
    assert (white["games"], white["blunders"], black["blunders"]) == (2, 0, 1)
    assert [p["phase"] for p in got["phases"]] == ["opening", "middlegame", "endgame"]
    assert got["players"][:2] == ["Duke Karl / Count Isouard", "Kermur de Legal"]
    assert got["opening_options"] == [
        {"eco": "C41", "name": None},  # Légal's game has the code, not the name
        {"eco": "C41", "name": "Philidor Defence"},
    ]
    assert got["engines"] == ["Stockfish 17.1 \N{MIDDLE DOT} depth 8"]
    morphy, legal = got["lines"]
    assert (morphy["white"], morphy["date"], morphy["moves"]) == ("Paul Morphy", "1858", 17)
    assert (legal["by_side"][1]["blunders"], legal["by_side"][1]["moves"]) == (1, 6)


def test_every_collection_counts_each_game_once(client: TestClient) -> None:
    got = stats(client)
    assert (got["title"], got["collection"], got["total"]) == ("All collections", None, 2)


def test_a_players_stats(client: TestClient) -> None:
    got = stats(client, collection="1", player="  saint   BRIE ", result="lost")
    assert (got["games"], got["labels"]) == (1, ["Saint Brie", "Opponents"])
    assert got["sides"][0]["blunders"] == 1
    assert got["lines"][0]["player_color"] == "black"
    assert stats(client, collection="1", player="Saint Brie", result="won")["games"] == 0


def test_the_other_filters(client: TestClient) -> None:
    assert stats(client, color="black")["labels"] == ["Black", "White"]
    assert stats(client, result="black")["games"] == 0
    assert stats(client, opening="c4")["games"] == 2
    assert stats(client, opening="sicilian")["games"] == 0
    assert [p["moves"] for p in stats(client, collection="2")["phases"]] == [13, 0, 0]
    later = stats(client, collection="2", phase="middlegame")
    assert later["games"] == 1 and later["sides"][0]["moves"] == 0


@pytest.mark.parametrize(
    ("params", "status", "detail"),
    [
        ({"result": "won"}, 422, "A won result needs a player: whose result is it?"),
        ({"collection": "9"}, 404, "No collection #9."),
        ({"collection": "classics"}, 422, "collection is a collection's number, or all."),
    ],
)
def test_stats_refuse(client: TestClient, params: dict[str, str], status: int, detail: str) -> None:
    got = client.get("/api/ext/collection/stats", params=params)
    assert (got.status_code, got.json()["detail"]) == (status, detail)


def test_bad_filter_values_are_refused(client: TestClient) -> None:
    for params in ({"phase": "late"}, {"color": "red"}, {"player": "x" * 101}):
        assert client.get("/api/ext/collection/stats", params=params).status_code == 422


def test_your_thresholds_are_read_on_each_request(client: TestClient, cfg_file: Path) -> None:
    assert stats(client, collection="2")["sides"][1]["blunders"] == 1
    cfg = config.load(cfg_file)
    config.save(replace(cfg, thresholds=Thresholds(blunder=0.99)), cfg_file)
    black = stats(client, collection="2")["sides"][1]
    assert (black["blunders"], black["mistakes"]) == (0, 1)


# ---------------------------------------------------------------- players


def test_the_players(client: TestClient) -> None:
    got = client.get("/api/ext/collection/players", params={"collection": "2"}).json()
    assert got["title"] == "Traps"
    assert got["players"] == [
        {
            "name": "Kermur de Legal",
            "games": 1,
            "as_white": 1,
            "as_black": 0,
            "score": {"won": 1, "drawn": 0, "lost": 0, "unfinished": 0},
            "accuracy": got["players"][0]["accuracy"],
        },
        {
            "name": "Saint Brie",
            "games": 1,
            "as_white": 0,
            "as_black": 1,
            "score": {"won": 0, "drawn": 0, "lost": 1, "unfinished": 0},
            "accuracy": got["players"][1]["accuracy"],
        },
    ]
    assert got["players"][1]["accuracy"] < got["players"][0]["accuracy"]


# ---------------------------------------------------------------- one game


def test_a_game_has_every_position_and_move(client: TestClient) -> None:
    got = client.get("/api/ext/collection/games/2").json()
    assert (got["white"], got["black"], got["result"]) == ("Kermur de Legal", "Saint Brie", "1-0")
    assert got["collections"] == [{"id": 1, "name": "Classics"}, {"id": 2, "name": "Traps"}]
    assert got["engine"] == "Stockfish 17.1 \N{MIDDLE DOT} depth 8"
    assert len(got["positions"]) == len(got["moves"]) + 1 == 14
    assert got["positions"][0]["fen"] == chess.STARTING_FEN
    assert got["positions"][-1]["eval"] == {"mate": 0}
    assert got["positions"][-1]["chances"] == 1.0  # Black is mated: White's chances are 1
    assert got["positions"][1]["chances"] == pytest.approx(0.518, abs=0.001)
    marked = [m for m in got["moves"] if m["judgment"]]
    assert [m["label"] for m in marked] == ["5... Bxd1"]
    (bxd1,) = marked
    assert bxd1 == bxd1 | {
        "ply": 9,
        "color": "black",
        "uci": "g4d1",
        "judgment": "blunder",
        "best_san": "dxe5",
        "best_line": "5... dxe5",
        "refutation": "6. Bxf7+ Ke7",
    }
    plain = got["moves"][0]
    assert (plain["label"], plain["judgment"], plain["best_san"]) == ("1. e4", None, None)
    assert plain["refutation"] is None


def test_an_unknown_game_is_a_404(client: TestClient) -> None:
    got = client.get("/api/ext/collection/games/99")
    assert (got.status_code, got.json()["detail"]) == (404, "No game #99 in your collections.")


@pytest.mark.parametrize(
    ("date", "label"),
    [("1858.??.??", "1858"), ("1858.10.31", "1858-10-31"), ("????.??.??", None), (None, None)],
)
def test_date_label(date: str | None, label: str | None) -> None:
    assert routes.date_label(date) == label


# ---------------------------------------------------------------- the tab


def test_the_tab_is_listed(client: TestClient) -> None:
    assert client.get("/api/extensions").json() == [
        {"name": "collection", "title": "Collection", "css": True}
    ]
    page = client.get("/ext/collection/view.js")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/javascript")


def test_the_page_passes_the_checks(tmp_path: Path) -> None:
    folder = ext.web_folder(extension)
    assert folder is not None
    app = create_app(tmp_path / "blunderbook.db", [extension])
    assert webcheck.problems(folder, app, prefix="collection") == []


def test_only_the_import_changes_anything() -> None:
    """Every route is a GET but the import, which only the page may call (§10)."""
    changes = [
        (r.path, r.dependencies)  # type: ignore[attr-defined]
        for r in routes.router.routes
        if getattr(r, "methods", set()) - {"GET"}
    ]
    assert [path for path, _ in changes] == ["/import"]
    assert [d.dependency for d in changes[0][1]] == [host.same_origin]
