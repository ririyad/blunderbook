"""The import pipeline: PGN text -> games -> analysis -> blunders (CLAUDE.md §7, §9).

1. :func:`prepare` reads the text and puts each game in the queue as ``ready``,
   ``needs_side``, ``duplicate`` or ``error``. No engine is needed for this step.
2. :func:`analyse` runs one ready game through the engine and the suggested causes.

Storage arrives in M2. Until then the CLI prints the report and saves nothing.
"""

from collections.abc import Container, Iterable
from dataclasses import dataclass, replace
from typing import Literal

from blunderbook.core import engine, hints, identity, pgn, timecontrol
from blunderbook.core.models import (
    Color,
    Finding,
    GameAnalysis,
    ParsedGame,
    SourceInfo,
    Thresholds,
    header_value,
)
from blunderbook.core.source import detect_source

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


def summary(queue: Iterable[QueuedGame], analysed: Iterable[AnalysedGame], verb: str) -> str:
    """``"4 games read · 1 skipped (duplicate) · 1 needs side · 3 blunders found"``.

    ``verb`` is "found" until storage exists (M2), then "added".
    """
    queue = tuple(queue)
    blunders = sum(len(a.blunders) for a in analysed)
    statuses = [q.status for q in queue]
    parts = [_count(len(queue), "game") + " read"]
    if n := statuses.count("duplicate"):
        parts.append(f"{n} skipped (duplicate)")
    if n := statuses.count("needs_side"):
        parts.append(f"{n} {'needs' if n == 1 else 'need'} side")
    if n := statuses.count("error"):
        parts.append(_count(n, "error"))
    parts.append(f"{_count(blunders, 'blunder')} {verb}")
    return " \N{MIDDLE DOT} ".join(parts)


def _count(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"
