"""A collection's stats (ROADMAP 12.2): each move judged as your own are, accuracy, centipawn
loss, phases, the filters, openings and players, from evals made up for the test."""

from contextlib import closing

import chess
import pytest
from blunderbook_collection import collect, extension, games, stats, store
from collection_fakes import (  # noqa: F401  (fixtures)
    CLASSICS,
    FakeEngine,
    cfg_file,
    fake,
)

from blunderbook import host
from blunderbook.core import pgn
from blunderbook.core.models import Eval, Thresholds

TH = Thresholds()
LEGAL = "1. e4 e5 2. Nf3 d6 3. Bc4 Bg4 4. Nc3 g6 5. Nxe5 Bxd1 6. Bxf7+ Ke7 7. Nd5# 1-0"


def game(
    movetext: str,
    scores: list[Eval],
    best: dict[int, str] | None = None,
    *,
    gid: int = 1,
    white: str | None = "Kermur de Légal",
    black: str | None = "Saint Brie",
    result: str | None = "1-0",
    eco: str | None = "C41",
    opening: str | None = "Philidor Defence",
    fen: str | None = None,
) -> stats.Game:
    """A stored game with these evals (one per position). ``best`` gives the engine's move
    in a position; by default it's the move after, unless that's the last."""
    head = f'[FEN "{fen}"]\n[SetUp "1"]\n\n' if fen else ""
    parsed = pgn.parse(head + movetext).games[0]
    assert len(scores) == len(parsed.plies) + 1
    best = best or {}
    positions = []
    for i, score in enumerate(scores):
        ply = parsed.plies[i - 1] if i else None
        default = parsed.plies[i].uci if i < len(parsed.plies) else None
        engine_move = best.get(i, default)
        positions.append(
            games.Position(
                ply=i,
                fen=ply.fen_after if ply else parsed.start_fen,
                move_uci=ply.uci if ply else None,
                move_san=ply.san if ply else None,
                clock_s=None,
                score=score,
                best_uci=engine_move,
                pv_uci=(engine_move,) if engine_move else (),
            )
        )
    return stats.Game(
        gid, white, black, result, eco, opening, "1750.??.??", "Paris", tuple(positions)
    )


def cp(*values: int) -> list[Eval]:
    return [Eval(cp=v) for v in values]


# Légal's game: level until 4... g6 (+2.7), 5... Bxd1 lets White mate in two.
LEGAL_SCORES = [*cp(30, 30, 30, 30, 30, 30, 60, 50, 270, 270), Eval(mate=2), Eval(mate=1),
                Eval(mate=1), Eval(mate=0)]  # fmt: skip
LEGAL_BEST = {7: "g8f6", 8: "d1e2", 9: "d6e5"}  # the engine wanted Nf6, Qe2, then dxe5


def legal(**kw: object) -> stats.Game:
    return game(LEGAL, LEGAL_SCORES, LEGAL_BEST, **kw)  # type: ignore[arg-type]


# ---------------------------------------------------------------- one move


def test_accuracy_of_a_move() -> None:
    assert stats.win_percent(0) == 50
    assert stats.move_accuracy(30, 30) == pytest.approx(100, abs=1e-3)
    assert stats.move_accuracy(0, 50) == 100  # it got better: no more than 100
    assert stats.move_accuracy(300, -300) == pytest.approx(8.41, abs=0.01)
    assert stats.move_accuracy(10_000, -10_000) == 0


def test_accuracy_of_a_game() -> None:
    assert stats.game_accuracy([]) is None
    assert stats.game_accuracy([90, 90]) == pytest.approx(90)
    # one bad move costs more than the plain average (50): mean 50, harmonic ~1.98
    assert stats.game_accuracy([100, 0]) == pytest.approx((50 + 2 / 1.01) / 2)


def test_every_move_is_judged() -> None:
    moves = stats.moves(legal(), TH)
    assert len(moves) == 13
    assert [(m.ply, m.move_no, m.color, m.san) for m in moves[:2]] == [
        (0, 1, "white", "e4"),
        (1, 1, "black", "e5"),
    ]
    marked = {m.san: m.judgment for m in moves if m.judgment}
    assert marked == {"g6": "blunder", "Bxd1": "blunder"}
    bxd1 = moves[9]
    assert bxd1.swing == pytest.approx(0.2701, abs=1e-4)  # (w(-270) - w(-mate)) / 2
    assert bxd1.cp_loss == 1000 - 270  # mate counts as 1000 here (capped)
    assert bxd1.accuracy == pytest.approx(28.66, abs=0.01)  # winning chances -27 points


def test_the_engines_own_move_is_never_marked() -> None:
    # 4... g6 drops 2.2 pawns, but say it was the engine's move: no mark, the loss still counts
    moves = stats.moves(game(LEGAL, LEGAL_SCORES, {**LEGAL_BEST, 7: "g7g6"}), TH)
    g6 = moves[7]
    assert (g6.san, g6.judgment, g6.cp_loss) == ("g6", None, 220)


def test_thresholds_are_yours() -> None:
    strict = Thresholds(inaccuracy=0.2, mistake=0.3, blunder=0.4)
    marked = {m.san: m.judgment for m in stats.moves(legal(), strict) if m.judgment}
    assert marked == {"Bxd1": "inaccuracy"}


def test_a_check_mate_at_the_end_counts_as_won() -> None:
    last = stats.moves(legal(), TH)[-1]
    assert (last.san, last.judgment, last.cp_loss) == ("Nd5#", None, 0)
    assert last.accuracy == pytest.approx(100, abs=1e-3)


def test_phases() -> None:
    assert stats.phase(chess.Board()) == "opening"
    middle = chess.Board()
    middle.fullmove_number = 11
    assert stats.phase(middle) == "middlegame"
    ending = chess.Board("4k3/8/8/8/8/8/4P3/R2QK2R w - - 0 5")  # 3 pieces, move 5
    assert stats.phase(ending) == "endgame"
    six = chess.Board("r2qk2r/8/8/8/8/8/8/R2QK2R w - - 0 30")
    assert stats.phase(six) == "endgame"
    seven = chess.Board("rn1qk2r/8/8/8/8/8/8/R2QK2R w - - 0 30")
    assert stats.phase(seven) == "middlegame"


def test_a_game_from_a_position_counts_its_own_move_numbers() -> None:
    g = game("40. Rd8+ Kf7 *", cp(500, 500, 500), fen="6k1/6pp/8/8/8/8/6PP/3R2K1 w - - 0 40",
             result="*")  # fmt: skip
    assert [(m.move_no, m.phase) for m in stats.moves(g, TH)] == [
        (40, "endgame"),
        (40, "endgame"),
    ]


# ---------------------------------------------------------------- the report

OPERA = "1. e4 e5 2. Nf3 d6 3. d4 Bg4 *"


def collection() -> list[stats.Game]:
    return [
        legal(),
        game(
            OPERA,
            cp(30, 30, 30, 30, 30, 30, 30),
            gid=2,
            white="Paul Morphy",
            black="Duke Karl",
            result="1/2-1/2",
        ),
        game(
            OPERA,
            cp(30, 30, 30, 30, 30, -300, -300),
            {4: "b1c3"},
            gid=3,
            white="Saint Brie",
            black="kermur de légal",
            result="0-1",
        ),
        game(
            "1. e4 c6 *",
            cp(30, 30, 30),
            gid=4,
            white="Richard Réti",
            black="Tartakower",
            result="*",
            eco="B10",
            opening="Caro-Kann Defence",
        ),
    ]


def test_everything() -> None:
    r = stats.report(collection(), TH)
    assert r.games == 4
    assert r.labels == ("White", "Black")
    assert r.score == stats.Score(won=1, drawn=1, lost=1, unfinished=1)  # White's side
    white, black = r.sides
    assert (white.games, white.moves, black.games, black.moves) == (
        4,
        7 + 3 + 3 + 1,
        4,
        6 + 3 + 3 + 1,
    )
    assert white.blunders == 1  # 3. d4?? in game 3: +0.3 to -3.0
    assert black.blunders == 2  # g6 and Bxd1
    assert set(r.phases) == {"opening", "middlegame", "endgame"}
    assert r.phases["opening"].moves == white.moves + black.moves
    assert [line.game.id for line in r.lines] == [1, 2, 3, 4]
    assert r.lines[0].black.blunders == 2 and r.lines[0].white.blunders == 0
    eco = [(o.eco, o.sides[0].games, o.score) for o in r.openings]
    assert eco == [
        ("C41", 3, stats.Score(won=1, drawn=1, lost=1)),
        ("B10", 1, stats.Score(unfinished=1)),
    ]


def test_a_player() -> None:
    r = stats.report(collection(), TH, stats.Filter(player="KERMUR DE LÉGAL"))
    assert r.games == 2
    assert r.labels == ("Kermur de Légal", "Opponents")  # as first written
    assert r.score == stats.Score(won=2)  # won as White, and as Black (0-1)
    mine, theirs = r.sides
    assert mine.moves == 7 + 3  # their moves only
    assert theirs.blunders == 3  # g6, Bxd1, then Saint Brie's 3. d4
    assert {(o.color, o.eco) for o in r.openings} == {("white", "C41"), ("black", "C41")}
    assert [line.player_color for line in r.lines] == ["white", "black"]


def test_a_player_and_a_colour() -> None:
    r = stats.report(collection(), TH, stats.Filter(player="Kermur de Légal", color="black"))
    assert [line.game.id for line in r.lines] == [3]


def test_one_sides_moves() -> None:
    r = stats.report(collection(), TH, stats.Filter(color="black"))
    assert r.labels == ("Black", "White")
    assert r.sides[0].blunders == 2
    assert r.phases["opening"].moves == r.sides[0].moves  # only Black's


@pytest.mark.parametrize(
    ("f", "ids"),
    [
        (stats.Filter(result="white"), [1]),
        (stats.Filter(result="black"), [3]),
        (stats.Filter(result="drawn"), [2]),
        (stats.Filter(player="Saint Brie", result="won"), []),
        (stats.Filter(player="Saint Brie", result="lost"), [1, 3]),
        (stats.Filter(opening="c4"), [1, 2, 3]),  # an ECO start
        (stats.Filter(opening="B10"), [4]),
        (stats.Filter(opening="caro"), [4]),  # part of the name
        (stats.Filter(opening="C5"), []),
        (stats.Filter(player="Nobody"), []),
    ],
)
def test_filters(f: stats.Filter, ids: list[int]) -> None:
    assert [line.game.id for line in stats.report(collection(), TH, f).lines] == ids


def test_a_phase() -> None:
    r = stats.report(collection(), TH, stats.Filter(phase="middlegame"))
    assert r.games == 4  # the games pass; none has a middlegame move
    assert (r.sides[0].games, r.sides[0].moves, r.sides[0].accuracy) == (0, 0, None)
    assert r.sides[0].acpl is None


def test_won_or_lost_needs_a_player() -> None:
    assert stats.Filter(result="won").problem() == (
        "--result won needs --player: whose result is it?"
    )
    assert stats.Filter(result="white").problem() is None


def test_players() -> None:
    found = stats.players(collection(), TH)
    assert [(p.name, p.games, p.as_white, p.as_black) for p in found] == [
        ("Kermur de Légal", 2, 1, 1),
        ("Saint Brie", 2, 1, 1),
        ("Duke Karl", 1, 0, 1),
        ("Paul Morphy", 1, 1, 0),
        ("Richard Réti", 1, 1, 0),
        ("Tartakower", 1, 0, 1),
    ]
    assert found[0].score == stats.Score(won=2)
    assert found[1].score == stats.Score(lost=2)
    assert found[0].accuracy is not None and found[0].accuracy > found[1].accuracy  # type: ignore[operator]


def test_unknown_names_are_left_out() -> None:
    g = game("1. e4 e5 *", cp(30, 30, 30), white=None, black=None)
    assert stats.players([g], TH) == ()


# ---------------------------------------------------------------- from collection.db


def test_loading_from_the_database(fake: FakeEngine) -> None:
    text = CLASSICS.read_text("utf-8")
    with closing(host.open_db(extension)) as conn:
        for name in ("Classics", "Again"):
            collect.add(conn, name, collect.queue(conn, text, name), fake, depth=8)  # type: ignore[arg-type]
        every = store.load(conn)
        classics = store.find(conn, "Classics")
        assert classics is not None
        one = store.load(conn, classics.id)
    assert [g.white for g in every] == ["Paul Morphy", "Kermur de Legal"]  # each game once
    assert [g.id for g in one] == [g.id for g in every]
    morphy = every[0]
    assert (morphy.eco, morphy.opening, morphy.date, morphy.event) == (
        "C41",
        "Philidor Defence",
        "1858.??.??",
        "Paris",
    )
    assert len(morphy.positions) == 34
    assert len(stats.moves(morphy, TH)) == 33
    r = stats.report(every, TH)
    assert r.sides[0].blunders == r.sides[1].blunders == 0  # the fake scores every move +0.2
