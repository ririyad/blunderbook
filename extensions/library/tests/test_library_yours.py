"""Your entries in a Library entry's opening (ROADMAP 11.4): Log entries from games that reached
the entry's position, matched by position (so another move order counts), read-only."""

from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from blunderbook_library import routes, yours
from fastapi.testclient import TestClient
from test_library_api import client, db_file  # noqa: F401  (fixtures)

from blunderbook.core import pgn
from blunderbook.core.models import Color, Eval, NewBlunder, NewGame
from blunderbook.db import connection, repo

FIXTURES = Path(__file__).parents[3] / "tests" / "fixtures" / "pgn"
NOW = datetime(2026, 11, 8, 12, tzinfo=UTC)
# Légal's trap by another move order: 1... d6 before 2... e5 reaches the same position.
LEGAL_OTHER_ORDER = """[White "Someone"]
[Black "Rashed"]
[Date "2026.10.30"]

1. e4 d6 2. Nf3 e5 3. Bc4 Bg4 4. Nc3 g6 5. Nxe5 Bxd1 6. Bxf7+ Ke7 7. Nd5# 1-0
"""


def log(db: Path, text: str, plies: list[int], *, me: Color, at: int = 0) -> list[int]:
    """Save a game and an entry at each of ``plies`` to the Log, as an import would."""
    (parsed,) = pgn.parse(text).games
    game = NewGame(
        fingerprint=f"fp-{at}-{plies}",
        source="pgn",
        my_color=me,
        start_fen=parsed.start_fen,
        pgn=parsed.pgn,
        engine_name="Stockfish 17.1",
        engine_depth=12,
        white=parsed.header("White"),
        black=parsed.header("Black"),
        played_on=pgn.parse_date(parsed.header("Date")),
    )
    blunders = [
        NewBlunder(
            ply=i,
            move_no=parsed.plies[i].move_no,
            fen_before=parsed.plies[i].fen_before,
            played_uci=parsed.plies[i].uci,
            played_san=parsed.plies[i].san,
            best_uci="a2a3",
            best_san="a3",
            best_line_san="a3",
            accept_uci=("a2a3",),
            eval_before=Eval(cp=0),
            eval_after=Eval(cp=-500),
            swing=0.3,
            judgment="blunder",
        )
        for i in plies
    ]
    with closing(connection.open_db(db)) as conn:
        saved = repo.add_game(conn, game, blunders, now=NOW + timedelta(minutes=at))
    assert saved is not None
    return list(saved.blunder_ids)


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text("utf-8")


def mine(client: TestClient, entry_id: str) -> list[dict]:  # noqa: F811
    got = client.get(f"/api/ext/library/entries/{entry_id}/log")
    assert got.status_code == 200, got.text
    return got.json()


def test_falling_into_the_trap_in_a_game(client: TestClient, db_file: Path) -> None:  # noqa: F811
    """The §12 fixture's 5... Bxd1 is Légal's trap; its 4... g6 is on the line too."""
    g6, bxd1 = log(db_file, fixture("legal_trap.pgn"), [7, 9], me="black")
    found = mine(client, "legal-trap")  # the Log's order: one game's entries by move
    assert [(m["id"], m["move"], m["fell_in"], m["on_line"]) for m in found] == [
        (g6, "4... g6", False, True),
        (bxd1, "5... Bxd1", True, True),
    ]
    first = found[1]
    assert (first["judgment"], first["status"], first["source"]) == ("blunder", "new", "pgn")
    assert set(first) == {
        "id", "move", "judgment", "status", "source", "opponent", "played_on", "fell_in",
        "on_line",
    }  # fmt: skip


def test_each_fixture_trap_finds_its_game(client: TestClient, db_file: Path) -> None:  # noqa: F811
    """The traps written from the §12 games (11.1) each find that game's blunder."""
    games = [
        ("scholars_mate.pgn", 5, "black", "scholars-mate", "3... Nf6"),
        ("qgd_elephant.pgn", 10, "white", "elephant-trap", "6. Nxd5"),
        ("petroff_trap.pgn", 7, "black", "petrov-queen-trap", "4... Nf6"),
        ("blackburne_shilling.pgn", 8, "white", "blackburne-shilling", "5. Nxf7"),
    ]
    for at, (name, ply, me, _, _) in enumerate(games):
        log(db_file, fixture(name), [ply], me=me, at=at)
    for _, _, _, entry_id, move in games:
        found = mine(client, entry_id)
        assert [(m["move"], m["fell_in"]) for m in found] == [(move, True)], entry_id


def test_another_move_order_counts(client: TestClient, db_file: Path) -> None:  # noqa: F811
    (bxd1,) = log(db_file, LEGAL_OTHER_ORDER, [9], me="black")
    (found,) = mine(client, "legal-trap")
    assert (found["id"], found["move"], found["fell_in"]) == (bxd1, "5... Bxd1", True)
    assert (found["opponent"], found["played_on"]) == ("Someone", "2026-10-30")
    # 1... d6 2. Nf3 isn't the Philidor's own order of moves, but its position is reached.
    assert [m["id"] for m in mine(client, "philidor-defence")] == []


def test_a_game_that_left_the_line_doesn_t_count(client: TestClient, db_file: Path) -> None:  # noqa: F811
    log(db_file, fixture("legal_trap.pgn"), [9], me="black")
    assert mine(client, "petrovs-defence") == []
    assert mine(client, "back-rank-mate") == []  # a tactic from its own position


def test_newest_first_as_the_log(client: TestClient, db_file: Path) -> None:  # noqa: F811
    (older,) = log(db_file, fixture("legal_trap.pgn"), [9], me="black", at=0)
    (newer,) = log(db_file, LEGAL_OTHER_ORDER, [9], me="black", at=1)
    assert [m["id"] for m in mine(client, "legal-trap")] == [newer, older]


def test_an_empty_log(client: TestClient) -> None:  # noqa: F811
    assert mine(client, "legal-trap") == []


def test_an_unknown_entry_is_a_404(client: TestClient) -> None:  # noqa: F811
    assert client.get("/api/ext/library/entries/nope/log").status_code == 404


def test_the_log_is_only_read(client: TestClient, db_file: Path) -> None:  # noqa: F811
    log(db_file, fixture("legal_trap.pgn"), [9], me="black")
    with closing(connection.connect(db_file)) as conn:
        before = conn.execute("SELECT * FROM blunders").fetchall()
    mine(client, "legal-trap")
    with closing(connection.connect(db_file)) as conn:
        assert conn.execute("SELECT * FROM blunders").fetchall() == before


# ---------------------------------------------------------------- the matching, pure


def test_positions_are_compared_without_the_move_counters() -> None:
    a = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
    b = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 4 9"
    assert yours.key(a) == yours.key(b)
    assert yours.key(a) != yours.key(a.replace("KQkq", "Qkq"))  # castling rights count


def test_a_game_s_positions_are_read_once() -> None:
    text = fixture("legal_trap.pgn")
    (parsed,) = pgn.parse(text).games
    first = yours.game_positions(parsed.start_fen, parsed.pgn)
    assert yours.game_positions(parsed.start_fen, parsed.pgn) is first
    assert len(first) == len(parsed.plies) + 1


def test_unreadable_text_is_only_its_start() -> None:
    start = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    assert yours.game_positions(start, "") == frozenset({yours.key(start)})


@pytest.mark.parametrize("entry_id", ["legal-trap", "italian-game", "pin"])
def test_the_entries_route_still_has_no_log_in_it(client: TestClient, entry_id: str) -> None:  # noqa: F811
    """The entry page asks for your Log separately, so the entry never waits on it."""
    assert "log" not in client.get(f"/api/ext/library/entries/{entry_id}").json()
    assert routes.entries()[entry_id].id == entry_id
