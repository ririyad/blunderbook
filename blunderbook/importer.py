"""The import pipeline: PGN text -> games -> analysis -> blunders (CLAUDE.md §7, §9).

1. :func:`prepare` reads the text and puts each game in the queue as ``ready``,
   ``needs_side``, ``duplicate`` or ``error``. No engine is needed for this step.
2. :func:`analyse` runs one ready game through the engine and the suggested causes.
3. :func:`save` stores the analysed game and its blunders in one transaction.

Only analysed games are saved (CLAUDE.md §7.4). Each is saved as soon as it's analysed, so
if the engine stops, the games before it are kept and importing the file again finishes
the rest.
"""

import sqlite3
from collections.abc import Container, Iterable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal

from blunderbook.core import engine, hints, identity, pgn, timecontrol
from blunderbook.core.models import (
    Color,
    Finding,
    GameAnalysis,
    NewBlunder,
    NewGame,
    ParsedGame,
    SourceInfo,
    Thresholds,
    header_value,
)
from blunderbook.core.source import detect_source
from blunderbook.db import repo

GameStatus = Literal["ready", "needs_side", "duplicate", "error"]
SideFrom = Literal["names", "option"]

ALREADY_IMPORTED = "Already imported \N{EM DASH} skipped"


@dataclass(frozen=True, slots=True)
class QueuedGame:
    """One game of the file, in file order, with what happens to it next."""

    number: int  # 1-based position in the file
    status: GameStatus
    headers: frozendict[str, str]
    game: ParsedGame | None = None  # None when the game couldn't be read
    source: SourceInfo | None = None
    fingerprint: str | None = None
    side: Color | None = None  # set when ready
    side_from: SideFrom | None = None
    reason: str | None = None  # why it's an error or a duplicate
    warnings: tuple[str, ...] = ()

    def header(self, name: str) -> str | None:
        return header_value(self.headers, name)

    @property
    def players(self) -> str:
        return f"{self.header('White') or '?'} vs {self.header('Black') or '?'}"

    @property
    def date(self) -> str | None:
        """``YYYY-MM-DD`` when the header is a full date."""
        played = pgn.parse_date(self.header("Date"))
        return played.isoformat() if played else None


@dataclass(frozen=True, slots=True)
class FoundBlunder:
    finding: Finding
    hints: hints.Hints


@dataclass(frozen=True, slots=True)
class AnalysedGame:
    queued: QueuedGame
    analysis: GameAnalysis
    blunders: tuple[FoundBlunder, ...]


@dataclass(frozen=True, slots=True)
class SavedGame:
    analysed: AnalysedGame
    game_id: int
    blunder_ids: tuple[int, ...]  # one per analysed.blunders, same order


def prepare(
    text: str,
    names: Iterable[str],
    *,
    side: Color | None = None,
    known: Container[str] = frozenset(),
) -> tuple[QueuedGame, ...]:
    """Read ``text`` and queue every game in it, in file order.

    ``names`` are your names and usernames. ``side`` is used for games where they match
    neither player (or both). ``known`` holds fingerprints already imported. A game that
    repeats an earlier one in the same text is a duplicate too.
    """
    names = tuple(names)
    parsed = pgn.parse(text)
    queue: list[QueuedGame] = [
        QueuedGame(p.number, "error", p.headers, reason=p.reason) for p in parsed.problems
    ]
    seen: dict[str, int] = {}
    for game in parsed.games:
        source = detect_source(game.headers)
        fp = identity.fingerprint(game, source)
        base = QueuedGame(
            game.number,
            "ready",
            game.headers,
            game=game,
            source=source,
            fingerprint=fp,
            warnings=game.warnings,
        )
        if fp in known:
            queue.append(replace(base, status="duplicate", reason=ALREADY_IMPORTED))
            continue
        if fp in seen:
            note = f"Same game as game {seen[fp]} \N{EM DASH} skipped"
            queue.append(replace(base, status="duplicate", reason=note))
            continue
        seen[fp] = game.number
        mine = identity.my_side(game.headers, names)
        if mine is not None:
            queue.append(replace(base, side=mine, side_from="names"))
        elif side is not None:
            queue.append(replace(base, side=side, side_from="option"))
        else:
            queue.append(replace(base, status="needs_side"))
    return tuple(sorted(queue, key=lambda q: q.number))


def analyse(
    queued: QueuedGame,
    analyser: engine.Analyser,
    *,
    depth: int,
    thresholds: Thresholds,
    progress: engine.Progress | None = None,
) -> AnalysedGame:
    """Run the engine over a ready game and add the suggested causes to each blunder."""
    if queued.status != "ready" or queued.game is None or queued.side is None:
        raise ValueError(f"Game {queued.number} isn't ready to analyse ({queued.status}).")
    game = queued.game
    analysis = engine.analyse_game(
        game, queued.side, analyser, depth=depth, thresholds=thresholds, progress=progress
    )
    tc = timecontrol.parse(game.header("TimeControl"))
    found = tuple(FoundBlunder(f, hints.suggest(f, game, tc)) for f in analysis.findings)
    return AnalysedGame(queued, analysis, found)


def save(
    conn: sqlite3.Connection, analysed: AnalysedGame, *, now: datetime | None = None
) -> SavedGame | None:
    """Store an analysed game and its blunders. None when the game was saved meanwhile
    (by another import running at the same time): nothing is written then."""
    ids = repo.add_game(
        conn, new_game(analysed), [new_blunder(b) for b in analysed.blunders], now=now
    )
    if ids is None:
        return None
    return SavedGame(analysed, ids.game_id, ids.blunder_ids)


def new_game(analysed: AnalysedGame) -> NewGame:
    """The ``games`` row for an analysed game. Unknown headers stay None."""
    queued = analysed.queued
    game, source, side = queued.game, queued.source, queued.side
    assert game is not None and source is not None and side is not None
    assert queued.fingerprint is not None
    raw_tc = game.header("TimeControl")
    tc = timecontrol.parse(raw_tc)
    return NewGame(
        fingerprint=queued.fingerprint,
        source=source.source,
        my_color=side,
        start_fen=game.start_fen,
        pgn=game.pgn,
        engine_name=analysed.analysis.engine_name,
        engine_depth=analysed.analysis.depth,
        site_label=source.label,
        external_id=source.url or source.game_id,
        white=game.header("White"),
        black=game.header("Black"),
        white_elo=pgn.parse_int(game.header("WhiteElo")),
        black_elo=pgn.parse_int(game.header("BlackElo")),
        result=game.result,
        played_on=pgn.parse_date(game.header("Date")),
        time_control=raw_tc,
        tc_base_s=None if tc is None else tc.base_s,
        tc_inc_s=None if tc is None else tc.inc_s,
        speed=None if tc is None else timecontrol.speed(tc),
        opening=game.header("Opening"),
        eco=game.header("ECO"),
        has_clocks=game.has_clocks,
    )


def new_blunder(found: FoundBlunder) -> NewBlunder:
    """The ``blunders`` row for one finding: everything the machine fills in."""
    f, h = found.finding, found.hints
    return NewBlunder(
        ply=f.ply.index,
        move_no=f.ply.move_no,
        fen_before=f.ply.fen_before,
        played_uci=f.ply.uci,
        played_san=f.ply.san,
        best_uci=f.best_uci,
        best_san=f.best_san,
        best_line_san=f.best_line_san,
        accept_uci=f.accept_uci,
        eval_before=f.eval_before,
        eval_after=f.eval_after,
        swing=f.swing,
        judgment=f.judgment,
        refutation_san=f.refutation_san,
        clock_left_s=h.clock_left_s,
        time_spent_s=h.time_spent_s,
        auto_causes=h.causes,
    )


def summary(queue: Iterable[QueuedGame], saved: Iterable[SavedGame]) -> str:
    """``"4 games read · 1 skipped (duplicate) · 1 needs side · 3 blunders added"``."""
    queue = tuple(queue)
    blunders = sum(len(s.blunder_ids) for s in saved)
    statuses = [q.status for q in queue]
    parts = [_count(len(queue), "game") + " read"]
    if n := statuses.count("duplicate"):
        parts.append(f"{n} skipped (duplicate)")
    if n := statuses.count("needs_side"):
        parts.append(f"{n} {'needs' if n == 1 else 'need'} side")
    if n := statuses.count("error"):
        parts.append(_count(n, "error"))
    parts.append(f"{_count(blunders, 'blunder')} added")
    return " \N{MIDDLE DOT} ".join(parts)


def _count(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"
