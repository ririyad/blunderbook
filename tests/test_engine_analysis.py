"""Engine wrapper and the two analysis passes (CLAUDE.md §7.6).

Most tests use a scripted analyser (pure Python) or the fake UCI engine in
tests/fixtures/fake_uci.py, so they run without Stockfish. The ``engine`` tests at the
end use the real one.
"""

import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path

import chess
import chess.engine
import pytest

from blunderbook.core import pgn
from blunderbook.core.engine import (
    MULTIPV,
    Engine,
    EngineError,
    EngineInfo,
    EngineTimeout,
    Line,
    analyse_game,
    score_positions,
    terminal_line,
)
from blunderbook.core.models import Eval, ParsedGame, Thresholds

FIXTURES = Path(__file__).parent / "fixtures" / "pgn"
FakeEngine = Callable[..., list[str]]
TH = Thresholds()


def fixture(name: str) -> ParsedGame:
    return pgn.parse((FIXTURES / name).read_text("utf-8")).games[0]


def mv(*uci: str) -> tuple[chess.Move, ...]:
    return tuple(chess.Move.from_uci(u) for u in uci)


class Scripted:
    """An analyser answering from tables keyed by FEN. Records every call."""

    name = "Stockfish 17.1"

    def __init__(
        self,
        pass1: dict[str, Line] | None = None,
        multi: dict[str, list[Line]] | None = None,
        default: Line | None = None,
        fail_on: int = 0,
    ) -> None:
        self.pass1 = pass1 or {}
        self.multi = multi or {}
        self.default = default or Line(Eval(cp=20))
        self.fail_on = fail_on
        self.calls: list[tuple[str, int, int, object]] = []
        self.alone: list[tuple[str, int, str, object]] = []  # searches of one move (21.3)

    def lines(
        self,
        board: chess.Board,
        depth: int,
        multipv: int = 1,
        *,
        game: object = None,
        root_moves: Sequence[chess.Move] | None = None,
    ) -> list[Line]:
        if root_moves:  # one move alone: the position after it, as pass 1 scores it
            move = root_moves[0]
            self.alone.append((board.fen(), depth, move.uci(), game))
            after = board.copy()
            after.push(move)
            line = self.pass1.get(after.fen(), self.default)
            return [Line(line.score, (move, *line.pv))]
        self.calls.append((board.fen(), depth, multipv, game))
        if len(self.calls) == self.fail_on:
            raise EngineError("Stockfish stopped unexpectedly.")
        fen = board.fen()
        if multipv > 1 and fen in self.multi:
            return self.multi[fen][:multipv]
        return [self.pass1.get(fen, self.default)]


# ---------------------------------------------------------------- QGD Elephant trap, White


def qgd_script() -> tuple[ParsedGame, Scripted]:
    game = fixture("qgd_elephant.pgn")
    nxd5 = game.plies[10]
    script = Scripted(
        pass1={
            nxd5.fen_before: Line(Eval(cp=36), mv("e2e3", "f8e7", "f1d3", "c7c6", "h2h3", "d7f8")),
            nxd5.fen_after: Line(Eval(cp=-409), mv("f6d5", "g5d8", "f8b4", "d1d2", "b4d2", "e1d2")),
        },
        multi={
            nxd5.fen_before: [
                Line(Eval(cp=36), mv("e2e3")),
                Line(Eval(cp=20), mv("g1f3")),  # 16 below the best: accepted
                Line(Eval(cp=-30), mv("a2a3")),  # 66 below the best: not accepted
            ]
        },
    )
    return game, script


def test_flags_the_blunder_with_everything_filled_in() -> None:
    game, script = qgd_script()
    result = analyse_game(game, "white", script, depth=16, thresholds=TH)

    assert (result.engine_name, result.depth) == ("Stockfish 17.1", 16)
    assert len(result.evals) == len(game.plies) + 1
    (finding,) = result.findings
    assert finding.ply.label == "6. Nxd5"
    assert (finding.eval_before, finding.eval_after) == (Eval(cp=36), Eval(cp=-409))
    assert finding.swing == pytest.approx(0.352, abs=5e-4)
    assert finding.judgment == "blunder"
    assert (finding.best_uci, finding.best_san) == ("e2e3", "e3")
    assert finding.best_line_san == "6. e3 Be7 7. Bd3 c6 8. h3 Nf8"
    assert finding.refutation_san == "6... Nxd5 7. Bxd8 Bb4+ 8. Qd2 Bxd2+"
    assert finding.refutation_uci == ("f6d5", "g5d8", "f8b4", "d1d2", "b4d2", "e1d2")
    assert finding.accept_uci == ("e2e3", "g1f3")
    assert result.checked_out == ()


def test_pass_one_sees_every_position_once_and_pass_two_only_the_flagged_one() -> None:
    game, script = qgd_script()
    analyse_game(game, "white", script, depth=12, thresholds=TH)

    pass1 = [c for c in script.calls if c[2] == 1]
    pass2 = [c for c in script.calls if c[2] > 1]
    assert [c[0] for c in pass1] == [game.plies[0].fen_before] + [p.fen_after for p in game.plies]
    assert [(c[0], c[2]) for c in pass2] == [(game.plies[10].fen_before, MULTIPV)]
    # Nxd5 isn't among pass 2's lines, so it's searched alone from the same position (21.3)
    assert [(a[0], a[2]) for a in script.alone] == [(game.plies[10].fen_before, "c3d5")]
    assert {c[1] for c in script.calls} | {a[1] for a in script.alone} == {12}  # one depth
    keys = {c[3] for c in script.calls} | {a[3] for a in script.alone}
    assert len(keys) == 1 and None not in keys  # one game, one ucinewgame


def test_a_flag_the_check_clears_is_dropped() -> None:
    """Pass 1 drops 4 pawns after Nxd5, but pass 2, from the position before it, rates Nxd5
    16 cp below the best: depth noise, not a blunder. No entry, and no extra search."""
    game, script = qgd_script()
    nxd5 = game.plies[10]
    script.multi[nxd5.fen_before] = [
        Line(Eval(cp=36), mv("e2e3")),
        Line(Eval(cp=20), mv("c3d5")),  # the played move
        Line(Eval(cp=-30), mv("a2a3")),
    ]
    result = analyse_game(game, "white", script, depth=12, thresholds=TH)
    assert result.findings == ()
    assert result.checked_out == (10,)
    assert script.alone == []  # its score came with the MultiPV lines


def test_a_flag_the_check_confirms_from_the_multipv_lines() -> None:
    game, script = qgd_script()
    nxd5 = game.plies[10]
    script.multi[nxd5.fen_before] = [
        Line(Eval(cp=36), mv("e2e3")),
        Line(Eval(cp=-30), mv("a2a3")),
        Line(Eval(cp=-380), mv("c3d5")),  # the played move, still a blunder
    ]
    (finding,) = analyse_game(game, "white", script, depth=12, thresholds=TH).findings
    assert (finding.eval_before, finding.eval_after) == (Eval(cp=36), Eval(cp=-409))  # pass 1's
    assert finding.accept_uci == ("e2e3",)
    assert script.alone == []


def test_the_check_uses_the_lines_flag_at() -> None:
    """A FEN entry logs from the inaccuracy line, and its check does too."""
    game, script = qgd_script()
    nxd5 = game.plies[10]
    script.multi[nxd5.fen_before] = [
        Line(Eval(cp=36), mv("e2e3")),
        Line(Eval(cp=-40), mv("c3d5")),  # swing 0.07: an inaccuracy, not a blunder
    ]
    assert analyse_game(game, "white", script, depth=12, thresholds=TH).findings == ()
    result = analyse_game(game, "white", script, depth=12, thresholds=TH, flag_at="inaccuracy")
    assert [f.ply.label for f in result.findings] == ["6. Nxd5"]


def test_only_my_moves_are_flagged() -> None:
    game, script = qgd_script()
    result = analyse_game(game, "black", script, depth=12, thresholds=TH)
    assert result.findings == ()
    assert not [c for c in script.calls if c[2] > 1]


def test_progress_counts_positions_then_flagged_ones() -> None:
    game, script = qgd_script()
    seen: list[tuple[int, int]] = []
    analyse_game(
        game, "white", script, depth=12, thresholds=TH, progress=lambda d, t: seen.append((d, t))
    )
    positions = len(game.plies) + 1
    assert seen[:positions] == [(i, positions) for i in range(1, positions + 1)]
    assert seen[positions:] == [(positions + 1, positions + 1)]


def test_best_move_is_never_flagged_even_if_the_score_drops() -> None:
    game, _ = qgd_script()
    nxd5 = game.plies[10]
    script = Scripted(
        pass1={
            nxd5.fen_before: Line(Eval(cp=36), mv("c3d5")),
            nxd5.fen_after: Line(Eval(cp=-409)),
        }
    )
    assert analyse_game(game, "white", script, depth=12, thresholds=TH).findings == ()


def test_configured_blunder_line_is_used() -> None:
    game, script = qgd_script()
    strict = Thresholds(inaccuracy=0.4, mistake=0.4, blunder=0.4)
    assert analyse_game(game, "white", script, depth=12, thresholds=strict).findings == ()


def test_score_positions_is_pass_one_on_its_own() -> None:
    game, script = qgd_script()
    seen: list[tuple[int, int]] = []
    lines = score_positions(game, script, depth=12, progress=lambda d, t: seen.append((d, t)))
    nxd5 = game.plies[10]
    assert len(lines) == len(game.plies) + 1
    assert lines[10] == script.pass1[nxd5.fen_before]
    assert lines[11].score == Eval(cp=-409)
    assert {c[2] for c in script.calls} == {1}  # pass 1 only: no MultiPV
    assert [c[0] for c in script.calls] == [game.plies[0].fen_before] + [
        p.fen_after for p in game.plies
    ]
    assert len({c[3] for c in script.calls}) == 1  # one ucinewgame
    assert seen == [(i, len(lines)) for i in range(1, len(lines) + 1)]


def test_score_positions_keeps_the_game_key_it_is_given() -> None:
    game, script = qgd_script()
    key = object()
    score_positions(game, script, depth=12, key=key)
    score_positions(game, script, depth=12)
    keys = [c[3] for c in script.calls]
    n = len(game.plies) + 1
    assert set(keys[:n]) == {key}
    assert key not in keys[n:] and len(set(keys[n:])) == 1


# ---------------------------------------------------------------- missed wins (§7.6)


def missed_script(before: Eval, after: Eval, best: str = "e2e3") -> tuple[ParsedGame, Scripted]:
    """The QGD game with 5. cxd5 (ply 8) scored as given, and 6. Nxd5?? as before."""
    game, script = qgd_script()
    cxd5 = game.plies[8]
    script.pass1[cxd5.fen_before] = Line(before, mv(best, "e6d5"))
    script.pass1[cxd5.fen_after] = Line(after, mv("e6d5"))
    return game, script


def test_a_missed_mate_is_flagged_while_you_stay_winning() -> None:
    game, script = missed_script(Eval(mate=2), Eval(cp=500))
    result = analyse_game(game, "white", script, depth=12, thresholds=TH)
    by_ply = {f.ply.index: f for f in result.findings}
    assert sorted(by_ply) == [8, 10]
    missed = by_ply[8]
    assert missed.judgment == "missed"
    assert missed.swing < TH.blunder  # under the blunder line: the swing alone misses it
    assert (missed.best_uci, missed.best_pv_uci) == ("e2e3", ("e2e3", "e6d5"))
    assert by_ply[10].judgment == "blunder"  # 6. Nxd5?? is unchanged


def test_a_missed_queen_is_flagged() -> None:
    game, script = missed_script(Eval(cp=900), Eval(cp=500))
    result = analyse_game(game, "white", script, depth=12, thresholds=TH)
    assert [(f.ply.index, f.judgment) for f in result.findings] == [(8, "missed"), (10, "blunder")]


def test_a_missed_win_that_costs_the_advantage_stays_a_blunder() -> None:
    game, script = missed_script(Eval(cp=900), Eval(cp=100))
    result = analyse_game(game, "white", script, depth=12, thresholds=TH)
    assert [(f.ply.index, f.judgment) for f in result.findings] == [(8, "blunder"), (10, "blunder")]


def test_the_engines_own_move_is_never_a_missed_win() -> None:
    game, script = missed_script(Eval(mate=2), Eval(cp=500), best="c4d5")  # 5. cxd5 itself
    result = analyse_game(game, "white", script, depth=12, thresholds=TH)
    assert [f.ply.index for f in result.findings] == [10]


def test_missed_wins_turned_off() -> None:
    game, script = missed_script(Eval(mate=2), Eval(cp=500))
    off = Thresholds(missed_win_cp=0)
    assert [
        f.ply.index for f in analyse_game(game, "white", script, depth=12, thresholds=off).findings
    ] == [10]


def test_still_winning_by_a_lot_is_no_miss() -> None:
    game, script = missed_script(Eval(cp=1500), Eval(cp=1100))  # both over the +10 cap
    result = analyse_game(game, "white", script, depth=12, thresholds=TH)
    assert [f.ply.index for f in result.findings] == [10]


def test_progress_counts_missed_wins_in_pass_two() -> None:
    game, script = missed_script(Eval(mate=2), Eval(cp=500))
    seen: list[tuple[int, int]] = []
    analyse_game(
        game, "white", script, depth=12, thresholds=TH, progress=lambda d, t: seen.append((d, t))
    )
    positions = len(game.plies) + 1
    assert seen[positions:] == [(positions + 1, positions + 2), (positions + 2, positions + 2)]
    pass2 = [c[0] for c in script.calls if c[2] > 1]
    assert pass2 == [game.plies[8].fen_before, game.plies[10].fen_before]


# ---------------------------------------------------------------- finished positions


def test_checkmate_isnt_sent_to_the_engine() -> None:
    game = fixture("scholars_mate.pgn")  # ends 4. Qxf7#
    nf6 = game.plies[5]
    script = Scripted(
        pass1={
            nf6.fen_before: Line(Eval(cp=-32), mv("g7g6", "h5f3")),
            nf6.fen_after: Line(Eval(mate=1), mv("h5f7")),
        }
    )
    result = analyse_game(game, "black", script, depth=12, thresholds=TH)

    final = game.plies[-1].fen_after
    assert final not in [c[0] for c in script.calls]
    assert result.evals[-1] == Eval(mate=0)
    (finding,) = result.findings
    assert finding.ply.label == "3... Nf6"
    assert finding.eval_after == Eval(mate=1)
    assert finding.refutation_san == "4. Qxf7#"
    assert finding.best_line_san == "3... g6 4. Qf3"


def test_terminal_line() -> None:
    assert terminal_line(chess.Board()) is None
    mated = chess.Board("rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3")
    assert terminal_line(mated) == Line(Eval(mate=0))
    stalemate = chess.Board("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")
    assert terminal_line(stalemate) == Line(Eval(cp=0))
    bare_kings = chess.Board("8/8/4k3/8/8/4K3/8/8 w - - 0 1")
    assert terminal_line(bare_kings) == Line(Eval(cp=0))


def test_repetition_draws() -> None:
    board = chess.Board()
    shuffle = mv("g1f3", "g8f6", "f3g1", "f6g8")
    for move in shuffle * 2:
        board.push(move)
    assert board.can_claim_threefold_repetition()
    assert terminal_line(board) is None  # threefold must be claimed: still a game
    for move in shuffle * 2:
        board.push(move)
    assert terminal_line(board) == Line(Eval(cp=0))  # fivefold ends it


# ---------------------------------------------------------------- the engine always closes


class StubSimple:
    """Stands in for chess.engine.SimpleEngine."""

    def __init__(self, fail_on: int = 0) -> None:
        self.fail_on = fail_on
        self.calls = 0
        self.closed = False

    def analyse(
        self,
        board: chess.Board,
        limit: chess.engine.Limit,
        *,
        multipv: int | None = None,
        game: object = None,
        root_moves: list[chess.Move] | None = None,
    ) -> list[chess.engine.InfoDict]:
        self.calls += 1
        if self.calls == self.fail_on:
            raise chess.engine.EngineTerminatedError("engine process died unexpectedly")
        move = min(board.legal_moves, key=lambda m: m.uci())
        return [{"score": chess.engine.PovScore(chess.engine.Cp(15), board.turn), "pv": [move]}]

    def close(self) -> None:
        self.closed = True


def stub_engine(simple: StubSimple) -> Engine:
    return Engine(simple, EngineInfo("Stockfish 17.1", 17, 1))  # type: ignore[arg-type]


def test_engine_closes_when_it_crashes_mid_game() -> None:
    simple = StubSimple(fail_on=5)
    with pytest.raises(EngineError, match="stopped unexpectedly"), stub_engine(simple) as engine:
        analyse_game(fixture("qgd_elephant.pgn"), "white", engine, depth=8, thresholds=TH)
    assert simple.closed


def test_engine_closes_when_our_own_code_fails() -> None:
    simple = StubSimple()

    def progress(done: int, total: int) -> None:
        raise RuntimeError("progress display broke")

    with pytest.raises(RuntimeError), stub_engine(simple) as engine:
        analyse_game(
            fixture("qgd_elephant.pgn"), "white", engine, depth=8, thresholds=TH, progress=progress
        )
    assert simple.closed


def test_engine_closes_after_a_clean_run() -> None:
    simple = StubSimple()
    with stub_engine(simple) as engine:
        analyse_game(fixture("qgd_elephant.pgn"), "white", engine, depth=8, thresholds=TH)
    assert simple.closed


def test_no_score_is_an_error() -> None:
    script = Scripted()
    script.lines = lambda *a, **k: []  # type: ignore[method-assign]
    with pytest.raises(EngineError, match="no score after the start position"):
        analyse_game(fixture("qgd_elephant.pgn"), "white", script, depth=8, thresholds=TH)


# ---------------------------------------------------------------- a real UCI process (fake engine)


BLACK_TO_MOVE = chess.Board("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1")


@pytest.mark.parametrize(
    ("score", "white_to_move", "expected"),
    [
        ("cp 30", True, Eval(cp=30)),
        ("cp 30", False, Eval(cp=-30)),
        ("mate 2", True, Eval(mate=2)),
        ("mate 2", False, Eval(mate=-2)),
        ("mate -3", False, Eval(mate=3)),
    ],
)
def test_scores_come_back_from_whites_point_of_view(
    fake_engine: FakeEngine, score: str, white_to_move: bool, expected: Eval
) -> None:
    board = chess.Board() if white_to_move else BLACK_TO_MOVE
    with Engine.open(fake_engine("--score", score)) as engine:
        (line,) = engine.lines(board, 5)
    assert line.score == expected
    assert line.move in board.legal_moves


def test_multipv_lines(fake_engine: FakeEngine) -> None:
    with Engine.open(fake_engine("--score", "cp 50,cp 20,cp -40")) as engine:
        lines = engine.lines(chess.Board(), 5, 3)
    assert [line.score for line in lines] == [Eval(cp=50), Eval(cp=20), Eval(cp=-40)]
    assert [line.pv for line in lines] == [mv("a2a3"), mv("a2a4"), mv("b1a3")]


def test_settings_and_new_games_reach_the_engine(fake_engine: FakeEngine, tmp_path: Path) -> None:
    log = tmp_path / "uci.log"
    with Engine.open(fake_engine("--log", str(log)), threads=3, hash_mb=64) as engine:
        first, second = object(), object()
        engine.lines(chess.Board(), 7, game=first)
        engine.lines(BLACK_TO_MOVE, 7, game=first)
        engine.lines(chess.Board(), 7, game=second)
    sent = log.read_text("utf-8").splitlines()
    assert "setoption name Threads value 3" in sent
    assert "setoption name Hash value 64" in sent
    assert sent.count("ucinewgame") == 2
    assert sent.count("go depth 7 movetime 120000") == 3  # depth decides; the limit is a guard
    assert (engine.threads, engine.hash_mb) == (3, 64)  # kept, to store with each game


def test_one_move_alone_reaches_the_engine(fake_engine: FakeEngine, tmp_path: Path) -> None:
    """Pass 2's check of the move played (21.3) is a UCI ``searchmoves`` search."""
    log = tmp_path / "uci.log"
    with Engine.open(fake_engine("--log", str(log))) as engine:
        (line,) = engine.lines(chess.Board(), 7, root_moves=mv("g1f3"))
    assert line.move == chess.Move.from_uci("g1f3")  # not a2a3, the fake's first choice
    assert "go depth 7 movetime 120000 searchmoves g1f3" in log.read_text("utf-8").splitlines()


def test_settings_not_given_are_unknown(fake_engine: FakeEngine) -> None:
    with Engine.open(fake_engine(), hash_mb=32) as engine:
        assert (engine.threads, engine.hash_mb) == (None, 32)


def test_settings_the_engine_rejects(fake_engine: FakeEngine) -> None:
    with pytest.raises(EngineError, match="didn't accept the settings"):
        Engine.open(fake_engine(), threads=0)


def test_non_stockfish_is_refused_on_open(fake_engine: FakeEngine) -> None:
    with pytest.raises(EngineError, match="not Stockfish"):
        Engine.open(fake_engine("--name", "Lc0 v0.31"))


def test_whole_game_through_a_uci_process(fake_engine: FakeEngine, tmp_path: Path) -> None:
    log = tmp_path / "uci.log"
    game = fixture("scholars_mate.pgn")
    with Engine.open(fake_engine("--log", str(log))) as engine:
        result = analyse_game(game, "black", engine, depth=6, thresholds=TH)
    assert result.engine_name == "Stockfish 17.1"
    assert result.evals == (Eval(cp=0),) * 7 + (Eval(mate=0),)
    assert result.findings == ()
    assert len(result.positions) == 8
    assert all(p.best_uci is not None for p in result.positions[:-1])  # the fake's legal move
    assert result.positions[-1].best_uci is None  # checkmate: no move, no engine
    assert (result.threads, result.hash_mb) == (None, None)  # none were set
    sent = log.read_text("utf-8").splitlines()
    assert sent.count("go depth 6 movetime 120000") == 7  # the final checkmate isn't sent
    assert sent.count("ucinewgame") == 1


def test_crash_mid_game_closes_the_process(fake_engine: FakeEngine) -> None:
    game = fixture("qgd_elephant.pgn")
    engine = Engine.open(fake_engine("--crash-on-go", "4"))
    with pytest.raises(EngineError, match="stopped unexpectedly"), engine:
        analyse_game(game, "white", engine, depth=6, thresholds=TH)
    assert engine.closed


# ---------------------------------------------------------------- the safety limit (21.10)

LIMIT = 0.2  # seconds: a short limit stands in for the real 120 s


def test_a_search_cut_short_by_the_limit_is_an_error(fake_engine: FakeEngine) -> None:
    """The engine answers when its time runs out, but short of the depth: no score from that,
    and the same engine goes on (it never stopped answering)."""
    with Engine.open(fake_engine("--slow-on-go", "2"), search_limit_s=LIMIT) as engine:
        assert engine.lines(chess.Board(), 7)
        with pytest.raises(EngineTimeout, match=r"^Stockfish took over 0.2 s on one position\.$"):
            engine.lines(chess.Board(), 7)
        assert engine.lines(chess.Board(), 7)
        assert not engine.closed


def test_a_stuck_engine_is_restarted(fake_engine: FakeEngine, tmp_path: Path) -> None:
    log = tmp_path / "uci.log"
    command = fake_engine("--hang-on-go", "2", "--log", str(log))
    with Engine.open(command, threads=2, timeout=1, search_limit_s=LIMIT) as engine:
        assert engine.lines(chess.Board(), 7)
        stuck = f"SimpleEngine (pid={engine._simple.transport.get_pid()})"
        with pytest.raises(EngineTimeout):
            engine.lines(chess.Board(), 7)  # no answer at all: killed and started again
        assert engine.lines(BLACK_TO_MOVE, 7)  # the new process's first search
        assert not engine.closed
    # the stuck process's thread ends too, or Python would wait for it on exit
    deadline = time.monotonic() + 5
    while stuck in {t.name for t in threading.enumerate()} and time.monotonic() < deadline:
        time.sleep(0.05)
    assert stuck not in {t.name for t in threading.enumerate()}
    sent = log.read_text("utf-8").splitlines()
    assert sent.count("uci") == 2
    assert sent.count("setoption name Threads value 2") == 2  # the same settings again


def test_a_stuck_engine_that_cant_start_again(fake_engine: FakeEngine) -> None:
    simple = chess.engine.SimpleEngine.popen_uci(fake_engine("--hang-on-go", "1"), timeout=1)
    info = EngineInfo("Stockfish 17.1", 17, 1)
    engine = Engine(simple, info, search_limit_s=LIMIT, grace_s=0.5)  # under python-chess's 1 s
    with pytest.raises(EngineError, match="stopped answering") as raised, engine:
        engine.lines(chess.Board(), 7)
    assert not isinstance(raised.value, EngineTimeout)  # that stops the import
    assert engine.closed


def test_the_limit_names_the_position(fake_engine: FakeEngine) -> None:
    game = fixture("scholars_mate.pgn")
    engine = Engine.open(fake_engine("--slow-on-go", "3"), search_limit_s=LIMIT)
    with engine, pytest.raises(EngineTimeout) as raised:
        analyse_game(game, "black", engine, depth=6, thresholds=TH)
    assert str(raised.value) == "Stockfish took over 0.2 s after 1... e5."
    assert raised.value.where == "after 1... e5"


def test_a_limit_in_the_start_position(fake_engine: FakeEngine) -> None:
    game = fixture("scholars_mate.pgn")
    engine = Engine.open(fake_engine("--slow-on-go", "1"), search_limit_s=LIMIT)
    with engine, pytest.raises(EngineTimeout, match="in the start position"):
        score_positions(game, engine, depth=6)


# ---------------------------------------------------------------- real Stockfish


@pytest.mark.engine
def test_stockfish_flags_the_elephant_trap(stockfish_path: Path) -> None:
    game = fixture("qgd_elephant.pgn")
    with Engine.open(str(stockfish_path), threads=1, hash_mb=16) as engine:
        result = analyse_game(game, "white", engine, depth=12, thresholds=TH)
    flagged = {f.ply.label: f for f in result.findings}
    assert "6. Nxd5" in flagged
    nxd5 = flagged["6. Nxd5"]
    assert nxd5.best_uci != "c3d5"
    assert nxd5.best_uci in nxd5.accept_uci
    assert "c3d5" not in nxd5.accept_uci
    assert result.engine_name.startswith("Stockfish")
    assert (result.threads, result.hash_mb) == (1, 16)
    assert result.positions[nxd5.ply.index].best_uci == nxd5.best_uci


@pytest.mark.engine
def test_stockfish_mate_scores_are_whites_point_of_view(stockfish_path: Path) -> None:
    game = fixture("scholars_mate.pgn")
    with Engine.open(str(stockfish_path), threads=1, hash_mb=16) as engine:
        result = analyse_game(game, "black", engine, depth=10, thresholds=TH)
    nf6 = {f.ply.label: f for f in result.findings}["3... Nf6"]
    assert nf6.eval_after == Eval(mate=1)  # White mates in 1
    assert nf6.refutation_san == "4. Qxf7#"
    assert result.evals[-1] == Eval(mate=0)


@pytest.mark.engine
def test_stockfish_stops_at_the_safety_limit(stockfish_path: Path) -> None:
    """Real Stockfish honours the limit and reports the depth it reached, so a deep search
    cut short is an error, not a score (21.10)."""
    engine = Engine.open(str(stockfish_path), threads=1, hash_mb=16, search_limit_s=0.2)
    with engine, pytest.raises(EngineTimeout):
        engine.lines(chess.Board(), 40)
    with Engine.open(str(stockfish_path), threads=1, hash_mb=16) as engine:
        assert engine.lines(chess.Board(), 12)  # a normal search is untouched
