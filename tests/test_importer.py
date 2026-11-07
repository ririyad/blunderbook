"""The import pipeline without Stockfish: queueing, sides, duplicates, analysis with a
scripted engine, saving, and the summary line."""

import re
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import chess
import pytest

from blunderbook import importer
from blunderbook.core.engine import EngineError, Line
from blunderbook.core.models import Batch, Eval, Thresholds
from blunderbook.db import connection, repo

FIXTURES = Path(__file__).parent / "fixtures" / "pgn"
NAMES = ["Rashed"]


def read(name: str) -> str:
    return (FIXTURES / name).read_text("utf-8")


class Scripted:
    """A stand-in engine: scores from a table keyed by FEN, cp 20 everywhere else."""

    name = "Stockfish 17.1"

    def __init__(self, table: dict[str, Line] | None = None) -> None:
        self.table = table or {}
        self.positions = 0

    def lines(
        self, board: chess.Board, depth: int, multipv: int = 1, *, game: object = None
    ) -> list[Line]:
        self.positions += 1
        return [self.table.get(board.fen(), Line(Eval(cp=20)))]


def mv(*uci: str) -> tuple[chess.Move, ...]:
    return tuple(chess.Move.from_uci(u) for u in uci)


# ---------------------------------------------------------------- prepare


def test_multi_game_queue() -> None:
    queue = importer.prepare(read("multi_game.pgn"), NAMES)
    assert [(q.number, q.status, q.side) for q in queue] == [
        (1, "ready", "white"),
        (2, "error", None),
        (3, "ready", "white"),
        (4, "needs_side", None),  # a bare move list: no players to match
    ]
    assert queue[1].reason == "Illegal move 2. Ke3"
    assert queue[1].players == "Tanvir H. vs Rashed"
    assert queue[0].source is not None
    assert queue[0].source.label == "Over the board \N{MIDDLE DOT} Dhaka Chess Club"
    assert queue[0].date == "2026-10-05"
    assert queue[3].players == "? vs ?"


def test_side_option_only_fills_unmatched_games() -> None:
    queue = importer.prepare(read("multi_game.pgn"), NAMES, side="black")
    assert [(q.number, q.status, q.side, q.side_from) for q in queue if q.game] == [
        (1, "ready", "white", "names"),  # your name still wins
        (3, "ready", "white", "names"),
        (4, "ready", "black", "option"),
    ]


def test_unmatched_name_needs_side() -> None:
    (queued,) = importer.prepare(read("chesscom_unmatched_name.pgn"), NAMES)
    assert queued.status == "needs_side"
    (queued,) = importer.prepare(read("chesscom_unmatched_name.pgn"), [*NAMES, "rashed_blitz"])
    assert (queued.status, queued.side) == ("ready", "black")


def test_both_names_matching_needs_side() -> None:
    text = '[White "Rashed"]\n[Black "rashed_blitz"]\n\n1. e4 e5 *'
    (queued,) = importer.prepare(text, ["Rashed", "rashed_blitz"])
    assert queued.status == "needs_side"


def test_already_imported_is_skipped() -> None:
    (first,) = importer.prepare(read("qgd_elephant.pgn"), NAMES)
    assert first.fingerprint is not None
    (again,) = importer.prepare(read("qgd_elephant.pgn"), NAMES, known={first.fingerprint})
    assert (again.status, again.reason) == ("duplicate", "Already imported \N{EM DASH} skipped")


def test_same_game_twice_in_one_file() -> None:
    text = read("qgd_elephant.pgn") + "\n\n" + read("qgd_elephant.pgn")
    queue = importer.prepare(text, NAMES)
    assert [q.status for q in queue] == ["ready", "duplicate"]
    assert queue[1].reason == "Same game as game 1 \N{EM DASH} skipped"


def test_duplicates_are_found_before_asking_for_a_side() -> None:
    text = read("chesscom_unmatched_name.pgn") + "\n\n" + read("chesscom_unmatched_name.pgn")
    assert [q.status for q in importer.prepare(text, NAMES)] == ["needs_side", "duplicate"]


def test_parse_warnings_reach_the_queue() -> None:
    (queued,) = importer.prepare('[White "Rashed"]\n\n1. e4 e5 2. Ke9 Nf3 *', NAMES)
    assert queued.status == "ready"
    assert queued.warnings == ("Skipped unreadable text 'Ke9' at 2.",)


def test_empty_text() -> None:
    assert importer.prepare("", NAMES) == ()


# ---------------------------------------------------------------- analyse


def legal_trap() -> tuple[importer.AnalysedGame, Scripted]:
    """legal_trap.pgn analysed with a scripted engine that flags 5... Bxd1."""
    (queued,) = importer.prepare(read("legal_trap.pgn"), NAMES)
    assert queued.game is not None
    bxd1 = queued.game.plies[9]
    engine = Scripted(
        {
            bxd1.fen_before: Line(Eval(cp=-208), mv("d6e5", "d1g4")),
            bxd1.fen_after: Line(Eval(mate=2), mv("c4f7", "e8e7", "c3d5")),
        }
    )
    return importer.analyse(queued, engine, depth=12, thresholds=Thresholds()), engine


def test_analyse_adds_hints_to_each_blunder() -> None:
    result, engine = legal_trap()
    queued = result.queued
    assert queued.game is not None
    (found,) = result.blunders
    assert found.finding.ply.label == "5... Bxd1"
    assert found.finding.best_san == "dxe5"
    assert found.hints.causes == ("Missed their threat", "Moved too fast")
    assert found.hints.time_spent_s == pytest.approx(2.6)
    assert (
        engine.positions == len(queued.game.plies) + 1
    )  # the last one is checkmate: +1 for pass 2


def test_analyse_refuses_games_that_arent_ready() -> None:
    queue = importer.prepare(read("multi_game.pgn"), NAMES)
    for queued in (queue[1], queue[3]):
        with pytest.raises(ValueError, match="isn't ready"):
            importer.analyse(queued, Scripted(), depth=8, thresholds=Thresholds())


# ---------------------------------------------------------------- records and saving


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    with closing(connection.open_db(tmp_path / "blunderbook.db", create=True)) as db:
        yield db


def test_new_game_from_headers() -> None:
    result, _ = legal_trap()
    game = importer.new_game(result)
    queued = result.queued
    assert queued.game is not None
    assert (game.fingerprint, game.pgn, game.start_fen) == (
        queued.fingerprint,
        queued.game.pgn,
        chess.STARTING_FEN,
    )
    assert (game.source, game.site_label, game.external_id) == (
        "chesscom",
        "Chess.com",
        "https://www.chess.com/game/live/140512345678",
    )
    assert (game.white, game.black, game.white_elo, game.black_elo) == (
        "kingside_kid",
        "Rashed",
        1290,
        1305,
    )
    assert (game.my_color, game.result, game.played_on) == ("black", "1-0", date(2026, 10, 30))
    assert (game.time_control, game.tc_base_s, game.tc_inc_s, game.speed) == (
        "600",
        600,
        0,
        "rapid",
    )
    assert (game.opening, game.eco, game.has_clocks) == (None, "C41", True)
    assert (game.engine_name, game.engine_depth) == ("Stockfish 17.1", 12)


def test_new_game_with_unknown_headers() -> None:
    (queued,) = importer.prepare("1. e4 e5 2. Qh5 Nc6 *", NAMES, side="white")
    result = importer.analyse(queued, Scripted(), depth=8, thresholds=Thresholds())
    game = importer.new_game(result)
    assert (game.source, game.site_label, game.external_id) == ("pgn", "PGN file", None)
    assert (game.white, game.black, game.white_elo, game.result, game.played_on) == (
        None,
        None,
        None,
        "*",  # python-chess fills in an unknown result
        None,
    )
    assert (game.time_control, game.tc_base_s, game.speed, game.has_clocks) == (
        None,
        None,
        None,
        False,
    )


def test_new_blunder_from_a_finding() -> None:
    result, _ = legal_trap()
    (found,) = result.blunders
    b = importer.new_blunder(found)
    f = found.finding
    assert (b.ply, b.move_no, b.played_san, b.played_uci) == (9, 5, "Bxd1", "g4d1")
    assert (b.fen_before, b.best_uci, b.best_san) == (f.ply.fen_before, "d6e5", "dxe5")
    assert (b.best_line_san, b.refutation_san, b.accept_uci) == (
        f.best_line_san,
        f.refutation_san,
        f.accept_uci,
    )
    assert (b.eval_before, b.eval_after, b.swing, b.judgment) == (
        Eval(cp=-208),
        Eval(mate=2),
        f.swing,
        "blunder",
    )
    assert (b.clock_left_s, b.time_spent_s) == (found.hints.clock_left_s, pytest.approx(2.6))
    assert b.auto_causes == ("Missed their threat", "Moved too fast")


def test_save_stores_the_game_and_its_entries(conn: sqlite3.Connection) -> None:
    result, _ = legal_trap()
    now = datetime(2026, 11, 5, 9, 30, tzinfo=UTC)
    saved = importer.save(conn, result, now=now)
    assert saved is not None and saved.analysed is result
    (entry,) = repo.list_entries(conn)
    assert entry.blunder.id == saved.blunder_ids[0]
    assert entry.game.id == saved.game_id
    assert entry.blunder.played_san == "Bxd1"
    assert entry.game.imported_at == now


def test_saved_games_are_skipped_next_time(conn: sqlite3.Connection) -> None:
    result, _ = legal_trap()
    assert importer.save(conn, result) is not None
    assert importer.save(conn, result) is None  # saved meanwhile: nothing written
    assert len(repo.list_entries(conn)) == 1
    (again,) = importer.prepare(read("legal_trap.pgn"), NAMES, known=repo.known_fingerprints(conn))
    assert (again.status, again.reason) == ("duplicate", importer.ALREADY_IMPORTED)


# ---------------------------------------------------------------- FEN quick entry

BACK_RANK = "3r2k1/4qppp/8/8/8/1Q6/5PPP/2R3K1 w - - 0 32"


def after(fen: str, uci: str) -> str:
    board = chess.Board(fen)
    board.push_uci(uci)
    return board.fen()


def test_prepare_fen_builds_a_one_move_game() -> None:
    queued = importer.prepare_fen(
        BACK_RANK, "c1c7", me="Rashed", opponent="endgame_eel", played_on=date(2026, 11, 1)
    )
    assert (queued.status, queued.side, queued.side_from) == ("ready", "white", "position")
    assert queued.source is not None
    assert (queued.source.source, queued.source.label) == ("fen", "FEN entry")
    assert (queued.players, queued.date) == ("Rashed vs endgame_eel", "2026-11-01")
    game = queued.game
    assert game is not None
    assert game.start_fen == BACK_RANK
    assert [p.label for p in game.plies] == ["32. Rc7"]
    assert '[SetUp "1"]' in game.pgn and f'[FEN "{BACK_RANK}"]' in game.pgn
    assert '[Event "FEN entry"]' in game.pgn


def test_prepare_fen_you_are_the_side_to_move() -> None:
    black_to_move = "6k1/5ppp/8/8/8/8/5PPP/3R2K1 b - - 0 40"
    queued = importer.prepare_fen(black_to_move, "Kf8", me="Rashed", opponent="Tanvir H.")
    assert (queued.side, queued.players) == ("black", "Tanvir H. vs Rashed")
    assert queued.game is not None and queued.game.plies[0].label == "40... Kf8"


def test_prepare_fen_takes_uci_or_san_and_promotes_to_a_queen() -> None:
    uci = importer.prepare_fen(BACK_RANK, "c1c7")
    san = importer.prepare_fen(BACK_RANK, " Rc7 ")
    assert uci.fingerprint == san.fingerprint
    promo = "8/4P3/8/8/8/8/k7/4K3 w - - 0 1"
    queen = importer.prepare_fen(promo, "e7e8")
    knight = importer.prepare_fen(promo, "e7e8n")
    assert queen.game is not None and queen.game.plies[0].uci == "e7e8q"
    assert knight.game is not None and knight.game.plies[0].uci == "e7e8n"


def test_prepare_fen_fingerprint() -> None:
    """The same position, move, opponent and date is the same entry (CLAUDE.md §7.4)."""

    def fp(**changes: object) -> str | None:
        args: dict = {"move": "c1c7", "opponent": "eel", "played_on": date(2026, 11, 1)}
        args.update(changes)
        return importer.prepare_fen(BACK_RANK, **args).fingerprint

    assert fp() == fp()
    assert len({fp(), fp(move="c1c2"), fp(opponent="pike"), fp(played_on=date(2026, 11, 2))}) == 4


def test_prepare_fen_cleans_names_for_the_pgn() -> None:
    queued = importer.prepare_fen(BACK_RANK, "c1c7", me=None, opponent=' Tanvir "TH"\n H. ')
    assert queued.players == "? vs Tanvir 'TH' H."
    assert queued.game is not None and queued.header("White") is None


@pytest.mark.parametrize(
    ("fen", "move", "message"),
    [
        ("not a fen", "e2e4", "That FEN can't be read"),
        ("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR", "e2e4", "needs the side to move"),
        ("8/8/8/8/8/8/8/K7 w - - 0 1", "a1a2", "Black has no king"),
        ("k7/8/8/8/8/8/8/K6r b - - 0 1", "h1h2", "the side not to move is in check"),
        (
            "rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3",
            "e2e4",
            "no legal moves",
        ),
        (BACK_RANK, "e1e2", "e1e2 isn't a legal move in that position. White is to move."),
        (BACK_RANK, "Rc9", "isn't a legal move"),
        (BACK_RANK, "0000", "isn't a legal move"),
        (BACK_RANK, "--", "isn't a legal move"),
        (BACK_RANK, " ", "That isn't a legal move"),
    ],
)
def test_prepare_fen_refuses(fen: str, move: str, message: str) -> None:
    with pytest.raises(importer.FenError, match=re.escape(message)):
        importer.prepare_fen(fen, move)


def test_fen_entry_logs_a_mistake_an_import_would_skip() -> None:
    queued = importer.prepare_fen(BACK_RANK, "c1c7", me="Rashed", played_on=date(2026, 11, 1))
    engine = Scripted(
        {
            BACK_RANK: Line(Eval(cp=30), mv("b3c4")),
            after(BACK_RANK, "c1c7"): Line(Eval(cp=-100), mv("e7c7")),
        }
    )
    plain = importer.analyse(queued, engine, depth=8, thresholds=Thresholds())
    assert plain.blunders == ()  # swing 0.12: under the blunder line
    result = importer.analyse(
        queued, engine, depth=8, thresholds=Thresholds(), flag_at="inaccuracy"
    )
    (found,) = result.blunders
    assert (found.finding.judgment, found.finding.best_san) == ("mistake", "Qc4")
    assert found.finding.swing == pytest.approx(0.1186, abs=1e-3)

    game = importer.new_game(result)
    assert (game.source, game.site_label, game.external_id) == ("fen", "FEN entry", None)
    assert (game.white, game.black, game.my_color) == ("Rashed", None, "white")
    assert (game.played_on, game.time_control, game.has_clocks) == (date(2026, 11, 1), None, False)
    assert game.start_fen == BACK_RANK


# ---------------------------------------------------------------- run


class Failing(Scripted):
    """Fails like a crashed engine at its ``at``-th position."""

    def __init__(self, at: int) -> None:
        super().__init__()
        self.at = at

    def lines(
        self, board: chess.Board, depth: int, multipv: int = 1, *, game: object = None
    ) -> list[Line]:
        if self.positions + 1 >= self.at:
            raise EngineError("Stockfish stopped unexpectedly.")
        return super().lines(board, depth, multipv, game=game)


def run(conn: sqlite3.Connection, analyser: Scripted, **options: Any) -> importer.RunResult:
    queue = importer.prepare(read("multi_game.pgn"), NAMES, known=repo.known_fingerprints(conn))
    return importer.run(conn, queue, analyser, depth=8, thresholds=Thresholds(), **options)


def test_run_saves_each_ready_game(conn: sqlite3.Connection) -> None:
    result = run(conn, Scripted())
    assert result.finished
    assert sorted(result.saved) == [1, 3]
    assert [q.status for q in result.queue] == ["ready", "error", "ready", "needs_side"]
    again = run(conn, Scripted())
    assert again.saved == {}
    assert [q.status for q in again.queue] == ["duplicate", "error", "duplicate", "needs_side"]


def test_run_marks_a_game_saved_meanwhile_as_a_duplicate(conn: sqlite3.Connection) -> None:
    queue = importer.prepare(read("multi_game.pgn"), NAMES)  # read before the other import
    run(conn, Scripted())
    result = importer.run(conn, queue, Scripted(), depth=8, thresholds=Thresholds())
    assert result.finished and result.saved == {}
    assert [(q.status, q.reason) for q in result.queue if q.number in (1, 3)] == [
        ("duplicate", importer.ALREADY_IMPORTED),
        ("duplicate", importer.ALREADY_IMPORTED),
    ]


def test_run_reports_progress_per_game(conn: sqlite3.Connection) -> None:
    seen: list[tuple[str, int, int, int]] = []
    closed: list[int] = []

    @contextmanager
    def progress_for(queued: importer.QueuedGame, k: int, n: int) -> Iterator[Any]:
        yield lambda done, total: seen.append(("pos", queued.number, done, total))
        closed.append(queued.number)

    run(conn, Scripted(), progress_for=progress_for)
    assert closed == [1, 3]
    for number in (1, 3):
        mine = [(done, total) for _, n, done, total in seen if n == number]
        assert mine[0][0] == 1
        assert mine[-1][0] == mine[-1][1]  # it ends at 100%


def test_run_can_stop_between_positions(conn: sqlite3.Connection) -> None:
    analyser = Scripted()
    first = importer.prepare(read("multi_game.pgn"), NAMES)[0]
    assert first.game is not None
    stop_at = len(first.game.plies) + 1 + 2  # the first game, then 2 positions of the next
    result = run(conn, analyser, should_stop=lambda: analyser.positions >= stop_at)
    assert result.stopped and not result.finished and result.error is None
    assert sorted(result.saved) == [1]  # the game being analysed isn't saved
    assert len(repo.known_fingerprints(conn)) == 1
    # Importing the same text again finishes the rest.
    assert sorted(run(conn, Scripted()).saved) == [3]


def test_run_checks_before_each_game(conn: sqlite3.Connection) -> None:
    analyser = Scripted()
    result = run(conn, analyser, should_stop=lambda: True)
    assert result.stopped and result.saved == {} and analyser.positions == 0


def test_run_keeps_the_games_before_an_engine_failure(conn: sqlite3.Connection) -> None:
    first = importer.prepare(read("multi_game.pgn"), NAMES)[0]
    assert first.game is not None
    result = run(conn, Failing(at=len(first.game.plies) + 3))
    assert result.error == "Stockfish stopped unexpectedly."
    assert not result.finished
    assert sorted(result.saved) == [1]


# ---------------------------------------------------------------- log_fen


def fen_engine(best: str, before: int, after_cp: int) -> Scripted:
    return Scripted(
        {
            BACK_RANK: Line(Eval(cp=before), mv(best)),
            after(BACK_RANK, "c1c7"): Line(Eval(cp=after_cp), mv("e7c7")),
        }
    )


def test_log_fen_logs_a_mistake(conn: sqlite3.Connection) -> None:
    queued = importer.prepare_fen(BACK_RANK, "c1c7", me="Rashed", played_on=date(2026, 11, 1))
    assert importer.find_logged(conn, queued) is None
    outcome = importer.log_fen(
        conn, queued, fen_engine("b3c4", 30, -100), depth=8, thresholds=Thresholds()
    )
    assert outcome.result == "logged"
    assert outcome.saved is not None and outcome.entry_id == outcome.saved.blunder_ids[0]
    assert outcome.message == f"Logged 32. Rc7? as a mistake: entry #{outcome.entry_id}."

    again = importer.find_logged(conn, queued)
    assert again is not None
    assert (again.result, again.entry_id) == ("already_logged", outcome.entry_id)
    assert again.message == (
        f"You've already logged 32. Rc7 in this position (entry #{outcome.entry_id})."
        " Nothing was added."
    )


def test_log_fen_skips_stockfishs_own_choice(conn: sqlite3.Connection) -> None:
    queued = importer.prepare_fen(BACK_RANK, "c1c7", played_on=date(2026, 11, 1))
    outcome = importer.log_fen(
        conn, queued, fen_engine("c1c7", 30, -100), depth=8, thresholds=Thresholds()
    )
    assert outcome == importer.FenOutcome(
        "best_move", "32. Rc7 is Stockfish's own choice here. Nothing was logged."
    )
    assert importer.find_logged(conn, queued) is None


def test_log_fen_skips_a_move_under_the_inaccuracy_line(conn: sqlite3.Connection) -> None:
    queued = importer.prepare_fen(BACK_RANK, "c1c7", played_on=date(2026, 11, 1))
    outcome = importer.log_fen(
        conn, queued, fen_engine("b3c4", 30, 25), depth=8, thresholds=Thresholds()
    )
    assert outcome.result == "not_a_mistake"
    assert outcome.message.startswith("32. Rc7 isn't a mistake by Stockfish's measure (swing 0.00")
    assert outcome.message.endswith("inaccuracies start at 0.05). Nothing was logged.")
    assert outcome.saved is None and outcome.entry_id is None


# ---------------------------------------------------------------- summary


def test_summary_line() -> None:
    elephant = read("qgd_elephant.pgn")
    text = "\n\n".join([read("multi_game.pgn"), elephant, elephant])
    queue = importer.prepare(text, NAMES)
    assert importer.summary(queue, []) == (
        "6 games read \N{MIDDLE DOT} 1 skipped (duplicate) \N{MIDDLE DOT} 1 needs side "
        "\N{MIDDLE DOT} 1 error \N{MIDDLE DOT} 0 blunders added"
    )


def test_summary_line_counts_blunders_and_plurals() -> None:
    (queued,) = importer.prepare(read("qgd_elephant.pgn"), NAMES)
    assert queued.game is not None
    nxd5 = queued.game.plies[10]
    engine = Scripted(
        {
            nxd5.fen_before: Line(Eval(cp=36), mv("e2e3")),
            nxd5.fen_after: Line(Eval(cp=-409), mv("f6d5")),
        }
    )
    result = importer.analyse(queued, engine, depth=8, thresholds=Thresholds())
    saved = importer.SavedGame(result, game_id=1, blunder_ids=(7,))
    assert importer.summary([queued], [saved]) == "1 game read \N{MIDDLE DOT} 1 blunder added"
    two = importer.prepare('[White "A"]\n\n1. e4 *\n\n[White "B"]\n\n1. d4 *', NAMES)
    assert "2 need side" in importer.summary(two, [])


# ---------------------------------------------------------------- imports (Games tab)


def imports(conn: sqlite3.Connection) -> list[tuple[str, str, int]]:
    """Each saved import: its label, kind and how many games it holds."""
    return [
        tuple(row)
        for row in conn.execute(
            "SELECT i.label, i.kind, count(g.id) FROM imports AS i "
            "LEFT JOIN games AS g ON g.import_id = i.id GROUP BY i.id ORDER BY i.id"
        )
    ]


def test_run_remembers_its_import(conn: sqlite3.Connection) -> None:
    run(conn, Scripted(), batch=importer.file_batch("multi_game.pgn"))
    assert imports(conn) == [("multi_game.pgn", "file", 2)]


def test_an_import_that_adds_nothing_isnt_remembered(conn: sqlite3.Connection) -> None:
    run(conn, Scripted(), batch=importer.file_batch("multi_game.pgn"))
    run(conn, Scripted(), batch=importer.file_batch("multi_game.pgn"))  # all duplicates
    assert imports(conn) == [("multi_game.pgn", "file", 2)]


def test_without_a_batch_games_have_no_import(conn: sqlite3.Connection) -> None:
    run(conn, Scripted())
    assert imports(conn) == []
    assert conn.execute("SELECT count(*) FROM games WHERE import_id IS NULL").fetchone()[0] == 2


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("blitz-week.pgn", ("blitz-week.pgn", "file")),
        ("C:\\Users\\Rashed\\Downloads\\club.pgn", ("club.pgn", "file")),
        ("/home/rashed/games/open 2026.pgn", ("open 2026.pgn", "file")),
        ("  two\tspaces\n.pgn ", ("two spaces .pgn", "file")),
        ("bell\x07.pgn", ("bell.pgn", "file")),
        ("x" * 300, ("x" * 200, "file")),
        ("", (importer.PASTED, "paste")),
        (None, (importer.PASTED, "paste")),
        ("folder/", (importer.PASTED, "paste")),
    ],
)
def test_file_batch(name: str | None, expected: tuple[str, str]) -> None:
    batch = importer.file_batch(name)
    assert (batch.label, batch.kind) == expected


def test_sync_batch() -> None:
    assert importer.sync_batch("Chess.com") == Batch("Chess.com sync", "sync")
