"""What a site's leaderboard holds, once read (ROADMAP 16.2): shared by
:mod:`blunderbook_rankings.lichess` and :mod:`blunderbook_rankings.chesscom`."""

from dataclasses import dataclass
from typing import Final

from blunderbook_rankings.net import RankingsError

MAX_NAME: Final = 50  # usernames are at most 30 characters on Lichess, 25 on Chess.com
MAX_TITLE: Final = 5  # "GM", "WCM", "BOT"


@dataclass(frozen=True, slots=True)
class SitePlayer:
    rank: int  # 1 is the top
    username: str
    title: str | None  # "GM", ...; None when there's none
    rating: int
    progress: int | None  # the site's own recent change (Lichess's progress, Chess.com's
    # trend), else None


class BadBoard(RankingsError):
    """A leaderboard that couldn't be read. Plain message."""


def text(value: object, longest: int) -> str | None:
    """A short, single-line string from a site's JSON, or None."""
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned[:longest] or None


def whole(value: object) -> int | None:
    """An integer from a site's JSON (never a bool), or None."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None
