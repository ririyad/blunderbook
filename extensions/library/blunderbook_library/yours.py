"""Your entries in a Library entry's opening (ROADMAP 11.4), read from your Log.

A Log entry belongs to a Library entry when its game reaches the position at the end of the
entry's line. That's matched by position, not by the ECO header, so a typed-up OTB game with
no headers counts, and so does a game that got there by another move order. Positions are
compared without the move counters.

Pure: the route reads the Log through ``host.Log`` (read-only) and calls :func:`matches`.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache

import chess

from blunderbook.core import pgn
from blunderbook.core.models import Entry as LogEntry
from blunderbook_library import content


@dataclass(frozen=True, slots=True)
class Match:
    """One of your Log entries from a game that reached the Library entry's position."""

    log: LogEntry
    fell_in: bool  # you played one of the entry's losing replies, there
    on_line: bool  # your mistake was on the entry's line itself


def key(fen: str) -> str:
    """A position without its move counters: pieces, side to move, castling, en passant."""
    return " ".join(fen.split()[:4])


def matches(entry: content.Entry, log: Iterable[LogEntry]) -> list[Match]:
    """Your Log entries from games that reached ``entry``'s position, in the Log's order."""
    end = key(entry.end_fen)
    line = {key(fen) for fen in content.positions(entry.start_fen, entry.moves)}
    losing = {n.move.uci for n in entry.next if n.loses}
    found = []
    for item in log:
        if end not in game_positions(item.game.start_fen, item.game.pgn):
            continue
        b = item.blunder
        before = key(b.fen_before)
        found.append(
            Match(
                log=item,
                fell_in=before == end and _same_move(b.played_uci, losing),
                on_line=before in line,
            )
        )
    return found


@lru_cache(maxsize=4096)
def game_positions(start_fen: str, text: str) -> frozenset[str]:
    """Every position of a game's mainline, read again from its stored PGN (as core's game
    page does). Cached: a game's text never changes once it's saved."""
    parsed = pgn.parse(text).games
    if len(parsed) != 1:
        return frozenset({key(start_fen)})
    game = parsed[0]
    return frozenset({key(game.start_fen), *(key(p.fen_after) for p in game.plies)})


def _same_move(uci: str, moves: set[str]) -> bool:
    """The same from- and to-square: a promotion is matched whatever its piece."""
    try:
        played = chess.Move.from_uci(uci)
    except chess.InvalidMoveError:
        return False
    return any(
        (m.from_square, m.to_square) == (played.from_square, played.to_square)
        for m in map(chess.Move.from_uci, moves)
    )
