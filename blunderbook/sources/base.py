"""What every sync adapter provides (CLAUDE.md §8): PGN text, nothing else. The importer does
the rest, so a site changing its API only breaks its own adapter."""

from collections.abc import Iterable, Iterator
from datetime import datetime
from typing import Final, Protocol

import httpx

from blunderbook import __version__

USER_AGENT: Final = f"Blunderbook/{__version__} (local chess mistake library)"
# HTTP 429: both sites' docs say to slow down. Lichess: "waiting one minute before retrying".
WAIT_429_S: Final = 60.0
LONGEST_WAIT_S: Final = 300.0  # a longer Retry-After stops the sync instead of hanging it
TRIES: Final = 3  # requests in all, for one URL


class SyncError(Exception):
    """A sync that can't go on. The message is plain, ready to show, and holds no token."""


class SourceAdapter(Protocol):
    name: str  # 'lichess' | 'chesscom'

    def fetch_new_pgn(self, since: datetime | None) -> Iterator[str]:
        """The PGN of each game played since `since` (all games when None), one game per
        item, oldest first where the site allows. Raises SyncError."""
        ...


def redact(text: str, *secrets: str) -> str:
    """`text` with every non-empty secret replaced, for error messages (CLAUDE.md §6)."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[token]")
    return text


def games_in(lines: Iterable[str]) -> Iterator[str]:
    """Cut a stream of PGN lines into one text per game, as the lines arrive.

    Only chunking, for progress: each piece is still parsed by `core.pgn` with python-chess.
    A game starts at a header line (`[...`) that comes after some movetext. Movetext never
    starts with `[`: it starts with a move number, a move, a comment or a result.
    """
    game: list[str] = []
    moves_seen = False
    for raw in lines:
        line = raw.rstrip("\r\n")
        stripped = line.strip()
        if stripped.startswith("[") and moves_seen:
            yield _joined(game)
            game, moves_seen = [], False
        if stripped and not stripped.startswith("["):
            moves_seen = True
        if stripped or game:
            game.append(line)
    if any(line.strip() for line in game):
        yield _joined(game)


def _joined(lines: list[str]) -> str:
    return "\n".join(lines).strip() + "\n"


def wait_for(response: httpx.Response) -> float:
    """How long to wait after a 429: Retry-After if it says longer, else one minute."""
    try:
        asked = float(response.headers.get("Retry-After", "0"))
    except ValueError:
        asked = 0.0
    return max(WAIT_429_S, asked)
