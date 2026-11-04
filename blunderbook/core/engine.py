"""Stockfish wrapper (CLAUDE.md §7.6).

For now this only checks that a program is Stockfish and reads its version. The
analysis passes arrive in slice 1.7.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import chess.engine

MIN_STOCKFISH_MAJOR: Final = 17

_VERSION: Final = re.compile(r"Stockfish (\d+)(?:\.(\d+))?\b")


class EngineError(Exception):
    """The engine couldn't be started or used. The message is safe to show as is."""


@dataclass(frozen=True, slots=True)
class EngineInfo:
    """What the engine reported in its UCI ``id name`` line."""

    name: str  # e.g. "Stockfish 17.1"
    major: int | None  # None for dev builds such as "Stockfish dev-20260901-..."
    minor: int | None

    @property
    def outdated(self) -> bool:
        return self.major is not None and self.major < MIN_STOCKFISH_MAJOR

    @property
    def dev_build(self) -> bool:
        return self.major is None


def probe(command: str | Sequence[str], timeout: float = 10.0) -> EngineInfo:
    """Start the engine, read its name, and close it.

    Raises EngineError if it can't start, doesn't speak UCI, is too slow to answer, or
    isn't Stockfish. Every game is judged by the same engine (CLAUDE.md §1.5).
    """
    cmd = command if isinstance(command, str) else list(command)
    try:
        with chess.engine.SimpleEngine.popen_uci(cmd, timeout=timeout) as engine:
            name = engine.id.get("name", "").strip()
    except FileNotFoundError:
        raise EngineError("The program wasn't found.") from None
    except PermissionError:
        raise EngineError("You don't have permission to run this program.") from None
    except TimeoutError:
        raise EngineError(
            f"It didn't answer within {timeout:g} s, so it may not be a chess engine."
        ) from None
    except chess.engine.EngineError, chess.engine.EngineTerminatedError, OSError:
        raise EngineError("It didn't respond like a UCI chess engine.") from None

    if not name.startswith("Stockfish"):
        shown = name or "an unnamed engine"
        raise EngineError(f"This is {shown}, not Stockfish. Blunderbook only uses Stockfish.")
    match = _VERSION.match(name)
    if match is None:
        return EngineInfo(name=name, major=None, minor=None)
    major, minor = match.groups()
    return EngineInfo(name=name, major=int(major), minor=int(minor) if minor else None)
