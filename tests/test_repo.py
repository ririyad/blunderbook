"""db/repo.py against a real temp database: round trips, dedupe, the Log's filters and
order, notes, and deletes."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from dataclasses import fields, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import chess
import pytest

from blunderbook.core.models import Eval, NewBlunder, NewGame
from blunderbook.db import connection, repo

NOW = datetime(2026, 11, 5, 9, 30, tzinfo=UTC)
LATER = NOW + timedelta(minutes=5)
TODAY = NOW.astimezone().date()  # entries are due on the local date


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with closing(connection.open_db(tmp_path / "blunderbook.db", create=True)) as db:
        yield db


def new_game(**changes: object) -> NewGame:
    game = NewGame(
        fingerprint="fp-elephant",
        source="lichess",
        my_color="white",
        start_fen=chess.STARTING_FEN,
        pgn='[White "Rashed"]\n\n1. d4 d5 2. c4 e6 *',
        engine_name="Stockfish 17.1",
        engine_depth=16,
        site_label="Lichess",
        external_id="abcd1234",
        white="Rashed",
        black="Tanvir H.",
        white_elo=1512,
        black_elo=1498,
        result="0-1",
        played_on=date(2026, 10, 5),
        time_control="180+2",
        tc_base_s=180,
        tc_inc_s=2,
        speed="blitz",
        opening="Queen's Gambit Declined: Elephant Trap",
        eco="D51",
        has_clocks=True,
    )
    return replace(game, **changes)


def new_blunder(**changes: object) -> NewBlunder:
    blunder = NewBlunder(
        ply=10,
        move_no=6,
        fen_before="r1bqkb1r/pppn1ppp/5n2/3p2B1/3P4/2N5/PP2PPPP/R2QKBNR w KQkq - 0 6",
        played_uci="c3d5",
        played_san="Nxd5",
        best_uci="e2e3",
        best_san="e3",
        best_line_san="6. e3 Be7 7. Bd3 c6 8. Nf3 O-O",
        accept_uci=("e2e3", "g1f3"),
        eval_before=Eval(cp=36),
        eval_after=Eval(cp=-409),
        swing=0.39,
        judgment="blunder",
        refutation_san="6... Nxd5 7. Bxd8 Bb4+ 8. Qd2 Bxd2+",
        clock_left_s=95.5,
        time_spent_s=1.2,
        auto_causes=("Moved too fast",),
    )
    return replace(blunder, **changes)


def same_fields(stored: object, new: NewGame | NewBlunder) -> None:
    """Everything the import wrote comes back unchanged."""
    for f in fields(new):
        assert getattr(stored, f.name) == getattr(new, f.name), f.name


def ids(entries: list) -> list[int]:
    return [e.blunder.id for e in entries]


# ---------------------------------------------------------------- games


def test_game_round_trip(conn: sqlite3.Connection) -> None:
    game = new_game()
    game_id = repo.add_game(conn, game, now=NOW)
    assert game_id is not None
    stored = repo.get_game(conn, game_id)
    assert stored is not None
    same_fields(stored, game)
    assert (stored.id, stored.analysis_status, stored.imported_at) == (game_id, "done", NOW)


def test_game_with_unknown_headers(conn: sqlite3.Connection) -> None:
    game = NewGame(
        fingerprint="fp-bare",
        source="pgn",
        my_color="black",
        start_fen="3r2k1/4qppp/8/8/8/1Q6/5PPP/2R3K1 w - - 0 32",
        pgn="1. Rc7 *",
        engine_name="Stockfish 19",
        engine_depth=12,
    )
    game_id = repo.add_game(conn, game, now=NOW)
    assert game_id is not None
    stored = repo.get_game(conn, game_id)
    assert stored is not None
    same_fields(stored, game)
    assert (stored.white, stored.played_on, stored.speed, stored.has_clocks) == (
        None,
        None,
        None,
        False,
    )


def test_game_with_no_blunders_is_saved_so_its_skipped_next_time(
    conn: sqlite3.Connection,
) -> None:
    assert repo.add_game(conn, new_game(), now=NOW) is not None
    assert repo.known_fingerprints(conn) == {"fp-elephant"}
    assert repo.list_entries(conn) == []


def test_same_fingerprint_writes_nothing(conn: sqlite3.Connection) -> None:
    first = repo.add_game(conn, new_game(), [new_blunder()], now=NOW)
    again = repo.add_game(
        conn, new_game(white="Someone else"), [new_blunder(), new_blunder(ply=20)], now=LATER
    )
    assert first is not None and again is None
    assert len(repo.list_entries(conn)) == 1
    stored = repo.get_game(conn, first)
    assert stored is not None and stored.white == "Rashed"
    assert not conn.in_transaction


def test_a_failed_write_saves_nothing(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        repo.add_game(conn, new_game(), [new_blunder(), new_blunder()], now=NOW)  # same ply
    assert repo.known_fingerprints(conn) == set()
    assert not conn.in_transaction


def test_missing_rows(conn: sqlite3.Connection) -> None:
    assert repo.get_game(conn, 99) is None
    assert repo.get_entry(conn, 99) is None


def test_now_must_carry_a_time_zone(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        repo.add_game(conn, new_game(), now=datetime(2026, 11, 5, 9, 30))


# ---------------------------------------------------------------- entries


def test_blunders_round_trip_with_defaults(conn: sqlite3.Connection) -> None:
    mate = new_blunder(
        ply=30,
        move_no=16,
        eval_before=Eval(mate=3),
        eval_after=Eval(mate=0),
        refutation_san=None,
        clock_left_s=None,
        time_spent_s=None,
        auto_causes=(),
        judgment="mistake",
    )
    game_id = repo.add_game(conn, new_game(), [new_blunder(), mate], now=NOW)
    entries = repo.list_entries(conn)
    assert len(entries) == 2
    for entry, new in zip(entries, [new_blunder(), mate], strict=True):
        b = entry.blunder
        same_fields(b, new)
        assert b.game_id == entry.game.id == game_id
        assert (b.causes, b.other_cause, b.thinking, b.lesson) == ((), None, "", "")
        assert (b.status, b.streak, b.due_on) == ("new", 0, TODAY)
        assert b.created_at == b.updated_at == NOW
        assert repo.get_entry(conn, b.id) == entry


def test_evals_and_lists_are_stored_as_spec_json(conn: sqlite3.Connection) -> None:
    repo.add_game(conn, new_game(), [new_blunder(eval_after=Eval(mate=-2))], now=NOW)
    row = conn.execute("SELECT eval_before, eval_after, accept_uci, auto_causes FROM blunders")
    assert tuple(row.fetchone()) == (
        '{"cp":36}',
        '{"mate":-2}',
        '["e2e3","g1f3"]',
        '["Moved too fast"]',
    )


@pytest.fixture
def log(conn: sqlite3.Connection) -> dict[str, int]:
    """Three entries in two games. Returns their ids by name."""
    repo.add_game(
        conn,
        new_game(),
        [
            new_blunder(ply=10, auto_causes=("Moved too fast",)),
            new_blunder(ply=14, auto_causes=("Hung a piece",)),
        ],
        now=NOW,
    )
    repo.add_game(
        conn,
        new_game(fingerprint="fp-club", source="otb", played_on=date(2026, 10, 20)),
        [new_blunder(ply=24, auto_causes=("Hung a piece",))],
        now=LATER,
    )
    a1, a2, b1 = sorted(row[0] for row in conn.execute("SELECT id FROM blunders"))
    return {"a1": a1, "a2": a2, "b1": b1}


def test_log_order_newest_first_then_move_order(conn: sqlite3.Connection, log: dict) -> None:
    assert ids(repo.list_entries(conn)) == [log["b1"], log["a1"], log["a2"]]


def test_same_import_orders_by_game_date(conn: sqlite3.Connection) -> None:
    for fp, played in [("g1", date(2026, 10, 1)), ("g2", None), ("g3", date(2026, 10, 5))]:
        repo.add_game(conn, new_game(fingerprint=fp, played_on=played), [new_blunder()], now=NOW)
    assert [e.game.fingerprint for e in repo.list_entries(conn)] == ["g3", "g1", "g2"]


def test_filter_by_source(conn: sqlite3.Connection, log: dict) -> None:
    assert ids(repo.list_entries(conn, source="otb")) == [log["b1"]]
    assert ids(repo.list_entries(conn, source="chesscom")) == []


def test_filter_by_cause_uses_suggestions_until_you_confirm(
    conn: sqlite3.Connection, log: dict
) -> None:
    assert ids(repo.list_entries(conn, cause="Hung a piece")) == [log["b1"], log["a2"]]
    repo.update_notes(conn, log["a2"], causes=["Time trouble"])
    assert ids(repo.list_entries(conn, cause="Hung a piece")) == [log["b1"]]
    assert ids(repo.list_entries(conn, cause="Time trouble")) == [log["a2"]]
    assert ids(repo.list_entries(conn, cause="Moved too fast")) == [log["a1"]]
    with pytest.raises(ValueError, match="Unknown cause"):
        repo.list_entries(conn, cause="Bad luck")


def test_filter_by_status_and_due_date(conn: sqlite3.Connection, log: dict) -> None:
    tomorrow = (TODAY + timedelta(days=1)).isoformat()
    conn.execute(
        "UPDATE blunders SET status = 'missed', due_on = ? WHERE id = ?", (tomorrow, log["a1"])
    )
    conn.execute("UPDATE blunders SET status = 'solved' WHERE id = ?", (log["b1"],))
    assert ids(repo.list_entries(conn, statuses=["missed"])) == [log["a1"]]
    assert ids(repo.list_entries(conn, statuses={"new", "solved"})) == [log["b1"], log["a2"]]
    assert ids(repo.list_entries(conn, due_by=TODAY)) == [log["b1"], log["a2"]]
    due_again = repo.list_entries(conn, statuses=("solved", "missed"), due_by=TODAY)
    assert ids(due_again) == [log["b1"]]


# ---------------------------------------------------------------- notes


def test_update_changes_only_the_fields_given(conn: sqlite3.Connection, log: dict) -> None:
    entry = repo.update_notes(conn, log["a1"], thinking="I thought the knight was safe.", now=LATER)
    assert entry is not None
    b = entry.blunder
    assert b.thinking == "I thought the knight was safe."
    assert (b.lesson, b.causes, b.other_cause) == ("", (), None)
    assert (b.created_at, b.updated_at) == (NOW, LATER)
    entry = repo.update_notes(conn, log["a1"], lesson="Check what each capture leaves hanging.")
    assert entry is not None
    assert entry.blunder.thinking == "I thought the knight was safe."


def test_text_is_kept_exactly(conn: sqlite3.Connection, log: dict) -> None:
    text = "  Missed ♘d5 — the pin.\nNext time:  "
    entry = repo.update_notes(conn, log["a1"], thinking=text, lesson=text)
    assert entry is not None
    assert (entry.blunder.thinking, entry.blunder.lesson) == (text, text)


def test_causes_are_stored_once_in_the_fixed_order(conn: sqlite3.Connection, log: dict) -> None:
    entry = repo.update_notes(conn, log["a1"], causes=["Other", "Hung a piece", "Other"])
    assert entry is not None
    assert entry.blunder.causes == ("Hung a piece", "Other")
    entry = repo.update_notes(conn, log["a1"], causes=[])
    assert entry is not None
    assert entry.blunder.causes == ()


def test_unknown_cause_changes_nothing(conn: sqlite3.Connection, log: dict) -> None:
    with pytest.raises(ValueError, match="Unknown cause: 'Bad luck'"):
        repo.update_notes(conn, log["a1"], causes=["Hung a piece", "Bad luck"], thinking="x")
    entry = repo.get_entry(conn, log["a1"])
    assert entry is not None
    assert (entry.blunder.causes, entry.blunder.thinking) == ((), "")


def test_other_cause_set_kept_and_cleared(conn: sqlite3.Connection, log: dict) -> None:
    entry = repo.update_notes(conn, log["a1"], other_cause="Phone rang")
    assert entry is not None and entry.blunder.other_cause == "Phone rang"
    entry = repo.update_notes(conn, log["a1"], thinking="kept")
    assert entry is not None and entry.blunder.other_cause == "Phone rang"
    entry = repo.update_notes(conn, log["a1"], other_cause="")
    assert entry is not None and entry.blunder.other_cause is None


def test_update_with_nothing_to_change(conn: sqlite3.Connection, log: dict) -> None:
    before = repo.get_entry(conn, log["a1"])
    assert repo.update_notes(conn, log["a1"], now=LATER) == before
    assert repo.update_notes(conn, 999, thinking="x") is None


# ---------------------------------------------------------------- delete


def test_delete_an_entry(conn: sqlite3.Connection, log: dict) -> None:
    conn.execute(
        "INSERT INTO retest_attempts (blunder_id, attempted_at, solved) VALUES (?, ?, 0)",
        (log["a1"], NOW.isoformat()),
    )
    assert repo.delete_blunder(conn, log["a1"]) is True
    assert repo.get_entry(conn, log["a1"]) is None
    assert repo.delete_blunder(conn, log["a1"]) is False
    assert conn.execute("SELECT count(*) FROM retest_attempts").fetchone()[0] == 0
    assert "fp-elephant" in repo.known_fingerprints(conn)  # importing it again is skipped
    assert ids(repo.list_entries(conn)) == [log["b1"], log["a2"]]
