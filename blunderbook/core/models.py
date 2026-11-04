"""Shared types for the core.

Records that a later slice produces (parsed games, analysis findings, stored blunders)
are added by that slice, next to the code that fills them in.
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
