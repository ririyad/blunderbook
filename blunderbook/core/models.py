"""Shared types for the core.

Records are added by the slice whose code fills them in: parsed games (1.4), analysis
findings (1.6+), stored blunders (M2).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal

Color = Literal["white", "black"]
Source = Literal["lichess", "chesscom", "pgn", "otb", "fen"]
Speed = Literal["bullet", "blitz", "rapid", "classical"]
Judgment = Literal["blunder", "mistake", "inaccuracy"]
Status = Literal["new", "solved", "missed"]

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
