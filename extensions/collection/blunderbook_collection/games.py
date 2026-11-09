"""Anyone's games, read and scored (ROADMAP 12.1). Pure: text in, dataclasses out; the
engine comes in as ``core.engine.Analyser``.

- :func:`prepare` reads PGN text with ``core.pgn`` and queues each game: ``ready`` to
  analyse, ``known`` (already analysed for another collection: added without the engine),
  ``member`` (already in this collection), ``duplicate`` (earlier in the same text) or
  ``error``. Nobody's side is needed: both players' moves are scored.
- :func:`score` is pass 1 (``core.engine.score_positions``) for one game: every position,
  with its eval (White POV), the engine's move and its line.
- :func:`info` is what's kept of the headers. Missing ones are None, never a failure.

The rules are core's (CLAUDE.md §7): the same parser, fingerprints, source detection and
engine pass, so a game is read and scored here as it would be for your Log.
"""

from collections.abc import Container
from dataclasses import dataclass, replace
from typing import Final, Literal

from blunderbook.core import engine, identity, pgn, timecontrol
from blunderbook.core.models import Eval, ParsedGame, Source, SourceInfo, Speed, header_value
from blunderbook.core.source import detect_source

Status = Literal["ready", "known", "member", "duplicate", "error"]

PV_PLIES: Final = 10  # how much of each engine line is kept
NAME_MAX: Final = 60


class BadName(ValueError):
    """A collection name that can't be used, with a message ready to show."""


def collection_name(value: str) -> str:
    """The name, trimmed. Raises :class:`BadName` when it's empty, too long, or has
    control characters."""
    name = " ".join(value.split())
    if not name:
        raise BadName("Give the collection a name.")
    if len(name) > NAME_MAX:
        raise BadName(f"A collection's name can be at most {NAME_MAX} characters.")
    if any(not ch.isprintable() for ch in name):
        raise BadName("A collection's name can't have control characters.")
    return name


@dataclass(frozen=True, slots=True)
class Queued:
    """One game of the text, in text order, with what happens to it next."""

    number: int  # 1-based, in the text
    status: Status
    headers: frozendict[str, str]
    game: ParsedGame | None = None  # None when it couldn't be read
    source: SourceInfo | None = None
    fingerprint: str | None = None
    reason: str | None = None  # why it's an error, a duplicate or a member
    warnings: tuple[str, ...] = ()

    def header(self, name: str) -> str | None:
        return header_value(self.headers, name)

    @property
    def players(self) -> str:
        return f"{self.header('White') or '?'} vs {self.header('Black') or '?'}"


def prepare(
    text: str,
    *,
    collection: str,
    analysed: Container[str] = frozenset(),
    members: Container[str] = frozenset(),
) -> tuple[Queued, ...]:
    """Queue every game of ``text`` for ``collection``. ``analysed`` holds the fingerprints
    of every game already in the database, ``members`` those already in this collection."""
    parsed = pgn.parse(text)
    queue = [Queued(p.number, "error", p.headers, reason=p.reason) for p in parsed.problems]
    seen: dict[str, int] = {}
    for game in parsed.games:
        source = detect_source(game.headers)
        fp = identity.fingerprint(game, source)
        base = Queued(
            game.number,
            "ready",
            game.headers,
            game=game,
            source=source,
            fingerprint=fp,
            warnings=game.warnings,
        )
        if fp in seen:
            note = f"Same game as game {seen[fp]} \N{EM DASH} skipped"
            queue.append(replace(base, status="duplicate", reason=note))
            continue
        seen[fp] = game.number
        if fp in members:
            note = f"Already in {collection} \N{EM DASH} skipped"
            queue.append(replace(base, status="member", reason=note))
        elif fp in analysed:
            queue.append(replace(base, status="known"))
        else:
            queue.append(base)
    return tuple(sorted(queue, key=lambda q: q.number))


# ---------------------------------------------------------------- scoring


@dataclass(frozen=True, slots=True)
class Position:
    """One position of a game and its pass-1 score."""

    ply: int  # 0 = the start, i = after ply i - 1
    fen: str
    move_uci: str | None  # the move that led here; None at 0
    move_san: str | None
    clock_s: float | None  # the mover's clock after that move
    score: Eval  # White POV
    best_uci: str | None  # the engine's move here; None when the game is over
    pv_uci: tuple[str, ...]  # its line, at most PV_PLIES


def score(
    game: ParsedGame,
    analyser: engine.Analyser,
    *,
    depth: int,
    progress: engine.Progress | None = None,
) -> tuple[Position, ...]:
    """Every position of ``game``, scored once at ``depth`` (pass 1, CLAUDE.md §7.6)."""
    lines = engine.score_positions(game, analyser, depth=depth, progress=progress)
    positions: list[Position] = []
    for i, line in enumerate(lines):
        ply = game.plies[i - 1] if i else None
        pv = tuple(move.uci() for move in line.pv[:PV_PLIES])
        positions.append(
            Position(
                ply=i,
                fen=ply.fen_after if ply else game.start_fen,
                move_uci=ply.uci if ply else None,
                move_san=ply.san if ply else None,
                clock_s=ply.clock_s if ply else None,
                score=line.score,
                best_uci=pv[0] if pv else None,
                pv_uci=pv,
            )
        )
    return tuple(positions)


# ---------------------------------------------------------------- headers


@dataclass(frozen=True, slots=True, kw_only=True)
class GameInfo:
    """What's kept of a game besides its positions. Unknown values are None."""

    fingerprint: str
    source: Source
    site_label: str
    external_id: str | None
    white: str | None
    black: str | None
    white_elo: int | None
    black_elo: int | None
    result: str | None
    date: str | None  # the header as written
    played_on: str | None  # YYYY-MM-DD for a full date
    event: str | None
    site: str | None
    round: str | None
    time_control: str | None
    tc_base_s: int | None
    tc_inc_s: int | None
    speed: Speed | None
    opening: str | None
    eco: str | None
    start_fen: str
    pgn: str
    plies: int


def info(queued: Queued) -> GameInfo:
    """The headers worth keeping, for a ``ready`` or ``known`` game."""
    game, source, fp = queued.game, queued.source, queued.fingerprint
    assert game is not None and source is not None and fp is not None
    tc = timecontrol.parse(game.header("TimeControl"))
    played = pgn.parse_date(game.header("Date"))
    return GameInfo(
        fingerprint=fp,
        source=source.source,
        site_label=source.label,
        external_id=source.game_id,
        white=_known(game.header("White")),
        black=_known(game.header("Black")),
        white_elo=pgn.parse_int(game.header("WhiteElo")),
        black_elo=pgn.parse_int(game.header("BlackElo")),
        result=game.result,
        date=_known(game.header("Date")),
        played_on=played.isoformat() if played else None,
        event=_known(game.header("Event")),
        site=_known(game.header("Site")),
        round=_known(game.header("Round")),
        time_control=_known(game.header("TimeControl")),
        tc_base_s=tc.base_s if tc else None,
        tc_inc_s=tc.inc_s if tc else None,
        speed=timecontrol.speed(tc) if tc else None,
        opening=_known(game.header("Opening")),
        eco=_known(game.header("ECO")),
        start_fen=game.start_fen,
        pgn=game.pgn,
        plies=len(game.plies),
    )


def _known(value: str | None) -> str | None:
    """None for a missing header and for the PGN's unknown marks ("?", "-", "????.??.??")."""
    if value is None:
        return None
    value = value.strip()
    return None if not value or set(value) <= set("?-.") else value
