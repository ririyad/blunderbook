"""The Collection's routes, mounted at ``/api/ext/collection`` (ROADMAP 12.3): the
collections, a collection's stats with 12.2's filters, its players, and one game with every
move judged and the eval of every position.

Everything is worked out here, with :mod:`blunderbook_collection.stats` and your thresholds
read from config.toml on each request, so the page does no chess or maths (as in core).
Nothing here changes anything: importing on the page is 12.4.
"""

from typing import Annotated, Final, Literal

import chess
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from blunderbook import host
from blunderbook.core import detect
from blunderbook.core.models import Color, Judgment, Thresholds
from blunderbook_collection import stats, store
from blunderbook_collection.games import Position

router = APIRouter()

ALL: Final = "all"  # every collection, each game once
ALL_TITLE: Final = "All collections"
MAX_TEXT: Final = 100  # a player's name or an opening, as typed


# ---------------------------------------------------------------- the collections


class CollectionOut(BaseModel):
    id: int
    name: str
    games: int


class IndexOut(BaseModel):
    collections: list[CollectionOut]  # by name
    games: int  # every collection's, each game once


@router.get("/collections")
def list_collections(db: host.ExtDb) -> IndexOut:
    return IndexOut(
        collections=[
            CollectionOut(id=c.id, name=c.name, games=c.games) for c in store.collections(db)
        ],
        games=store.count_games(db),
    )


# ---------------------------------------------------------------- stats


class ScoreOut(BaseModel):
    won: int
    drawn: int
    lost: int
    unfinished: int  # "*" or no result


class TallyOut(BaseModel):
    games: int
    moves: int
    accuracy: float | None  # 0..100, the mean of the games'
    acpl: float | None
    blunders: int
    mistakes: int
    inaccuracies: int


class PhaseOut(TallyOut):
    phase: stats.Phase


class OpeningOut(BaseModel):
    eco: str | None
    name: str | None
    color: Color | None  # the player's colour, with a player
    score: ScoreOut  # from the player's side with one, else White's
    sides: list[TallyOut]  # as StatsOut.sides


class GameLineOut(BaseModel):
    id: int
    white: str | None
    black: str | None
    result: str | None
    date: str | None  # the known parts of the Date header: "1858", "1858-10-31"
    event: str | None
    eco: str | None
    opening: str | None
    moves: int
    player_color: Color | None  # the player's colour, with a player
    by_side: list[TallyOut]  # White's moves, then Black's


class OpeningOption(BaseModel):
    eco: str | None
    name: str | None


class StatsOut(BaseModel):
    title: str  # the collection's name, or "All collections"
    collection: int | None  # None for every collection
    total: int  # the games before any filter
    games: int  # the games that pass the filters
    score: ScoreOut
    labels: list[str]  # ["White", "Black"], or [the player, "Opponents"]
    sides: list[TallyOut]  # the moves of each label's side
    phases: list[PhaseOut]  # the moves counted: both sides', or the player's / one side's
    openings: list[OpeningOut]  # most games first
    lines: list[GameLineOut]  # in the order they were added
    players: list[str]  # for the filter: everyone who played, most games first
    opening_options: list[OpeningOption]  # every opening played, by ECO
    engines: list[str]  # "Stockfish 17.1 · depth 16", most games first


type ResultParam = Literal["won", "lost", "drawn", "white", "black"]
type Text = Annotated[str | None, Query(max_length=MAX_TEXT)]


@router.get("/stats")
def get_stats(
    db: host.ExtDb,
    collection: str = ALL,
    player: Text = None,
    color: Color | None = None,
    result: ResultParam | None = None,
    opening: Text = None,
    phase: stats.Phase | None = None,
) -> StatsOut:
    """A collection's stats (every collection's with ``all``), with the CLI's filters."""
    f = stats.Filter(
        player=_text(player),
        color=color,
        result=result,
        opening=_text(opening),
        phase=phase,
    )
    if f.problem():  # the CLI's words name its options
        raise HTTPException(422, f"A {result} result needs a player: whose result is it?")
    thresholds = _thresholds()
    title, collection_id = _collection(db, collection)
    games = store.load(db, collection_id)
    report = stats.report(games, thresholds, f)
    return StatsOut(
        title=title,
        collection=collection_id,
        total=len(games),
        games=report.games,
        score=_score(report.score),
        labels=list(report.labels),
        sides=[_tally(t) for t in report.sides],
        phases=[PhaseOut(phase=p, **_tally(t).model_dump()) for p, t in report.phases.items()],
        openings=[
            OpeningOut(
                eco=o.eco,
                name=o.name,
                color=o.color,
                score=_score(o.score),
                sides=[_tally(t) for t in o.sides],
            )
            for o in report.openings
        ],
        lines=[_line(line) for line in report.lines],
        players=[p.name for p in stats.players(games, thresholds)],
        opening_options=_opening_options(games),
        engines=[
            f"{name} \N{MIDDLE DOT} depth {depth}"
            for name, depth in store.engines(db, collection_id)
        ],
    )


# ---------------------------------------------------------------- players


class PlayerOut(BaseModel):
    name: str  # as first written
    games: int
    as_white: int
    as_black: int
    score: ScoreOut  # from their side
    accuracy: float | None


class PlayersOut(BaseModel):
    title: str
    collection: int | None
    players: list[PlayerOut]  # most games first, then by name


@router.get("/players")
def get_players(db: host.ExtDb, collection: str = ALL) -> PlayersOut:
    thresholds = _thresholds()
    title, collection_id = _collection(db, collection)
    found = stats.players(store.load(db, collection_id), thresholds)
    return PlayersOut(
        title=title,
        collection=collection_id,
        players=[
            PlayerOut(
                name=p.name,
                games=p.games,
                as_white=p.as_white,
                as_black=p.as_black,
                score=_score(p.score),
                accuracy=p.accuracy,
            )
            for p in found
        ],
    )


# ---------------------------------------------------------------- one game


class CollectionRef(BaseModel):
    id: int
    name: str


class PositionOut(BaseModel):
    ply: int  # 0 is the start, i the position after move i - 1
    fen: str
    eval: dict[str, int]  # {"cp": 36} | {"mate": -2}, White's side
    chances: float  # White's winning chances, 0..1, for the eval graph


class MoveOut(BaseModel):
    ply: int  # 0-based: the move from position ply to ply + 1
    move_no: int
    color: Color
    label: str  # "5. Nxe5", "5... Bxd1"
    san: str
    uci: str
    judgment: Judgment | None  # blunder / mistake / inaccuracy; None when it's fine
    accuracy: float
    cp_loss: int
    phase: stats.Phase
    best_san: str | None  # Stockfish's move instead, for a marked move
    best_line: str | None  # its line: "6. e3 Be7 7. Bd3"
    refutation: str | None  # Stockfish's line after the move, for a marked move


class GameOut(BaseModel):
    id: int
    white: str | None
    black: str | None
    white_elo: int | None
    black_elo: int | None
    result: str | None
    date: str | None
    event: str | None
    site_label: str
    round: str | None
    eco: str | None
    opening: str | None
    start_fen: str
    engine: str  # "Stockfish 17.1 · depth 16"
    collections: list[CollectionRef]
    by_side: list[TallyOut]  # White's, then Black's
    positions: list[PositionOut]
    moves: list[MoveOut]


@router.get("/games/{game_id}")
def get_game(game_id: int, db: host.ExtDb) -> GameOut:
    detail = store.game_detail(db, game_id)
    if detail is None:
        raise HTTPException(404, f"No game #{game_id} in your collections.")
    thresholds = _thresholds()
    g = detail.game
    moves = stats.moves(g, thresholds)
    white, black = stats.Tally(), stats.Tally()
    white.add_game([m for m in moves if m.color == "white"])
    black.add_game([m for m in moves if m.color == "black"])
    return GameOut(
        id=g.id,
        white=g.white,
        black=g.black,
        white_elo=detail.white_elo,
        black_elo=detail.black_elo,
        result=g.result,
        date=date_label(g.date),
        event=g.event,
        site_label=detail.site_label,
        round=detail.round,
        eco=g.eco,
        opening=g.opening,
        start_fen=detail.start_fen,
        engine=f"{detail.engine_name} \N{MIDDLE DOT} depth {detail.engine_depth}",
        collections=[CollectionRef(id=i, name=n) for i, n in detail.collections],
        by_side=[_tally(white), _tally(black)],
        positions=[
            PositionOut(ply=p.ply, fen=p.fen, eval=p.score.to_dict(), chances=white_chances(p))
            for p in g.positions
        ],
        moves=[_move(m, g.positions[m.ply], g.positions[m.ply + 1]) for m in moves],
    )


def white_chances(p: Position) -> float:
    """White's winning chances in a position, 0..1 (0.5 is level)."""
    turn: Color = "white" if chess.Board(p.fen).turn == chess.WHITE else "black"
    return (1 + detect.winning_chances(detect.maths_cp(p.score, turn))) / 2


def _move(m: stats.Move, before: Position, after: Position) -> MoveOut:
    best_san = best_line = refutation = None
    if m.judgment is not None:
        moves = [chess.Move.from_uci(u) for u in after.pv_uci]
        refutation = detect.refutation_san(after.fen, moves)
    if m.judgment is not None and before.best_uci:
        board = chess.Board(before.fen)
        line = [chess.Move.from_uci(u) for u in before.pv_uci] or [
            chess.Move.from_uci(before.best_uci)
        ]
        best_san = board.san(chess.Move.from_uci(before.best_uci))
        best_line = detect.best_line_san(before.fen, line) or None
    assert after.move_uci is not None
    label = f"{m.move_no}{'.' if m.color == 'white' else '...'} {m.san}"
    return MoveOut(
        ply=m.ply,
        move_no=m.move_no,
        color=m.color,
        label=label,
        san=m.san,
        uci=after.move_uci,
        judgment=m.judgment,
        accuracy=round(m.accuracy, 1),
        cp_loss=m.cp_loss,
        phase=m.phase,
        best_san=best_san,
        best_line=best_line,
        refutation=refutation,
    )


# ---------------------------------------------------------------- helpers


def date_label(date: str | None) -> str | None:
    """The known parts of a PGN date: "1858.??.??" is "1858", "1858.10.31" "1858-10-31"."""
    if not date:
        return None
    parts: list[str] = []
    for part in date.replace("-", ".").split("."):
        if not part.isdigit():
            break
        parts.append(part)
    return "-".join(parts) or None


def _text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def _collection(db: host.ExtDb, wanted: str) -> tuple[str, int | None]:
    if wanted == ALL:
        return ALL_TITLE, None
    if not wanted.isdigit():
        raise HTTPException(422, "collection is a collection's number, or all.")
    found = store.by_id(db, int(wanted))
    if found is None:
        raise HTTPException(404, f"No collection #{wanted}.")
    return found.name, found.id


def _thresholds() -> Thresholds:
    try:
        return host.settings().thresholds
    except host.HostError as exc:
        raise HTTPException(503, str(exc)) from None


def _score(s: stats.Score) -> ScoreOut:
    return ScoreOut(won=s.won, drawn=s.drawn, lost=s.lost, unfinished=s.unfinished)


def _tally(t: stats.Tally) -> TallyOut:
    return TallyOut(
        games=t.games,
        moves=t.moves,
        accuracy=None if t.accuracy is None else round(t.accuracy, 1),
        acpl=None if t.acpl is None else round(t.acpl, 1),
        blunders=t.blunders,
        mistakes=t.mistakes,
        inaccuracies=t.inaccuracies,
    )


def _line(line: stats.GameLine) -> GameLineOut:
    g = line.game
    return GameLineOut(
        id=g.id,
        white=g.white,
        black=g.black,
        result=g.result,
        date=date_label(g.date),
        event=g.event,
        eco=g.eco,
        opening=g.opening,
        moves=len(g.positions) // 2,
        player_color=line.player_color,
        by_side=[_tally(line.white), _tally(line.black)],
    )


def _opening_options(games: list[stats.Game]) -> list[OpeningOption]:
    seen = {(g.eco, g.opening) for g in games if g.eco or g.opening}
    ordered = sorted(seen, key=lambda o: (o[0] or "~", (o[1] or "").casefold()))
    return [OpeningOption(eco=eco, name=name) for eco, name in ordered]
