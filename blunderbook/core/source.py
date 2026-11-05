"""Where a game came from (CLAUDE.md §7.5), plus its site game id for dedupe (§7.4).

- ``Site`` or ``Event`` contains "lichess" -> lichess; "chess.com" -> chesscom.
- ``Site`` present and not a URL or domain -> otb, "Over the board · {Site}".
- Otherwise -> pgn, "PGN file".
"""

import re
from collections.abc import Mapping
from typing import Final

from blunderbook.core.models import SourceInfo, header_value

# Lichess game ids are 8 letters/digits. A 12-character "full id" adds a 4-character player
# suffix, and links may end in /white or /black. Exports put https://lichess.org/<id> in Site.
_LICHESS_GAME: Final = re.compile(
    r"(?:https?://)?(?:www\.)?(?i:lichess\.org)/([A-Za-z0-9]{8})(?:[A-Za-z0-9]{4})?"
    r"(?:/(?:white|black))?/?(?:[?#].*)?"
)
# Lichess pages whose path happens to be 8 letters, e.g. Site "https://lichess.org/analysis"
# from the analysis board. They name no game.
_LICHESS_PAGES: Final = frozenset({"analysis", "practice", "training", "tutorial", "streamer"})

# Chess.com exports put the game URL in Link: https://www.chess.com/game/live/140512345678
# (or /game/daily/<id>). Analysis links contain the same path.
# TODO(verify): older exports may use https://www.chess.com/live/game/<id>; accepted too.
_CHESSCOM_GAME: Final = re.compile(
    r"(?<![a-z0-9\-])chess\.com/(?:\S*?/)?(?:game/(live|daily)|(live|daily)/game)/(\d+)",
    re.IGNORECASE,
)
# "chess.com" as a whole name: "playchess.com" (ChessBase's server) is a different site.
_CHESSCOM: Final = re.compile(r"(?<![a-z0-9\-])chess\.com\b", re.IGNORECASE)

_URL: Final = re.compile(r"[a-z][a-z0-9+.\-]*://", re.IGNORECASE)
# "playchess.com", "www.chess24.com/en". The top-level domain must be lowercase, so a place
# written "St.Louis" still counts as over the board.
_DOMAIN: Final = re.compile(r"(?i:(?:www\.)?[a-z0-9\-]+(?:\.[a-z0-9\-]+)*)\.[a-z]{2,24}(?:/\S*)?")


def detect_source(headers: Mapping[str, str]) -> SourceInfo:
    """Source, display label and (for Lichess and Chess.com) the site game id and URL."""
    site = header_value(headers, "Site") or ""
    event = header_value(headers, "Event") or ""
    where = f"{site} {event}"

    if "lichess" in where.lower():
        match = _LICHESS_GAME.fullmatch(site)
        if match is None or match[1] in _LICHESS_PAGES:
            return SourceInfo("lichess", "Lichess")
        game_id = match[1]
        return SourceInfo("lichess", "Lichess", game_id, f"https://lichess.org/{game_id}")

    if _CHESSCOM.search(where):
        for text in (header_value(headers, "Link") or "", site):
            found = _CHESSCOM_GAME.search(text)
            if found:
                kind = (found[1] or found[2]).lower()
                game_id = f"{kind}/{found[3]}"
                return SourceInfo(
                    "chesscom", "Chess.com", game_id, f"https://www.chess.com/game/{game_id}"
                )
        return SourceInfo("chesscom", "Chess.com")

    if site and not _URL.match(site) and not _DOMAIN.fullmatch(site):
        return SourceInfo("otb", f"Over the board · {site}")
    return SourceInfo("pgn", "PGN file")
