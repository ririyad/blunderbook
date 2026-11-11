"""The Log's API (CLAUDE.md §10) against a real temp database, through FastAPI's TestClient:
list and filters, one entry with its game and moves, notes, deletes, and the guards (host
check, missing database)."""

from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import chess
import pytest
from fastapi.testclient import TestClient

from blunderbook.api.app import create_app
from blunderbook.core import detect, pgn
from blunderbook.core.models import CAUSES, Color, Eval, NewBlunder, NewGame, Source
from blunderbook.db import connection, repo

FIXTURES = Path(__file__).parent / "fixtures" / "pgn"
NOW = datetime(2026, 11, 5, 9, 30, tzinfo=UTC)
BACK_RANK = "3r2k1/4qppp/8/8/8/1Q6/5PPP/2R3K1 w - - 0 32"
URL = "http://127.0.0.1"


def entry_from(
    text: str,
    ply: int,
    *,
    fingerprint: str,
    source: Source,
    me: Color,
    eval_before: Eval,
    eval_after: Eval,
    best: tuple[str, str],
    auto_causes: tuple[str, ...] = (),
    **game: Any,
) -> tuple[NewGame, NewBlunder]:
    """A game and one entry, with positions and moves read from real PGN text."""
    (parsed,) = pgn.parse(text).games
    move = parsed.plies[ply]
    new_game = NewGame(
        fingerprint=fingerprint,
        source=source,
        my_color=me,
        start_fen=parsed.start_fen,
        pgn=parsed.pgn,
        engine_name="Stockfish 17.1",
        engine_depth=16,
        white=parsed.header("White"),
        black=parsed.header("Black"),
        played_on=pgn.parse_date(parsed.header("Date")),
        result=parsed.result,
        **game,
    )
    blunder = NewBlunder(
        ply=ply,
        move_no=move.move_no,
        fen_before=move.fen_before,
        played_uci=move.uci,
        played_san=move.san,
        best_uci=best[0],
        best_san=best[1],
        best_line_san=f"{move.move_no}. {best[1]}",
        accept_uci=(best[0],),
        eval_before=eval_before,
        eval_after=eval_after,
        swing=detect.swing(eval_before, eval_after, me),
        judgment="blunder",
        refutation_san="a line",
        auto_causes=auto_causes,
    )
    return new_game, blunder


def elephant() -> tuple[NewGame, NewBlunder]:
    """6. Nxd5?? as White, 3+2 blitz on Lichess."""
    return entry_from(
        (FIXTURES / "qgd_elephant.pgn").read_text("utf-8"),
        10,
        fingerprint="fp-elephant",
        source="lichess",
        me="white",
        eval_before=Eval(cp=36),
        eval_after=Eval(cp=-409),
        best=("e2e3", "e3"),
        site_label="Lichess",
        white_elo=1512,
        black_elo=1498,
        time_control="180+2",
        tc_base_s=180,
        tc_inc_s=2,
        speed="blitz",
        opening="Queen's Gambit Declined",
        eco="D51",
        auto_causes=("Hung a piece",),
    )


def scholars() -> tuple[NewGame, NewBlunder]:
    """3... Nf6?? as Black on Chess.com, mate in 1 against me."""
    return entry_from(
        (FIXTURES / "scholars_mate.pgn").read_text("utf-8"),
        5,
        fingerprint="fp-scholars",
        source="chesscom",
        me="black",
        eval_before=Eval(cp=-32),
        eval_after=Eval(mate=1),
        best=("g7g6", "g6"),
        site_label="Chess.com",
        has_clocks=True,
        auto_causes=("Missed their threat", "Moved too fast"),
    )


def fen_entry() -> tuple[NewGame, NewBlunder]:
    """32. Rc7 from a position, against nobody named."""
    text = (
        '[Event "FEN entry"]\n[White "Rashed"]\n[Black "?"]\n'
        f'[SetUp "1"]\n[FEN "{BACK_RANK}"]\n\n32. Rc7 *'
    )
    return entry_from(
        text,
        0,
        fingerprint="fp-fen",
        source="fen",
        me="white",
        eval_before=Eval(cp=3),
        eval_after=Eval(mate=-1),
        best=("g2g3", "g3"),
        site_label="FEN entry",
        auto_causes=("Missed their threat",),
    )


@pytest.fixture
def ids(db_file: Path) -> dict[str, int]:
    """Three entries, oldest first: the Elephant, Scholar's mate, a FEN entry."""
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


def sql(db_file: Path, statement: str, *params: object) -> None:
    with closing(connection.connect(db_file)) as conn:
        conn.execute(statement, params)


def listed(client: TestClient, query: str = "") -> list[int]:
    response = client.get("/api/blunders" + query)
    assert response.status_code == 200, response.text
    return [item["id"] for item in response.json()]


# ---------------------------------------------------------------- list


def test_list_newest_first(client: TestClient, ids: dict[str, int]) -> None:
    response = client.get("/api/blunders")
    assert response.status_code == 200
    items = response.json()
    assert [item["id"] for item in items] == [ids["fen"], ids["scholars"], ids["elephant"]]
    assert items[2] == {
        "id": ids["elephant"],
        "source": "lichess",
        "my_color": "white",
        "move_no": 6,
        "played_san": "Nxd5",
        "judgment": "blunder",
        "status": "new",
        "due_on": NOW.astimezone().date().isoformat(),
        "opponent": "Karim S.",
        "played_on": "2026-10-12",
        "speed": "blitz",
        "tc_label": "3+2",
        "needs_notes": True,
    }
    assert items[1]["opponent"] == "quickmate77"  # I'm Black there
    assert items[0]["opponent"] is None  # "?" in the FEN entry
    assert items[0]["tc_label"] is None


def test_list_empty(client: TestClient, db_file: Path) -> None:
    with closing(connection.open_db(db_file, create=True)):
        pass
    assert client.get("/api/blunders").json() == []


def test_list_filters(client: TestClient, ids: dict[str, int], db_file: Path) -> None:
    change = "UPDATE blunders SET status = ?, due_on = ? WHERE id = ?"
    sql(db_file, change, "missed", "2000-01-01", ids["elephant"])
    sql(db_file, change, "solved", "2999-01-01", ids["scholars"])
    sql(db_file, change, "new", "2000-01-02", ids["fen"])
    with closing(connection.connect(db_file)) as conn:
        repo.update_notes(conn, ids["scholars"], causes=["Time trouble"])

    assert listed(client, "?source=chesscom") == [ids["scholars"]]
    assert listed(client, "?status=missed") == [ids["elephant"]]
    assert listed(client, "?status=solved&status=missed") == [ids["scholars"], ids["elephant"]]
    assert listed(client, "?due=1") == [ids["fen"], ids["elephant"]]
    assert listed(client, "?due=1&status=solved&status=missed") == [ids["elephant"]]
    # A suggestion counts only while you haven't confirmed any cause.
    assert listed(client, "?cause=Missed their threat") == [ids["fen"]]
    assert listed(client, "?cause=Time trouble") == [ids["scholars"]]
    assert listed(client, "?source=lichess&cause=Hung a piece") == [ids["elephant"]]


def test_list_by_needs_notes(client: TestClient, ids: dict[str, int], db_file: Path) -> None:
    everything = listed(client)
    assert listed(client, "?notes=missing") == everything
    assert all(item["needs_notes"] for item in client.get("/api/blunders").json())
    done = {"causes": ["Time trouble"], "lesson": "Check the clock."}
    assert client.patch(f"/api/blunders/{ids['scholars']}", json=done).status_code == 200
    assert listed(client, "?notes=missing") == [i for i in everything if i != ids["scholars"]]
    flags = {item["id"]: item["needs_notes"] for item in client.get("/api/blunders").json()}
    assert flags == {i: i != ids["scholars"] for i in everything}


@pytest.mark.parametrize(
    "query",
    ["?source=chess.com", "?status=due", "?cause=Bad luck", "?due=maybe", "?notes=done"],
)
def test_list_rejects_unknown_filters(client: TestClient, ids: dict[str, int], query: str) -> None:
    assert client.get("/api/blunders" + query).status_code == 422


# ---------------------------------------------------------------- one entry


def test_entry_with_its_game(client: TestClient, ids: dict[str, int]) -> None:
    response = client.get(f"/api/blunders/{ids['elephant']}")
    assert response.status_code == 200
    body = response.json()
    _, blunder = elephant()
    assert body["id"] == ids["elephant"]
    same = ("ply", "move_no", "fen_before", "played_uci", "played_san", "best_uci", "best_san")
    for name in (*same, "best_line_san", "refutation_san", "swing", "judgment"):
        assert body[name] == getattr(blunder, name), name
    assert body["eval_before"] == {"cp": 36}
    assert body["eval_after"] == {"cp": -409}
    assert body["auto_causes"] == ["Hung a piece"]
    assert body["causes"] == []
    assert body["other_cause"] is None
    assert (body["thinking"], body["lesson"]) == ("", "")
    assert (body["status"], body["streak"]) == ("new", 0)
    assert body["created_at"] == body["updated_at"] == "2026-11-05T09:30:00Z"
    assert "accept_uci" not in body  # the Log doesn't need it

    g = body["game"]
    assert g["white"] == "Rashed"
    assert (g["opponent"], g["my_color"], g["result"]) == ("Karim S.", "white", "0-1")
    assert (g["time_control"], g["tc_label"], g["speed"]) == ("180+2", "3+2", "blitz")
    assert (g["white_elo"], g["black_elo"]) == (1512, 1498)
    assert (g["site_label"], g["opening"], g["eco"]) == (
        "Lichess",
        "Queen's Gambit Declined",
        "D51",
    )
    assert (g["engine_name"], g["engine_depth"], g["has_clocks"]) == ("Stockfish 17.1", 16, False)
    assert "pgn" not in g and "fingerprint" not in g
    assert g["start_fen"] == chess.STARTING_FEN


def test_entry_moves_step_through_the_game(client: TestClient, ids: dict[str, int]) -> None:
    body = client.get(f"/api/blunders/{ids['elephant']}").json()
    moves = body["game"]["moves"]
    assert len(moves) == 18  # the whole game, past the blunder
    assert moves[0] == {
        "ply": 0,
        "move_no": 1,
        "color": "white",
        "san": "d4",
        "uci": "d2d4",
        "fen": "rnbqkbnr/pppppppp/8/8/3P4/8/PPP1PPPP/RNBQKBNR b KQkq - 0 1",
    }
    mine = moves[body["ply"]]
    assert (mine["uci"], mine["san"], mine["move_no"]) == ("c3d5", "Nxd5", 6)
    assert moves[body["ply"] - 1]["fen"] == body["fen_before"]
    board = chess.Board()
    for move in moves:
        board.push_uci(move["uci"])
        assert move["fen"] == board.fen()


def test_winning_chances_are_yours(client: TestClient, ids: dict[str, int]) -> None:
    white = client.get(f"/api/blunders/{ids['elephant']}").json()
    assert 0.5 < white["chances_after"] + white["swing"] == pytest.approx(white["chances_before"])
    assert white["chances_after"] < 0.2

    black = client.get(f"/api/blunders/{ids['scholars']}").json()  # cp -32 is good for Black
    assert black["chances_before"] > 0.5
    assert black["chances_after"] < 0.001  # mated next move
    assert black["chances_before"] - black["chances_after"] == pytest.approx(black["swing"])


def test_fen_entry(client: TestClient, ids: dict[str, int]) -> None:
    body = client.get(f"/api/blunders/{ids['fen']}").json()
    g = body["game"]
    assert g["start_fen"] == BACK_RANK == body["fen_before"]
    assert (g["source"], g["opponent"], g["white"]) == ("fen", None, "Rashed")
    board = chess.Board(BACK_RANK)
    board.push_uci("c1c7")
    assert g["moves"] == [
        {"ply": 0, "move_no": 32, "color": "white", "san": "Rc7", "uci": "c1c7", "fen": board.fen()}
    ]


def test_entry_whose_pgn_was_changed_by_hand(
    client: TestClient, ids: dict[str, int], db_file: Path
) -> None:
    sql(db_file, "UPDATE games SET pgn = 'not a game' WHERE fingerprint = 'fp-elephant'")
    body = client.get(f"/api/blunders/{ids['elephant']}").json()
    assert body["game"]["moves"] == []
    assert body["fen_before"]  # the blunder position still shows


def test_entry_not_found(client: TestClient, ids: dict[str, int]) -> None:
    response = client.get("/api/blunders/999")
    assert response.status_code == 404
    assert response.json() == {"detail": "No entry #999."}
    assert client.get("/api/blunders/abc").status_code == 422


# ---------------------------------------------------------------- notes


def patch(client: TestClient, blunder_id: int, body: dict[str, Any]) -> Any:
    return client.patch(f"/api/blunders/{blunder_id}", json=body)


def test_notes_are_saved_exactly(client: TestClient, ids: dict[str, int]) -> None:
    thinking = "  Thought d5 was loose.\nThe f6 knight is pinned — isn't it?  "
    response = patch(client, ids["elephant"], {"thinking": thinking})
    assert response.status_code == 200
    assert response.json()["thinking"] == thinking
    assert response.json()["updated_at"] != response.json()["created_at"]

    response = patch(client, ids["elephant"], {"lesson": "Check Bb4+ first."})
    body = client.get(f"/api/blunders/{ids['elephant']}").json()
    assert response.json() == body  # PATCH answers with the whole entry
    assert (body["thinking"], body["lesson"]) == (thinking, "Check Bb4+ first.")


def test_causes_are_kept_once_in_the_fixed_order(client: TestClient, ids: dict[str, int]) -> None:
    chosen = ["Other", "Time trouble", "Hung a piece", "Time trouble"]
    body = patch(client, ids["elephant"], {"causes": chosen, "other_cause": "Tired"}).json()
    assert body["causes"] == ["Hung a piece", "Time trouble", "Other"]
    assert body["other_cause"] == "Tired"
    assert body["auto_causes"] == ["Hung a piece"]  # suggestions never change

    body = patch(client, ids["elephant"], {"causes": [], "other_cause": ""}).json()
    assert (body["causes"], body["other_cause"]) == ([], None)


def test_fields_left_out_or_null_stay(client: TestClient, ids: dict[str, int]) -> None:
    patch(client, ids["elephant"], {"causes": ["Wrong plan"], "thinking": "a", "lesson": "b"})
    before = client.get(f"/api/blunders/{ids['elephant']}").json()
    nulls = {"causes": None, "other_cause": None, "thinking": None, "lesson": None}
    for body in ({}, nulls):
        after = patch(client, ids["elephant"], body).json()
        assert after == before


@pytest.mark.parametrize(
    "body",
    [
        {"causes": ["Hung a piece", "Bad luck"]},
        {"causes": "Hung a piece"},
        {"thinking": 5},
        {"best_uci": "c3d5"},  # the machine's part can't be changed
        {"status": "solved"},
    ],
)
def test_bad_notes_change_nothing(client: TestClient, ids: dict[str, int], body: Any) -> None:
    before = client.get(f"/api/blunders/{ids['elephant']}").json()
    response = patch(client, ids["elephant"], {"lesson": "new", **body})
    assert response.status_code == 422
    assert client.get(f"/api/blunders/{ids['elephant']}").json() == before


def test_unknown_cause_says_so(client: TestClient, ids: dict[str, int]) -> None:
    response = patch(client, ids["elephant"], {"causes": ["Bad luck"]})
    assert "Unknown cause: 'Bad luck'" in response.text


def test_every_cause_is_accepted(client: TestClient, ids: dict[str, int]) -> None:
    body = patch(client, ids["elephant"], {"causes": list(reversed(CAUSES))}).json()
    assert body["causes"] == list(CAUSES)


def test_notes_for_a_missing_entry(client: TestClient, ids: dict[str, int]) -> None:
    response = patch(client, 999, {"lesson": "x"})
    assert response.status_code == 404
    assert response.json() == {"detail": "No entry #999."}


# ---------------------------------------------------------------- delete


def test_delete_keeps_the_game(client: TestClient, ids: dict[str, int], db_file: Path) -> None:
    response = client.delete(f"/api/blunders/{ids['scholars']}")
    assert response.status_code == 204
    assert response.content == b""
    assert client.get(f"/api/blunders/{ids['scholars']}").status_code == 404
    assert listed(client) == [ids["fen"], ids["elephant"]]
    with closing(connection.connect(db_file, mode="ro")) as conn:
        assert "fp-scholars" in repo.known_fingerprints(conn)  # not imported again
    again = client.delete(f"/api/blunders/{ids['scholars']}")
    assert again.status_code == 404


# ---------------------------------------------------------------- guards


@pytest.mark.parametrize("base", ["http://127.0.0.1:8732", "http://localhost:8732"])
def test_local_hosts_are_answered(db_file: Path, ids: dict[str, int], base: str) -> None:
    with TestClient(create_app(db_file), base_url=base) as local:
        assert local.get("/api/blunders").status_code == 200


def test_other_hosts_are_refused(db_file: Path, ids: dict[str, int]) -> None:
    """A page whose domain name points at 127.0.0.1 (DNS rebinding) gets nothing."""
    with TestClient(create_app(db_file), base_url="http://evil.example:8732") as other:
        assert other.get("/api/blunders").status_code == 400
        changed = other.patch(f"/api/blunders/{ids['elephant']}", json={"lesson": "x"})
        assert changed.status_code == 400
    with closing(connection.connect(db_file, mode="ro")) as conn:
        entry = repo.get_entry(conn, ids["elephant"])
        assert entry is not None and entry.blunder.lesson == ""


def test_no_database(tmp_path: Path) -> None:
    missing = tmp_path / "nope" / "blunderbook.db"
    with TestClient(create_app(missing), base_url=URL) as no_db:
        response = no_db.get("/api/blunders")
    assert response.status_code == 503
    assert response.json()["detail"].startswith(f"Can't open {missing}")
    assert not missing.exists()  # never created by the API


def test_docs_pages_are_off(client: TestClient) -> None:
    """They load scripts from a CDN; the app stays offline."""
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
