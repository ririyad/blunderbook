"""Which side you played (CLAUDE.md §7.3), and a game's fingerprint for dedupe (§7.4)."""

import hashlib
from collections.abc import Iterable, Mapping
from typing import Final

import chess

from blunderbook.core.models import Color, ParsedGame, SourceInfo, header_value
from blunderbook.core.pgn import parse_date

FINGERPRINT_PLIES: Final = 30


def normalize_name(name: str) -> str:
    """Trimmed and case-insensitive: ``"  Rashed_Blitz "`` -> ``"rashed_blitz"``."""
    return name.strip().casefold()


def my_side(headers: Mapping[str, str], names: Iterable[str]) -> Color | None:
    """The side you played, or None when the game needs you to choose.

    ``names`` are your names and usernames (``my_names`` plus the Lichess and Chess.com
    usernames). None when neither player matches, and also when both do (for example two
    of your own accounts): the app never guesses.
    """
    mine = {normalize_name(n) for n in names if n.strip()}
    white = normalize_name(header_value(headers, "White") or "")
    black = normalize_name(header_value(headers, "Black") or "")
    is_white = bool(white) and white in mine
    is_black = bool(black) and black in mine
    if is_white == is_black:
        return None
    return "white" if is_white else "black"


def fingerprint(game: ParsedGame, source: SourceInfo) -> str:
    """sha1 hex digest identifying the game, so the same game is never imported twice.

    With a site game id: ``sha1("{source}:{game_id}")``. Otherwise
    ``sha1(lower(white) | lower(black) | date | first 30 SAN moves)``, where date is
    ``YYYY-MM-DD`` when the header is a full date, else the header as written. A game that
    doesn't start from the standard position also adds its start FEN, so two different
    positions with the same players, date and first move don't collide.
    """
    if source.game_id:
        key = f"{source.source}:{source.game_id}"
    else:
        raw_date = game.header("Date") or ""
        played = parse_date(raw_date)
        parts = [
            (game.header("White") or "").strip().lower(),
            (game.header("Black") or "").strip().lower(),
            played.isoformat() if played else raw_date,
            " ".join(p.san for p in game.plies[:FINGERPRINT_PLIES]),
        ]
        if game.start_fen != chess.STARTING_FEN:
            parts.append(game.start_fen)
        key = "|".join(parts)
    return hashlib.sha1(key.encode("utf-8"), usedforsecurity=False).hexdigest()
