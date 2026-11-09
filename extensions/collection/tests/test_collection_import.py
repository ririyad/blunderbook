"""Adding games to a collection (ROADMAP 12.1): queueing, pass 1 for every position, what's
kept of the headers, collection.db, and what happens when the engine stops."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import chess
import pytest
from blunderbook_collection import collect, extension, games, store
from collection_fakes import (  # noqa: F401  (fixtures)
    CLASSICS,
    FakeEngine,
    cfg_file,
    fake,
    no_engine,
)

from blunderbook import config, ext, host
from blunderbook.core.models import Eval

TEXT = CLASSICS.read_text("utf-8")
LEGAL = "[Event" + TEXT.split("\n\n[Event")[1]


def db() -> sqlite3.Connection:
    return host.open_db(extension)


def run(conn: sqlite3.Connection, text: str, name: str, engine: object) -> collect.Result:
    queued = collect.queue(conn, text, name)
    return collect.add(conn, name, queued, engine, depth=8)  # type: ignore[arg-type]


# ---------------------------------------------------------------- names


@pytest.mark.parametrize(
    ("value", "name"), [("Classics", "Classics"), ("  Model   games ", "Model games")]
)
def test_a_name_is_trimmed(value: str, name: str) -> None:
    assert games.collection_name(value) == name


@pytest.mark.parametrize(
    ("value", "problem"),
    [
        ("   ", "Give the collection a name."),
        ("x" * 61, "A collection's name can be at most 60 characters."),
        ("Tab\x07", "A collection's name can't have control characters."),
    ],
)
def test_a_bad_name(value: str, problem: str) -> None:
    with pytest.raises(games.BadName, match=problem):
        games.collection_name(value)


# ---------------------------------------------------------------- the queue


def test_every_game_is_queued_in_file_order() -> None:
    queued = games.prepare(TEXT, collection="Classics")
    assert [(q.number, q.status) for q in queued] == [
        (1, "ready"),
        (2, "ready"),
        (3, "error"),
        (4, "duplicate"),
    ]
    assert queued[2].reason == "Illegal move 2. Ke3"
    assert queued[3].reason == "Same game as game 1 \N{EM DASH} skipped"
    assert queued[0].players == "Paul Morphy vs Duke Karl / Count Isouard"


def test_known_games_and_members() -> None:
    first = games.prepare(TEXT, collection="Classics")
    morphy, legal = first[0].fingerprint, first[1].fingerprint
    assert morphy is not None and legal is not None
    again = games.prepare(TEXT, collection="Classics", analysed={morphy, legal}, members={morphy})
    assert [q.status for q in again] == ["member", "known", "error", "duplicate"]
    assert again[0].reason == "Already in Classics \N{EM DASH} skipped"


def test_nobody_needs_a_side() -> None:
    queued = games.prepare("1. e4 e5 2. Nf3 Nc6 *", collection="Bare")
    assert [q.status for q in queued] == ["ready"]
    assert queued[0].players == "? vs ?"


# ---------------------------------------------------------------- pass 1 and the headers


def test_every_position_is_scored_once() -> None:
    game = games.prepare(TEXT, collection="C")[0].game
    assert game is not None
    engine = FakeEngine()
    seen: list[tuple[int, int]] = []
    scored = games.score(game, engine, depth=8, progress=lambda d, t: seen.append((d, t)))
    n = len(game.plies)
    assert [p.ply for p in scored] == list(range(n + 1))
    assert scored[0].fen == chess.STARTING_FEN and scored[0].move_uci is None
    assert (scored[1].move_san, scored[1].move_uci) == ("e4", "e2e4")
    assert scored[1].fen == game.plies[0].fen_after
    assert scored[1].score == Eval(cp=20)
    assert len(scored[1].pv_uci) == games.PV_PLIES  # the line is cut to 10 plies
    assert scored[1].best_uci == scored[1].pv_uci[0]
    last = scored[-1]  # 17. Rd8# is mate: not sent to the engine
    assert (last.move_san, last.score, last.best_uci, last.pv_uci) == (
        "Rd8#",
        Eval(mate=0),
        None,
        (),
    )
    assert len(engine.calls) == n  # every position but the mate
    assert seen[-1] == (n + 1, n + 1)


def test_what_is_kept_of_the_headers() -> None:
    queued = games.prepare(TEXT, collection="C")
    opera = games.info(queued[0])
    assert (opera.white, opera.black, opera.result) == (
        "Paul Morphy",
        "Duke Karl / Count Isouard",
        "1-0",
    )
    assert (opera.date, opera.played_on, opera.round) == ("1858.??.??", None, None)
    assert (opera.event, opera.site, opera.eco, opera.opening) == (
        "Paris",
        "Paris FRA",
        "C41",
        "Philidor Defence",
    )
    assert (opera.source, opera.site_label) == ("otb", "Over the board \N{MIDDLE DOT} Paris FRA")
    assert (opera.white_elo, opera.time_control, opera.speed) == (None, None, None)
    assert opera.plies == 33
    assert opera.pgn.startswith('[Event "Paris"]') and opera.pgn.endswith("17. Rd8# 1-0")


def test_a_time_control_and_ratings() -> None:
    text = (
        '[White "Ann"]\n[Black "Bo"]\n[WhiteElo "1820"]\n[BlackElo "?"]\n'
        '[TimeControl "180+2"]\n[Date "2026.11.02"]\n[Result "0-1"]\n\n1. f3 e5 2. g4 Qh4# 0-1'
    )
    got = games.info(games.prepare(text, collection="C")[0])
    assert (got.white_elo, got.black_elo) == (1820, None)
    assert (got.tc_base_s, got.tc_inc_s, got.speed) == (180, 2, "blitz")
    assert (got.date, got.played_on) == ("2026.11.02", "2026-11-02")


# ---------------------------------------------------------------- collection.db


def test_games_are_saved_with_every_position(fake: FakeEngine) -> None:
    with closing(db()) as conn:
        result = run(conn, TEXT, "Classics", fake)
        assert result.error is None and result.created
        assert sorted(result.added) == [1, 2]
        (found,) = store.collections(conn)
        assert (found.name, found.games) == ("Classics", 2)
        rows = store.games(conn, found.id)
        assert [(g.white, g.plies, g.engine_name, g.engine_depth) for g in rows] == [
            ("Paul Morphy", 33, "Stockfish 17.1", 8),
            ("Kermur de Legal", 13, "Stockfish 17.1", 8),
        ]
        kept = store.positions(conn, rows[1].id)
        assert len(kept) == 14
        assert kept[10].move_san == "Bxd1"
        assert kept[-1].score == Eval(mate=0)
        raw = conn.execute("SELECT eval FROM positions WHERE ply = 1 LIMIT 1").fetchone()[0]
        assert json.loads(raw) == {"cp": 20}
    assert fake.opened == fake.closed == 1  # one engine for the whole import


def test_the_same_file_again_adds_nothing(fake: FakeEngine) -> None:
    with closing(db()) as conn:
        run(conn, TEXT, "Classics", fake)
        calls = len(fake.calls)
        again = run(conn, TEXT, "classics", fake)  # any case
        assert again.added == {} and not again.created
        assert [q.status for q in again.queue] == ["member", "member", "error", "duplicate"]
        assert len(fake.calls) == calls and fake.opened == 1  # no engine needed
        assert [c.games for c in store.collections(conn)] == [2]


def test_a_game_in_two_collections_is_analysed_once(fake: FakeEngine) -> None:
    with closing(db()) as conn:
        run(conn, TEXT, "Classics", fake)
        calls = len(fake.calls)
        other = run(conn, LEGAL, "Traps", fake)
        assert other.created and list(other.added) == [1]
        assert [q.status for q in other.queue] == ["known"]
        assert len(fake.calls) == calls and fake.opened == 1
        assert [(c.name, c.games) for c in store.collections(conn)] == [
            ("Classics", 2),
            ("Traps", 1),
        ]
        assert conn.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 2


def test_nothing_added_leaves_no_collection(fake: FakeEngine) -> None:
    broken = '[White "A"]\n[Black "B"]\n\n1. e4 e5 2. Ke3 *'
    with closing(db()) as conn:
        result = run(conn, broken, "Empty", fake)
        assert result.collection_id is None and not result.created
        assert store.collections(conn) == []
    assert fake.opened == 0


def test_when_the_engine_stops_the_games_before_are_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = FakeEngine(fail_on=40)  # in the second game: the first has 33 to score
    with closing(db()) as conn:
        result = run(conn, TEXT, "Classics", engine)
        assert result.error == "Stockfish stopped unexpectedly."
        assert list(result.added) == [1]
        assert [c.games for c in store.collections(conn)] == [1]
        assert conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0] == 34
        finish = run(conn, TEXT, "Classics", FakeEngine())
        assert list(finish.added) == [2]
    assert engine.closed == 1


def test_ctrl_c_keeps_the_games_before(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = FakeEngine(fail_on=40, interrupt=True)
    with closing(db()) as conn:
        result = run(conn, TEXT, "Classics", engine)
        assert result.stopped and result.error is None
        assert list(result.added) == [1]
    assert engine.closed == 1


def test_no_stockfish_still_adds_known_games(fake: FakeEngine, no_engine: None) -> None:
    with closing(db()) as conn:
        run(conn, LEGAL, "Traps", fake)
        both = run(conn, TEXT, "Classics", host.engine)
        assert both.error == "Can't analyse: Stockfish wasn't found."
        assert list(both.added) == [2]  # Légal's game, analysed before
        assert [c.games for c in store.collections(conn)] == [1, 1]


def test_collection_db_is_its_own(fake: FakeEngine, cfg_file: Path) -> None:
    with closing(db()) as conn:
        run(conn, TEXT, "Classics", fake)
    path = ext.db_path(extension)
    assert path == config.db_path().parent / "collection.db"
    assert not config.db_path().exists()  # your Log isn't touched


def test_only_the_host_api_is_used() -> None:
    package = Path(games.__file__).parent
    assert ext.boundary_problems(package) == []
