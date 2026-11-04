"""Parse PGN ``TimeControl`` headers and classify game speed (CLAUDE.md §7.2)."""

from __future__ import annotations

import re
from typing import Final

from blunderbook.core.models import Speed, TimeControl

# "180" or "180+2", the whole string. Anything else (e.g. "-", "?", Chess.com daily
# "1/86400", multi-period "40/7200:3600", sandclock "*60") is unknown: speed stays None.
_SIMPLE: Final = re.compile(r"(\d+)(?:\+(\d+))?")

# Upper bounds (exclusive) of the estimate base + 40 * inc, in seconds.
_BULLET_BELOW: Final = 180
_BLITZ_BELOW: Final = 480
_RAPID_BELOW: Final = 1500


def parse(raw: str | None) -> TimeControl | None:
    """``"180+2"`` -> ``TimeControl(180, 2)``. Missing or unrecognised -> ``None``."""
    if raw is None:
        return None
    match = _SIMPLE.fullmatch(raw.strip())
    if match is None:
        return None
    base, inc = match.groups()
    return TimeControl(base_s=int(base), inc_s=int(inc or 0))


def speed(tc: TimeControl) -> Speed:
    """Classify from the estimated game length ``base + 40 * inc``."""
    estimate = tc.base_s + 40 * tc.inc_s
    if estimate < _BULLET_BELOW:
        return "bullet"
    if estimate < _BLITZ_BELOW:
        return "blitz"
    if estimate < _RAPID_BELOW:
        return "rapid"
    return "classical"


def label(tc: TimeControl) -> str:
    """Display label with the base in minutes: ``180+2`` -> ``"3+2"``, ``90+0`` -> ``"1.5+0"``."""
    if tc.base_s % 60 == 0:
        minutes = str(tc.base_s // 60)
    else:
        minutes = f"{tc.base_s / 60:.2f}".rstrip("0").rstrip(".")
    return f"{minutes}+{tc.inc_s}"
