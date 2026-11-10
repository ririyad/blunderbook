"""Shared types for the core.

Records are added by the slice whose code fills them in: parsed games (1.4), analysis
findings (1.6+), stored games and blunders (2.2).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final, Literal

Color = Literal["white", "black"]
Source = Literal["lichess", "chesscom", "pgn", "otb", "fen"]
Speed = Literal["bullet", "blitz", "rapid", "classical"]
Judgment = Literal["blunder", "mistake", "inaccuracy", "missed"]  # "missed": a missed win
JUDGMENT_NOUN: Final[Mapping[Judgment, str]] = {  # "Logged 30. h3 as a missed win"
    "blunder": "a blunder",
    "mistake": "a mistake",
    "inaccuracy": "an inaccuracy",
    "missed": "a missed win",
}
Status = Literal["new", "solved", "missed"]
AnalysisStatus = Literal["pending", "running", "done", "error"]
ImportKind = Literal["file", "paste", "sync"]
Outcome = Literal["won", "lost", "drawn"]

# Fixed order everywhere: UI chips, print page, Patterns (CLAUDE.md §5).
CAUSES: Final[tuple[str, ...]] = (
    "Hung a piece",
    "Missed their threat",
    "Missed my tactic",
    "Miscalculated a line",
    "Time trouble",
    "Moved too fast",
    "Wrong plan",
    "Opening gap",
    "Endgame technique",
    "Overconfident / tilt",
    "Skipped blunder check",
    "Other",
)


@dataclass(frozen=True, slots=True)
class TimeControl:
    """A parsed ``TimeControl`` header: base time and increment, in seconds."""

    base_s: int
    inc_s: int


@dataclass(frozen=True, slots=True)
class Eval:
    """An engine score from White's point of view. Exactly one of ``cp`` / ``mate`` is set.

    ``mate > 0``: White mates in N. ``mate < 0``: Black mates in N.
    ``mate == 0``: the side to move in that position is already checkmated. The number
    carries no sign, so whoever reads it takes the losing side from the position.

    Stored as JSON exactly like ``{"cp": 36}`` or ``{"mate": -2}``.
    """

    cp: int | None = None
    mate: int | None = None

    def __post_init__(self) -> None:
        if (self.cp is None) == (self.mate is None):
            raise ValueError("Eval needs exactly one of cp or mate")
        for value in (self.cp, self.mate):
            if value is not None and type(value) is not int:
                raise TypeError(f"Eval values must be int, got {type(value).__name__}")

    def to_dict(self) -> dict[str, int]:
        if self.mate is not None:
            return {"mate": self.mate}
        assert self.cp is not None
        return {"cp": self.cp}

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> Eval:
        keys = set(data)
        if keys == {"cp"}:
            return cls(cp=_as_int(data["cp"]))
        if keys == {"mate"}:
            return cls(mate=_as_int(data["mate"]))
        raise ValueError(f"Eval must have exactly one key, cp or mate: {dict(data)!r}")


def _as_int(value: object) -> int:
    if type(value) is not int:
        raise TypeError(f"Eval values must be int, got {type(value).__name__}")
    return value


@dataclass(frozen=True, slots=True)
class Thresholds:
    """Swing thresholds (0..1), the missed-win line and the re-test margin, from
    ``[thresholds]`` in config.toml."""

    inaccuracy: float = 0.05
    mistake: float = 0.10
    blunder: float = 0.15  # only >= blunder (and missed wins) are logged from imports
    accept_margin_cp: int = 60  # re-tests accept moves within this of the best
    missed_win_cp: int = 300  # an eval drop this big is a missed win; 0 turns them off


# ---------------------------------------------------------------- parsed PGN (core/pgn.py)

RESULTS: Final = frozenset({"1-0", "0-1", "1/2-1/2", "*"})


def header_value(headers: Mapping[str, str], name: str) -> str | None:
    """A header's value, or None when it's missing or unknown ("", "?", "????.??.??")."""
    value = headers.get(name, "").strip()
    if not value or set(value) <= {"?", "."}:
        return None
    return value


@dataclass(frozen=True, slots=True)
class Ply:
    """One half-move of a game's mainline."""

    index: int  # 0-based ply in this game (blunders.ply)
    move_no: int  # fullmove number shown to the user
    color: Color  # the side that played it
    san: str
    uci: str
    fen_before: str
    fen_after: str
    clock_s: float | None  # mover's clock after the move, from [%clk]; None if absent

    @property
    def label(self) -> str:
        """``"6. Nxd5"`` for White, ``"5... Bxd1"`` for Black."""
        dots = "." if self.color == "white" else "..."
        return f"{self.move_no}{dots} {self.san}"


@dataclass(frozen=True, slots=True)
class ParsedGame:
    """One game read from PGN text: headers, mainline, and its own verbatim text."""

    number: int  # 1-based position in the file, for the import report
    headers: frozendict[str, str]  # as written; python-chess fills missing ones with "?"
    start_fen: str
    plies: tuple[Ply, ...]
    pgn: str  # this game's text, verbatim apart from normalised line endings
    warnings: tuple[str, ...] = ()  # e.g. "Skipped unreadable text 'Ke9' at 2."

    def header(self, name: str) -> str | None:
        return header_value(self.headers, name)

    @property
    def has_clocks(self) -> bool:
        return any(p.clock_s is not None for p in self.plies)

    @property
    def result(self) -> str | None:
        value = self.header("Result")
        return value if value in RESULTS else None


@dataclass(frozen=True, slots=True)
class PgnProblem:
    """A game that couldn't be read. The import report shows ``reason``."""

    number: int
    reason: str
    headers: frozendict[str, str]
    pgn: str

    def header(self, name: str) -> str | None:
        return header_value(self.headers, name)


@dataclass(frozen=True, slots=True)
class ParsedPgn:
    """Everything read from one PGN text, in file order."""

    games: tuple[ParsedGame, ...]
    problems: tuple[PgnProblem, ...]


# ---------------------------------------------------------------- analysis (core/engine.py)


@dataclass(frozen=True, slots=True)
class Finding:
    """One flagged move of mine: everything the machine fills in for a blunder entry.

    Moves are UCI strings, lines are SAN text, scores are White POV (CLAUDE.md §7.6).
    """

    ply: Ply  # the move I played: index, move number, FENs, clock
    eval_before: Eval
    eval_after: Eval
    swing: float
    judgment: Judgment
    best_uci: str
    best_san: str
    best_line_san: str  # "6. e3 Be7 7. Bd3 c6 8. h3 Nf8"
    refutation_san: str | None  # "6... Nxd5 7. Bxd8 Bb4+"; None if the engine gave no line
    refutation_uci: tuple[str, ...]  # the engine line after my move, for suggested causes
    accept_uci: tuple[str, ...]  # moves a re-test accepts, best first
    best_pv_uci: tuple[str, ...] = ()  # the engine line before my move, for suggested causes


@dataclass(frozen=True, slots=True)
class GameAnalysis:
    """The result of analysing one game for one side."""

    engine_name: str  # e.g. "Stockfish 17.1", stored with the game
    depth: int
    evals: tuple[Eval, ...]  # positions 0..N: before ply 0, then after each ply
    findings: tuple[Finding, ...]  # flagged moves, in game order


# ---------------------------------------------------------------- source (core/source.py)


@dataclass(frozen=True, slots=True)
class SourceInfo:
    """Where a game came from, read from its headers (CLAUDE.md §7.5)."""

    source: Source  # never "fen": that's set by the FEN quick entry, not detected
    label: str  # "Lichess", "Chess.com", "Over the board · Dhaka Chess Club", "PGN file"
    game_id: str | None = None  # "abcd1234" (Lichess), "live/140512345678" (Chess.com)
    url: str | None = None  # canonical game URL when game_id is known


# ---------------------------------------------------------------- stored (db/repo.py)
# The New* records are what an import writes. The stored records add what the database
# keeps on top: ids, your notes, the re-test schedule and timestamps (CLAUDE.md §5).
# Dates you see are local; timestamps are UTC.


@dataclass(frozen=True, slots=True, kw_only=True)
class NewGame:
    """One analysed game, ready to save. Unknown headers are None."""

    fingerprint: str
    source: Source
    my_color: Color
    start_fen: str
    pgn: str  # the game's own text, verbatim
    engine_name: str  # e.g. "Stockfish 17.1"
    engine_depth: int
    site_label: str | None = None
    external_id: str | None = None  # site game id when known
    white: str | None = None
    black: str | None = None
    white_elo: int | None = None
    black_elo: int | None = None
    result: str | None = None
    played_on: date | None = None
    time_control: str | None = None  # raw header, e.g. "180+2"
    tc_base_s: int | None = None
    tc_inc_s: int | None = None
    speed: Speed | None = None
    opening: str | None = None
    eco: str | None = None
    has_clocks: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class Game(NewGame):
    id: int
    analysis_status: AnalysisStatus
    imported_at: datetime
    import_id: int | None = None  # None for FEN entries and games saved before 0003


@dataclass(frozen=True, slots=True)
class Batch:
    """An import about to save games: "blitz-week.pgn" (file), "Pasted PGN" (paste),
    "Lichess sync" (sync)."""

    label: str
    kind: ImportKind


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportInfo:
    """One saved import (a row in ``imports``)."""

    id: int
    label: str
    kind: ImportKind
    started_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class GameRow:
    """A game for the Games list: the import it came from and its entries by judgment."""

    game: Game
    batch: ImportInfo | None  # None for games saved before imports were remembered
    blunders: int
    mistakes: int
    inaccuracies: int
    missed: int  # missed wins


@dataclass(frozen=True, slots=True, kw_only=True)
class NewBlunder:
    """Everything the machine fills in for one entry (CLAUDE.md §7.6, §7.7)."""

    ply: int  # 0-based index of my move in the game
    move_no: int
    fen_before: str
    played_uci: str
    played_san: str
    best_uci: str
    best_san: str
    best_line_san: str
    accept_uci: tuple[str, ...]
    eval_before: Eval
    eval_after: Eval
    swing: float
    judgment: Judgment
    refutation_san: str | None = None
    clock_left_s: float | None = None
    time_spent_s: float | None = None
    auto_causes: tuple[str, ...] = ()  # suggestions only, in CAUSES order


@dataclass(frozen=True, slots=True, kw_only=True)
class Blunder(NewBlunder):
    """One entry: the machine's part, your notes, and its re-test schedule."""

    id: int
    game_id: int
    causes: tuple[str, ...]  # confirmed by you, in CAUSES order
    other_cause: str | None
    thinking: str
    lesson: str
    status: Status
    streak: int
    due_on: date
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class Entry:
    """A blunder with the game it came from, as the Log shows it."""

    blunder: Blunder
    game: Game


@dataclass(frozen=True, slots=True, kw_only=True)
class Attempt:
    """One re-test try (a row in ``retest_attempts``)."""

    id: int
    blunder_id: int
    attempted_at: datetime
    move_uci: str | None  # None when you gave up
    solved: bool
    used_hint: bool


@dataclass(frozen=True, slots=True)
class AttemptStats:
    """How often an entry was re-tested, and when last."""

    count: int
    last_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class Explanation:
    """A saved AI explanation of one entry (CLAUDE.md §7.10)."""

    blunder_id: int
    text: str
    model: str  # the OpenRouter model that wrote it
    prompt_version: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SavedIds:
    """The ids a saved game and its entries got, entries in the order they were given."""

    game_id: int
    blunder_ids: tuple[int, ...]


@dataclass(frozen=True, kw_only=True, slots=True)
class Totals:
    """How much a database holds, shown before a restore."""

    games: int  # imported games; a FEN entry's stand-in game doesn't count
    entries: int


# ---------------------------------------------------------------- sync (CLAUDE.md §8)

SyncSource = Literal["lichess", "chesscom"]


@dataclass(frozen=True, kw_only=True, slots=True)
class SyncState:
    """How far `blunderbook sync` got with one site (a row of `sync_state`)."""

    source: SyncSource
    username: str  # the account synced; another one starts again from the beginning
    last_synced: datetime | None  # when the newest game fetched was played (UTC)
    last_run_at: datetime | None
    last_error: str | None  # the last run's problem; None when it worked
