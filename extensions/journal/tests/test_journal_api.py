"""The Journal tab's routes and page (ROADMAP 19.3): the list with search and tags, a note
with its tree and its Log links, saving, pinning and deleting."""

import re
import threading
from collections.abc import Iterator
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Any, ClassVar, Self

import chess
import pytest
from blunderbook_journal import extension, routes
from fastapi.testclient import TestClient
from journal_fakes import ELEPHANT, FENCE, cfg_file  # noqa: F401  (fixtures)

from blunderbook import config, ext, host, webcheck
from blunderbook.api.app import create_app
from blunderbook.core import detect, pgn
from blunderbook.core.engine import EngineError, Line
from blunderbook.core.models import Eval, NewBlunder, NewGame
from blunderbook.db import connection, repo

URL = "http://127.0.0.1"
API = "/api/ext/journal/notes"
PACKAGE = Path(routes.__file__).parent

GAME = (
    '[White "Rashed"]\n[Black "Ivanov"]\n[Date "2026.11.12"]\n[Result "0-1"]\n'
    '[TimeControl "180+2"]\n\n'
    "1. d4 d5 2. c4 e6 3. Nc3 Nf6 4. Bg5 Nbd7 5. cxd5 exd5 6. Nxd5 Nxd5 7. Bxd8 Bb4+ 0-1"
)


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


def logged(db_file: Path) -> tuple[int, int]:
    """Your 6. Nxd5?? in a 3+2 game against Ivanov, in your Log: (entry id, game id)."""
    (parsed,) = pgn.parse(GAME).games
    move = parsed.plies[10]
    game = NewGame(
        fingerprint="fp-elephant",
        source="lichess",
        my_color="white",
        start_fen=parsed.start_fen,
        pgn=parsed.pgn,
        engine_name="Stockfish 17.1",
        engine_depth=16,
        white="Rashed",
        black="Ivanov",
        result="0-1",
        played_on=date(2026, 11, 12),
        time_control="180+2",
        tc_base_s=180,
        tc_inc_s=2,
        speed="blitz",
    )
    entry = NewBlunder(
        ply=10,
        move_no=move.move_no,
        fen_before=move.fen_before,
        played_uci=move.uci,
        played_san=move.san,
        best_uci="e2e3",
        best_san="e3",
        best_line_san="6. e3",
        accept_uci=("e2e3",),
        eval_before=Eval(cp=36),
        eval_after=Eval(cp=-409),
        swing=detect.swing(Eval(cp=36), Eval(cp=-409), "white"),
        judgment="blunder",
    )
    with closing(connection.open_db(db_file)) as conn:
        saved = repo.add_game(conn, game, [entry])
    assert saved is not None
    return saved.blunder_ids[0], saved.game_id


def new(client: TestClient, body: str) -> Any:
    response = client.post(API, json={"body": body})
    assert response.status_code == 201, response.text
    return response.json()


def listed(client: TestClient, **params: str) -> Any:
    response = client.get(API, params=params)
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------- notes


def test_an_empty_journal(client: TestClient) -> None:
    assert listed(client) == {"notes": [], "tags": [], "total": 0}


def test_write_read_and_list_a_note(client: TestClient) -> None:
    made = new(client, ELEPHANT)
    assert made["title"] == "The Elephant trap"
    assert made["body"] == ELEPHANT
    assert made["tags"] == ["qgd", "traps"]
    assert made["pinned"] is False
    assert made["doc"]["blocks"][0]["t"] == "heading"
    assert len(made["doc"]["starts"]) == 2  # the game and the diagram
    assert client.get(f"{API}/{made['id']}").json() == made
    found = listed(client)
    assert found["total"] == 1
    assert found["tags"] == [{"tag": "qgd", "notes": 1}, {"tag": "traps", "notes": 1}]
    [summary] = found["notes"]
    assert summary["id"] == made["id"]
    assert summary["title"] == "The Elephant trap"
    assert summary["snippet"].startswith("The d5 pawn looks free")


def test_a_new_empty_note(client: TestClient) -> None:
    response = client.post(API, json={})
    assert response.status_code == 201
    made = response.json()
    assert (made["title"], made["body"], made["doc"]["blocks"], made["refs"]) == ("", "", [], [])


def test_saving_answers_with_the_new_tree(client: TestClient) -> None:
    made = new(client, "# Draft")
    response = client.patch(f"{API}/{made['id']}", json={"body": "# Draft\n\n1. e4 e5 #open"})
    assert response.status_code == 200
    saved = response.json()
    assert saved["tags"] == ["open"]
    assert [m["san"] for m in saved["doc"]["moves"]] == ["e4", "e5"]
    assert saved["doc"]["starts"] == [chess.STARTING_FEN]
    assert saved["updated_at"] >= made["updated_at"]


def test_pinning_isnt_an_edit(client: TestClient) -> None:
    first = new(client, "# First")
    second = new(client, "# Second")
    response = client.patch(f"{API}/{first['id']}", json={"pinned": True})
    assert response.status_code == 200
    pinned = response.json()
    assert pinned["pinned"] is True
    assert pinned["updated_at"] == first["updated_at"]
    assert pinned["body"] == "# First"
    assert [n["id"] for n in listed(client)["notes"]] == [first["id"], second["id"]]


def test_search_and_tags(client: TestClient) -> None:
    trap = new(client, ELEPHANT)
    new(client, "# Endgames\n\nRook behind the passed pawn. #endgame")
    assert [n["id"] for n in listed(client, q="petrova")["notes"]] == [trap["id"]]
    assert [n["id"] for n in listed(client, q="eleph")["notes"]] == [trap["id"]]
    assert [n["title"] for n in listed(client, tag="endgame")["notes"]] == ["Endgames"]
    assert [n["title"] for n in listed(client, tag="#ENDGAME")["notes"]] == ["Endgames"]
    nothing = listed(client, q="najdorf")
    assert (nothing["notes"], nothing["total"]) == ([], 2)


def test_a_search_that_isnt_words(client: TestClient) -> None:
    new(client, "# Notes")
    assert listed(client, q='"*) ( - ^') == listed(client)  # no words: everything
    assert listed(client, q="x" * 5000)["notes"] == []


def test_delete(client: TestClient) -> None:
    made = new(client, "# Gone soon #x")
    assert client.delete(f"{API}/{made['id']}").status_code == 204
    assert client.get(f"{API}/{made['id']}").status_code == 404
    assert listed(client) == {"notes": [], "tags": [], "total": 0}


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", f"{API}/99", None),
        ("PATCH", f"{API}/99", {"body": "x"}),
        ("PATCH", f"{API}/99", {"pinned": True}),
        ("DELETE", f"{API}/99", None),
    ],
)
def test_no_such_note(client: TestClient, method: str, path: str, body: Any) -> None:
    response = client.request(method, path, json=body)
    assert response.status_code == 404
    assert response.json()["detail"] == "There's no such note. It may have been deleted."


@pytest.mark.parametrize(
    "body",
    [{"body": "x", "title": "y"}, {"body": 12}, {"pinned": "maybe"}, {"body": "x" * 1_000_001}],
)
def test_a_bad_save_changes_nothing(client: TestClient, body: Any) -> None:
    made = new(client, "# Kept")
    assert client.patch(f"{API}/{made['id']}", json=body).status_code == 422
    assert client.get(f"{API}/{made['id']}").json() == made


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", API, {"body": "x"}),
        ("PATCH", f"{API}/1", {"body": "x"}),
        ("DELETE", f"{API}/1", None),
    ],
)
def test_changes_from_another_site_are_refused(
    client: TestClient, method: str, path: str, body: Any
) -> None:
    new(client, "# Mine")
    response = client.request(method, path, json=body, headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    assert listed(client)["notes"][0]["title"] == "Mine"


def test_only_the_page_can_change_anything() -> None:
    """Every route that isn't a GET is for the Blunderbook page only (§10): those that
    change something, and Analyse, which starts Stockfish."""
    changes = [
        (r.path, sorted(r.methods), [d.dependency for d in r.dependencies])  # type: ignore[attr-defined]
        for r in routes.router.routes
        if getattr(r, "methods", set()) - {"GET"}
    ]
    assert [(path, methods) for path, methods, _ in changes] == [
        ("/notes", ["POST"]),
        ("/notes/{note_id}", ["PATCH"]),
        ("/notes/{note_id}", ["DELETE"]),
        ("/board", ["POST"]),
        ("/notes/{note_id}/lines", ["POST"]),
        ("/analyse", ["POST"]),
    ]
    assert all(deps == [host.same_origin] for _, _, deps in changes)


# ---------------------------------------------------------------- Log links


def test_a_log_link(client: TestClient, db_file: Path) -> None:
    entry_id, game_id = logged(db_file)
    made = new(client, f"I fell for it: [[log {entry_id}]].\n\n[[log {entry_id}]]\n")
    [ref] = made["refs"]  # once, though it's written twice
    assert ref == {
        "kind": "log",
        "id": entry_id,
        "found": True,
        "game_id": game_id,
        "opponent": "Ivanov",
        "my_color": "white",
        "speed": "blitz",
        "tc_label": "3+2",
        "played_on": "2026-11-12",
        "result": "0-1",
        "move": "6. Nxd5",
        "judgment": "blunder",
        "status": "new",
        "due_on": ref["due_on"],
        "played_uci": "c3d5",
        "best_uci": "e2e3",
        "fen": "r1bqkb1r/pppn1ppp/5n2/3p2B1/3P4/2N5/PP2PPPP/R2QKBNR w KQkq - 0 6",
        "moves": [],
    }


def test_a_game_link(client: TestClient, db_file: Path) -> None:
    _, game_id = logged(db_file)
    [ref] = new(client, f"The whole game: [[game {game_id}]]")["refs"]
    assert (ref["kind"], ref["found"], ref["opponent"], ref["result"]) == (
        "game",
        True,
        "Ivanov",
        "0-1",
    )
    assert ref["fen"] == chess.STARTING_FEN
    assert [m["san"] for m in ref["moves"]][-3:] == ["Nxd5", "Bxd8", "Bb4+"]
    assert ref["moves"][0] == {
        "san": "d4",
        "uci": "d2d4",
        "fen": "rnbqkbnr/pppppppp/8/8/3P4/8/PPP1PPPP/RNBQKBNR b KQkq - 0 1",
    }
    assert ref["move"] is None and ref["status"] is None


def test_a_link_to_something_not_in_your_log(client: TestClient, db_file: Path) -> None:
    entry_id, game_id = logged(db_file)
    made = new(client, f"[[log {entry_id + 50}]] and [[game {game_id + 50}]]")
    assert [(r["kind"], r["found"]) for r in made["refs"]] == [("log", False), ("game", False)]


def test_a_fen_entrys_game_isnt_a_game(client: TestClient, db_file: Path) -> None:
    fen_entry = NewGame(
        fingerprint="fp-fen",
        source="fen",
        my_color="white",
        start_fen=chess.STARTING_FEN,
        pgn=f'[SetUp "1"]\n[FEN "{chess.STARTING_FEN}"]\n\n1. e4 *',
        engine_name="Stockfish 17.1",
        engine_depth=16,
    )
    with closing(connection.open_db(db_file)) as conn:
        saved = repo.add_game(conn, fen_entry)
    assert saved is not None
    [ref] = new(client, f"[[game {saved.game_id}]]")["refs"]
    assert ref["found"] is False


def test_links_in_lists_quotes_and_headings(client: TestClient, db_file: Path) -> None:
    entry_id, game_id = logged(db_file)
    body = f"# See [[game {game_id}]]\n\n- [[log {entry_id}]]\n\n> [[log {entry_id + 1}]]"
    refs = new(client, body)["refs"]
    assert [(r["kind"], r["id"], r["found"]) for r in refs] == [
        ("game", game_id, True),
        ("log", entry_id, True),
        ("log", entry_id + 1, False),
    ]


def test_the_log_is_never_changed(client: TestClient, db_file: Path) -> None:
    entry_id, _ = logged(db_file)
    before = db_file.read_bytes()
    made = new(client, f"[[log {entry_id}]]")
    client.patch(f"{API}/{made['id']}", json={"body": f"[[log {entry_id}]] again"})
    client.delete(f"{API}/{made['id']}")
    assert db_file.read_bytes() == before


# ---------------------------------------------------------------- the page


def test_the_tab(client: TestClient) -> None:
    assert client.get("/api/extensions").json() == [
        {"name": "journal", "title": "Journal", "css": True}
    ]
    for name in ("view.js", "read.js", "write.js", "play.js"):
        page = client.get(f"/ext/journal/{name}")
        assert page.status_code == 200, name
        assert page.headers["content-type"].startswith("text/javascript")


def test_the_page_passes_the_checks(tmp_path: Path) -> None:
    folder = ext.web_folder(extension)
    assert folder is not None
    app = create_app(tmp_path / "blunderbook.db", [extension])
    assert webcheck.problems(folder, app, prefix="journal") == []


def test_it_uses_only_the_host_api() -> None:
    assert ext.boundary_problems(PACKAGE) == []


def test_the_page_reads_only_what_the_api_sends() -> None:
    """Every field the page reads off a note, a list answer, a summary or a Log link is in
    that part's schema. In the page those are always called note, listed, n and r."""
    folder = ext.web_folder(extension)
    assert folder is not None
    names = ("view.js", "read.js", "write.js", "play.js")
    text = "\n".join((folder / f).read_text("utf-8") for f in names)
    parts = {
        "note": routes.NoteOut,
        "listed": routes.ListOut,
        "n": routes.SummaryOut,
        "r": routes.RefOut,
        "state": routes.BoardOut,
        "answer": routes.BoardOut,
        "analysis": routes.AnalyseOut,
        "engineLine": routes.EngineLineOut,
    }
    for name, model in parts.items():
        read = set(re.findall(rf"\b{name}\.([a-z_]+)\b", text))
        assert read, name
        assert read <= set(model.model_fields), (name, read - set(model.model_fields))


def test_the_page_reads_only_what_the_tree_has() -> None:
    """read.js reads a block as `block`, a move as `m`, a span as `s` and a PGN item as
    `item`: each field it reads is one the parser writes."""
    folder = ext.web_folder(extension)
    assert folder is not None
    text = (folder / "read.js").read_text("utf-8")
    written = {
        "block": {"t", "level", "spans", "ordered", "start", "items", "kind", "id", "lang",
                  "text", "error", "headers", "result", "note", "arrows", "squares",
                  "caption", "playable"},
        "m": {"id", "san", "uci", "fen", "no", "white", "prev", "next", "start", "nag",
              "arrows", "squares"},
        "s": {"t", "text", "b", "i", "href", "tag", "kind", "id", "move"},
        "item": {"move", "comment", "line", "depth", "spans"},
        "tree": {"v", "starts", "moves", "blocks"},
    }  # fmt: skip
    for name, fields in written.items():
        read = set(re.findall(rf"\b{name}\.([a-z_]+)\b", text))
        assert read, name
        assert read <= fields, (name, read - fields)


def test_note_text_never_goes_into_html() -> None:
    """Reading mode builds the note with DOM calls: the only innerHTML is fixed markup and
    the page's own pills (CLAUDE.md §11)."""
    folder = ext.web_folder(extension)
    assert folder is not None
    text = (folder / "read.js").read_text("utf-8")
    for line in text.splitlines():
        if "innerHTML" in line:
            assert "statusPill" in line or "stepsHtml" in line or "`<div" in line, line


def test_pasted_games_and_positions_get_their_own_block() -> None:
    """write.js's paste rules, read with the same regular expressions in Python."""
    folder = ext.web_folder(extension)
    assert folder is not None
    text = (folder / "write.js").read_text("utf-8")
    fen_line = re.search(r"const FEN_LINE = /(.+)/;", text)
    assert fen_line is not None
    fen = re.compile(fen_line.group(1).replace(r"\/", "/"))
    assert fen.match("3r2k1/4qppp/8/8/8/1Q6/5PPP/2R3K1 w - - 0 32")
    assert fen.match(chess.STARTING_FEN.split(" ")[0])
    assert not fen.match("1. e4 e5 2. Nf3")
    assert FENCE in text


# ---------------------------------------------------------------- boards (19.4)

ELEPHANT_GAME = (
    f'# Trap\n\n{FENCE}pgn\n[White "?"] [Black "?"]\n'
    "1. d4 d5 2. c4 e6 3. Nc3 Nf6 4. Bg5 Nbd7 5. cxd5 exd5\n"
    f"6. Nxd5?? (6. e3 {{The quiet move.}} 6... Be7) 6... Nxd5! 7. Bxd8 Bb4+ *\n{FENCE}\n\n"
    "After 6. e3 Be7 it's quiet.\n"
)


def play(client: TestClient, fen: str, moves: list[str]) -> Any:
    return client.post("/api/ext/journal/board", json={"fen": fen, "moves": moves})


def test_play_on_a_board(client: TestClient) -> None:
    response = play(client, chess.STARTING_FEN, ["e2e4", "c7c5"])
    assert response.status_code == 200
    found = response.json()
    assert [m["san"] for m in found["moves"]] == ["e4", "c5"]
    assert found["moves"][1] == {
        "san": "c5",
        "uci": "c7c5",
        "fen": "rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2",
        "no": 1,
        "white": False,
    }
    assert (found["turn"], found["line"], found["pgn"], found["over"]) == (
        "white",
        "1. e4 c5",
        "1. e4 c5 *",
        "",
    )
    assert found["fen"] == found["moves"][1]["fen"] and "g1f3" in found["legal"]


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"fen": "nonsense"}, 422),
        ({"fen": chess.STARTING_FEN, "moves": ["e2e5"]}, 422),
        ({"fen": chess.STARTING_FEN, "moves": ["e2e4"] * 601}, 422),
        ({"fen": chess.STARTING_FEN, "extra": 1}, 422),
        ({"moves": []}, 422),
    ],
)
def test_a_board_that_cant_be_played(client: TestClient, body: Any, status: int) -> None:
    assert client.post("/api/ext/journal/board", json=body).status_code == status


def test_an_illegal_move_says_which(client: TestClient) -> None:
    response = play(client, chess.STARTING_FEN, ["e2e4", "e2e4"])
    assert response.json()["detail"] == "e2e4 isn't legal there (after 1. e4)."


def lines_url(note_id: int) -> str:
    return f"{API}/{note_id}/lines"


def pgn_block(note: Any) -> tuple[int, dict[str, Any]]:
    [(index, block)] = [(i, b) for i, b in enumerate(note["doc"]["blocks"]) if b["t"] == "pgn"]
    return index, block


def test_a_line_goes_into_the_game(client: TestClient) -> None:
    made = new(client, ELEPHANT_GAME)
    index, _ = pgn_block(made)
    before = next(m for m in made["doc"]["moves"] if m["san"] == "exd5")
    response = client.post(
        lines_url(made["id"]),
        json={"block": index, "after": before["id"], "moves": ["g1f3", "c7c6"]},
    )
    assert response.status_code == 200, response.text
    saved = response.json()
    assert "(6. Nf3 c6)" in " ".join(saved["body"].split())
    assert saved["body"].startswith("# Trap\n\n```pgn\n[White")
    assert saved["body"].endswith("```\n\nAfter 6. e3 Be7 it's quiet.\n")
    sans = [m["san"] for m in saved["doc"]["moves"]]
    assert "Nf3" in sans and "c6" in sans
    # The sentence still plays from the game's side line.
    sentence = saved["doc"]["blocks"][-1]["spans"]
    assert [s["text"] for s in sentence if s["t"] == "move"] == ["6. e3", "Be7"]


def test_a_line_from_the_games_start(client: TestClient) -> None:
    made = new(client, ELEPHANT_GAME)
    index, _ = pgn_block(made)
    response = client.post(
        lines_url(made["id"]), json={"block": index, "after": None, "moves": ["e2e4"]}
    )
    assert response.status_code == 200
    assert "1. d4 (1. e4) 1... d5" in response.json()["body"]


def test_a_line_the_game_has_already(client: TestClient) -> None:
    made = new(client, ELEPHANT_GAME)
    index, _ = pgn_block(made)
    response = client.post(
        lines_url(made["id"]), json={"block": index, "after": None, "moves": ["d2d4"]}
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "The game has that line already."
    assert client.get(f"{API}/{made['id']}").json()["body"] == ELEPHANT_GAME


@pytest.mark.parametrize(
    "change",
    [
        {"block": 0},  # the heading, not a game
        {"block": 9},
        {"after": 999},
        {"moves": ["e7e5"]},  # not legal after 5... exd5
        {"moves": []},
    ],
)
def test_a_line_that_cant_go_in(client: TestClient, change: dict[str, Any]) -> None:
    made = new(client, ELEPHANT_GAME)
    index, _ = pgn_block(made)
    exd5 = next(m for m in made["doc"]["moves"] if m["san"] == "exd5")
    body = {"block": index, "after": exd5["id"], "moves": ["g1f3"], **change}
    assert client.post(lines_url(made["id"]), json=body).status_code == 422
    assert client.get(f"{API}/{made['id']}").json()["body"] == ELEPHANT_GAME


def test_a_line_into_a_note_thats_gone(client: TestClient) -> None:
    body = {"block": 1, "after": None, "moves": ["e2e4"]}
    assert client.post(lines_url(99), json=body).status_code == 404


class StubEngine:
    """Stockfish's three lines for any position, without Stockfish."""

    name = "Stockfish 17.1"
    asked: ClassVar[list[tuple[str, int, int]]] = []

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        pass

    def lines(self, board: chess.Board, depth: int, multipv: int = 1, **_: object) -> list[Line]:
        self.asked.append((board.fen(), depth, multipv))
        return [
            Line(Eval(cp=36), (chess.Move.from_uci("e2e3"), chess.Move.from_uci("f8e7"))),
            Line(Eval(cp=-409), (chess.Move.from_uci("c3d5"),)),
            Line(Eval(mate=-3), ()),  # no moves: left out
        ]


BEFORE_NXD5 = "r1bqkb1r/pppn1ppp/5n2/3p2B1/3P4/2N5/PP2PPPP/R2QKBNR w KQkq - 0 6"


def test_analyse(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    StubEngine.asked = []
    monkeypatch.setattr(host, "engine", StubEngine)
    response = client.post("/api/ext/journal/analyse", json={"fen": BEFORE_NXD5})
    assert response.status_code == 200, response.text
    assert response.json() == {
        "fen": BEFORE_NXD5,
        "engine": "Stockfish 17.1",
        "depth": 16,
        "lines": [
            {"eval": {"cp": 36}, "uci": "e2e3", "line": "6. e3 Be7"},
            {"eval": {"cp": -409}, "uci": "c3d5", "line": "6. Nxd5"},
        ],
        "over": "",
    }
    assert StubEngine.asked == [(BEFORE_NXD5, 16, 3)]


def test_analyse_a_finished_game(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host, "engine", lambda: pytest.fail("Stockfish isn't needed"))
    mated = "rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3"
    found = client.post("/api/ext/journal/analyse", json={"fen": mated}).json()
    assert (found["over"], found["lines"], found["engine"]) == ("Checkmate", [], "")


def test_analyse_with_no_stockfish(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def missing() -> None:
        raise host.HostError("Can't analyse: Stockfish wasn't found.")

    monkeypatch.setattr(host, "engine", missing)
    response = client.post("/api/ext/journal/analyse", json={"fen": BEFORE_NXD5})
    assert response.status_code == 503
    assert response.json()["detail"] == "Can't analyse: Stockfish wasn't found."


def test_analyse_when_stockfish_stops(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    class Stops(StubEngine):
        def lines(self, *args: object, **kwargs: object) -> list[Line]:
            raise EngineError("Stockfish stopped unexpectedly.")

    monkeypatch.setattr(host, "engine", Stops)
    response = client.post("/api/ext/journal/analyse", json={"fen": BEFORE_NXD5})
    assert (response.status_code, response.json()["detail"]) == (
        503,
        "Stockfish stopped unexpectedly.",
    )


def test_one_analysis_at_a_time(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host, "engine", StubEngine)
    held = routes._analysing.acquire(blocking=False)
    assert held
    try:
        response = client.post("/api/ext/journal/analyse", json={"fen": BEFORE_NXD5})
        assert (response.status_code, response.json()["detail"]) == (409, routes.BUSY)
    finally:
        routes._analysing.release()
    assert client.post("/api/ext/journal/analyse", json={"fen": BEFORE_NXD5}).status_code == 200
    assert isinstance(routes._analysing, type(threading.Lock()))


def test_analyse_an_unplayable_position(client: TestClient) -> None:
    response = client.post("/api/ext/journal/analyse", json={"fen": "8/8/8/8/8/8/8/8 w - - 0 1"})
    assert response.status_code == 422
