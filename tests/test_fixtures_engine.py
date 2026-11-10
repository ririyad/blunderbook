"""The §12 fixtures through the whole pipeline, with real Stockfish (CLAUDE.md §12).

Fixed depth and one thread, so results don't depend on the machine. Each test asserts
which move gets flagged, never centipawn values. Where §12 names the best move, it must be
one of the moves a re-test accepts (at this depth Stockfish may rank another move first).
"""

from collections.abc import Iterator
from pathlib import Path

import pytest

from blunderbook import importer
from blunderbook.core.engine import Engine
from blunderbook.core.models import Color, Thresholds

FIXTURES = Path(__file__).parent / "fixtures" / "pgn"
DEPTH = 12
NAMES = ["Rashed"]

pytestmark = pytest.mark.engine


@pytest.fixture(scope="module")
def stockfish(stockfish_path: Path) -> Iterator[Engine]:
    """One engine for the module; each game still starts with ucinewgame."""
    with Engine.open([str(stockfish_path)], threads=1, hash_mb=64) as engine:
        yield engine


def analyse(name: str, sf: Engine, side: Color | None = None) -> importer.AnalysedGame:
    (queued,) = importer.prepare((FIXTURES / name).read_text("utf-8"), NAMES, side=side)
    assert queued.status == "ready", queued
    return importer.analyse(queued, sf, depth=DEPTH, thresholds=Thresholds())


# file, side when no name matches, expected blunder, §12 best move (UCI), required hints
CASES = [
    ("qgd_elephant.pgn", None, "6. Nxd5", "e2e3", set()),
    ("scholars_mate.pgn", None, "3... Nf6", None, {"Missed their threat"}),
    ("legal_trap.pgn", None, "5... Bxd1", "d6e5", set()),
    ("blackburne_shilling.pgn", None, "5. Nxf7", "e1g1", set()),
    ("back_rank.pgn", None, "32. Rc7", None, {"Time trouble"}),
    ("petroff_trap.pgn", None, "4... Nf6", "d8e7", set()),
    ("otb_club_no_clocks.pgn", None, "13. Nc3", "h2h3", set()),
    ("chesscom_unmatched_name.pgn", "black", "5... Ngf6", None, set()),
]


@pytest.mark.parametrize(("name", "side", "label", "best", "hints"), CASES)
def test_fixture_flags_its_blunder(
    stockfish: Engine,
    name: str,
    side: Color | None,
    label: str,
    best: str | None,
    hints: set[str],
) -> None:
    result = analyse(name, stockfish, side)
    flagged = {b.finding.ply.label: b for b in result.blunders}
    assert label in flagged, f"{name}: flagged {list(flagged)}"
    blunder = flagged[label]
    assert blunder.finding.judgment == "blunder"
    assert blunder.finding.best_uci != blunder.finding.ply.uci
    assert blunder.finding.ply.uci not in blunder.finding.accept_uci
    if best is not None:
        assert best in blunder.finding.accept_uci, blunder.finding
    assert hints <= set(blunder.hints.causes)
    assert result.analysis.engine_name.startswith("Stockfish")
    assert result.analysis.depth == DEPTH


def test_otb_game_has_no_time_hints(stockfish: Engine) -> None:
    result = analyse("otb_club_no_clocks.pgn", stockfish)
    assert result.queued.source is not None
    assert result.queued.source.source == "otb"
    for blunder in result.blunders:
        assert blunder.hints.clock_left_s is None
        assert not {"Time trouble", "Moved too fast"} & set(blunder.hints.causes)


def test_multi_game_imports_the_good_games(stockfish: Engine) -> None:
    queue = importer.prepare((FIXTURES / "multi_game.pgn").read_text("utf-8"), NAMES, side="black")
    assert [q.status for q in queue] == ["ready", "error", "ready", "ready"]
    results = [
        importer.analyse(q, stockfish, depth=DEPTH, thresholds=Thresholds())
        for q in queue
        if q.status == "ready"
    ]
    assert len(results) == 3
    assert all(r.analysis.evals for r in results)


def test_a_missed_mate_is_a_missed_win(stockfish: Engine) -> None:
    """30. Rd8# was mate; 30. h3 lets Black out with h6, and White stays far ahead, so the
    swing alone (well under an inaccuracy) wouldn't log it (§7.6)."""
    result = analyse("missed_mate.pgn", stockfish)
    (missed,) = result.blunders
    assert missed.finding.ply.label == "30. h3"
    assert missed.finding.judgment == "missed"
    assert missed.finding.swing < Thresholds().inaccuracy
    assert "d1d8" in missed.finding.accept_uci  # Rd8#
    assert "Missed my tactic" in missed.hints.causes
