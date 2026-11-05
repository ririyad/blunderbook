"""The import pipeline without Stockfish: queueing, sides, duplicates, analysis with a
scripted engine, and the summary line."""

from pathlib import Path

import chess
import pytest

from blunderbook import importer
from blunderbook.core.engine import Line
from blunderbook.core.models import Eval, Thresholds

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


def test_analyse_adds_hints_to_each_blunder() -> None:
    (queued,) = importer.prepare(read("legal_trap.pgn"), NAMES)
    assert queued.game is not None
    bxd1 = queued.game.plies[9]
    engine = Scripted(
        {
            bxd1.fen_before: Line(Eval(cp=-208), mv("d6e5", "d1g4")),
            bxd1.fen_after: Line(Eval(mate=2), mv("c4f7", "e8e7", "c3d5")),
        }
    )
    result = importer.analyse(queued, engine, depth=12, thresholds=Thresholds())
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


# ---------------------------------------------------------------- summary


def test_summary_line() -> None:
    elephant = read("qgd_elephant.pgn")
    text = "\n\n".join([read("multi_game.pgn"), elephant, elephant])
    queue = importer.prepare(text, NAMES)
    assert importer.summary(queue, [], "found") == (
        "6 games read \N{MIDDLE DOT} 1 skipped (duplicate) \N{MIDDLE DOT} 1 needs side "
        "\N{MIDDLE DOT} 1 error \N{MIDDLE DOT} 0 blunders found"
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
    assert importer.summary([queued], [result], "added") == (
        "1 game read \N{MIDDLE DOT} 1 blunder added"
    )
    two = importer.prepare('[White "A"]\n\n1. e4 *\n\n[White "B"]\n\n1. d4 *', NAMES)
    assert "2 need side" in importer.summary(two, [], "found")
