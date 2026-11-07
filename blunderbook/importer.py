"""The import pipeline: PGN text -> games -> analysis -> blunders (CLAUDE.md §7, §9).

1. :func:`prepare` reads the text and puts each game in the queue as ``ready``,
   ``needs_side``, ``duplicate`` or ``error``. No engine is needed for this step.
2. :func:`analyse` runs one ready game through the engine and the suggested causes.
3. :func:`save` stores the analysed game and its blunders in one transaction.

Only analysed games are saved (CLAUDE.md §7.4). Each is saved as soon as it's analysed, so
if the engine stops, the games before it are kept and importing the file again finishes
the rest.
"""

import re
import sqlite3
from collections.abc import Callable, Container, Iterable, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Final, Literal

import chess
import chess.pgn

from blunderbook.core import detect, engine, hints, identity, pgn, timecontrol
from blunderbook.core.models import (
    Batch,
    Color,
    Finding,
    GameAnalysis,
    Judgment,
    NewBlunder,
    NewGame,
    ParsedGame,
    SavedIds,
    SourceInfo,
    Thresholds,
    header_value,
)
from blunderbook.core.source import detect_source
from blunderbook.db import repo

GameStatus = Literal["ready", "needs_side", "duplicate", "error"]
SideFrom = Literal["names", "option", "position"]  # "position": the side to move in a FEN

ALREADY_IMPORTED = "Already imported \N{EM DASH} skipped"
FEN_LABEL = "FEN entry"


class FenError(ValueError):
    """A FEN or move that can't be logged, with a message ready to show."""


@dataclass(frozen=True, slots=True)
class QueuedGame:
    """One game of the file, in file order, with what happens to it next."""

    number: int  # 1-based position in the file
    status: GameStatus
    headers: frozendict[str, str]
    game: ParsedGame | None = None  # None when the game couldn't be read
    source: SourceInfo | None = None
    fingerprint: str | None = None
    side: Color | None = None  # set when ready
    side_from: SideFrom | None = None
    reason: str | None = None  # why it's an error or a duplicate
    warnings: tuple[str, ...] = ()

    def header(self, name: str) -> str | None:
        return header_value(self.headers, name)

    @property
    def players(self) -> str:
        return f"{self.header('White') or '?'} vs {self.header('Black') or '?'}"

    @property
    def date(self) -> str | None:
        """``YYYY-MM-DD`` when the header is a full date."""
        played = pgn.parse_date(self.header("Date"))
        return played.isoformat() if played else None


@dataclass(frozen=True, slots=True)
class FoundBlunder:
    finding: Finding
    hints: hints.Hints


@dataclass(frozen=True, slots=True)
class AnalysedGame:
    queued: QueuedGame
    analysis: GameAnalysis
    blunders: tuple[FoundBlunder, ...]


@dataclass(frozen=True, slots=True)
class SavedGame:
    analysed: AnalysedGame
    game_id: int
    blunder_ids: tuple[int, ...]  # one per analysed.blunders, same order


def prepare(
    text: str,
    names: Iterable[str],
    *,
    side: Color | None = None,
    known: Container[str] = frozenset(),
) -> tuple[QueuedGame, ...]:
    """Read ``text`` and queue every game in it, in file order.

    ``names`` are your names and usernames. ``side`` is used for games where they match
    neither player (or both). ``known`` holds fingerprints already imported. A game that
    repeats an earlier one in the same text is a duplicate too.
    """
    names = tuple(names)
    parsed = pgn.parse(text)
    queue: list[QueuedGame] = [
        QueuedGame(p.number, "error", p.headers, reason=p.reason) for p in parsed.problems
    ]
    seen: dict[str, int] = {}
    for game in parsed.games:
        source = detect_source(game.headers)
        fp = identity.fingerprint(game, source)
        base = QueuedGame(
            game.number,
            "ready",
            game.headers,
            game=game,
            source=source,
            fingerprint=fp,
            warnings=game.warnings,
        )
        if fp in known:
            queue.append(replace(base, status="duplicate", reason=ALREADY_IMPORTED))
            continue
        if fp in seen:
            note = f"Same game as game {seen[fp]} \N{EM DASH} skipped"
            queue.append(replace(base, status="duplicate", reason=note))
            continue
        seen[fp] = game.number
        mine = identity.my_side(game.headers, names)
        if mine is not None:
            queue.append(replace(base, side=mine, side_from="names"))
        elif side is not None:
            queue.append(replace(base, side=side, side_from="option"))
        else:
            queue.append(replace(base, status="needs_side"))
    return tuple(sorted(queue, key=lambda q: q.number))


def analyse(
    queued: QueuedGame,
    analyser: engine.Analyser,
    *,
    depth: int,
    thresholds: Thresholds,
    progress: engine.Progress | None = None,
    flag_at: Judgment = "blunder",
) -> AnalysedGame:
    """Run the engine over a ready game and add the suggested causes to each blunder.
    ``flag_at`` is the lowest judgment that's logged: blunders for imports, anything from
    an inaccuracy up for a FEN entry."""
    if queued.status != "ready" or queued.game is None or queued.side is None:
        raise ValueError(f"Game {queued.number} isn't ready to analyse ({queued.status}).")
    game = queued.game
    analysis = engine.analyse_game(
        game,
        queued.side,
        analyser,
        depth=depth,
        thresholds=thresholds,
        progress=progress,
        flag_at=flag_at,
    )
    tc = timecontrol.parse(game.header("TimeControl"))
    found = tuple(FoundBlunder(f, hints.suggest(f, game, tc)) for f in analysis.findings)
    return AnalysedGame(queued, analysis, found)


def prepare_fen(
    fen: str,
    move: str,
    *,
    me: str | None = None,
    opponent: str | None = None,
    played_on: date | None = None,
) -> QueuedGame:
    """A FEN quick entry as a ready game: the position and the move you played, as a
    one-move game (CLAUDE.md §5). You're the side to move. ``move`` is UCI (``e2e4``,
    ``e7e8`` promotes to a queen) or SAN (``Nf3``). Raises :class:`FenError`."""
    board = _fen_board(fen)
    played = _fen_move(board, move)
    record = chess.pgn.Game()
    mine, theirs = _pgn_name(me), _pgn_name(opponent)
    white, black = (mine, theirs) if board.turn == chess.WHITE else (theirs, mine)
    record.headers["Event"] = FEN_LABEL
    record.headers["Date"] = played_on.strftime("%Y.%m.%d") if played_on else "????.??.??"
    record.headers["White"] = white
    record.headers["Black"] = black
    record.setup(board)
    record.add_main_variation(played)
    (game,) = pgn.parse(str(record)).games  # the move was checked, so this reads back
    source = SourceInfo("fen", FEN_LABEL)
    return QueuedGame(
        1,
        "ready",
        game.headers,
        game=game,
        source=source,
        fingerprint=identity.fingerprint(game, source),
        side="white" if board.turn == chess.WHITE else "black",
        side_from="position",
    )


_STATUS_PROBLEMS = (
    (chess.STATUS_EMPTY, "the board is empty"),
    (chess.STATUS_NO_WHITE_KING, "White has no king"),
    (chess.STATUS_NO_BLACK_KING, "Black has no king"),
    (chess.STATUS_TOO_MANY_KINGS, "there are too many kings"),
    (chess.STATUS_OPPOSITE_CHECK, "the side not to move is in check"),
    (chess.STATUS_PAWNS_ON_BACKRANK, "a pawn is on the first or last rank"),
    (chess.STATUS_BAD_CASTLING_RIGHTS, "the castling rights don't match the kings and rooks"),
    (chess.STATUS_INVALID_EP_SQUARE, "the en passant square doesn't fit the position"),
)


def _fen_board(fen: str) -> chess.Board:
    fields = fen.split()
    if len(fields) < 2:
        raise FenError(
            "The FEN needs the side to move after the pieces, for example "
            "'... w - - 0 1' for White or '... b - - 0 1' for Black."
        )
    try:
        board = chess.Board(" ".join(fields))
    except ValueError as exc:
        raise FenError(f"That FEN can't be read: {exc}.") from exc
    status = board.status()
    if status != chess.STATUS_VALID:
        reasons = [text for flag, text in _STATUS_PROBLEMS if status & flag]
        why = "; ".join(reasons) or "the pieces can't get there in a real game"
        raise FenError(f"That position can't happen in a game: {why}.")
    if not any(board.legal_moves):
        raise FenError("There are no legal moves in that position (the game is over).")
    return board


def _fen_move(board: chess.Board, text: str) -> chess.Move:
    text = text.strip()
    attempts = [lambda: board.parse_uci(text), lambda: board.parse_san(text)]
    if len(text) == 4:  # e7e8 without a piece: promote to a queen (CLAUDE.md §7.8)
        attempts.insert(1, lambda: board.parse_uci(text + "q"))
    for attempt in attempts:
        try:
            move = attempt()
        except ValueError:
            continue
        if move and move in board.legal_moves:  # a null move ("0000", "--") is falsy
            return move
    side = "White" if board.turn == chess.WHITE else "Black"
    raise FenError(f"{text or 'That'} isn't a legal move in that position. {side} is to move.")


PASTED: Final = "Pasted PGN"
LONGEST_LABEL: Final = 200


def file_batch(name: str | None) -> Batch:
    """The import of a file called ``name`` (a path, or just its name), or of pasted text
    when there's no name. Folders are dropped, and so are control characters."""
    base = re.split(r"[\\/]", name or "")[-1]
    label = re.sub(r"[\x00-\x1f\x7f]", "", re.sub(r"\s+", " ", base)).strip()
    if not label:
        return Batch(PASTED, "paste")
    return Batch(label[:LONGEST_LABEL], "file")


def sync_batch(site_label: str) -> Batch:
    """The import of a sync: "Lichess sync", "Chess.com sync"."""
    return Batch(f"{site_label} sync", "sync")


def _pgn_name(name: str | None) -> str:
    """A name safe inside a PGN header: python-chess doesn't escape quotes."""
    cleaned = re.sub(r"\s+", " ", (name or "").replace('"', "'").replace("\\", "/")).strip()
    return cleaned or "?"


def save(
    conn: sqlite3.Connection,
    analysed: AnalysedGame,
    *,
    now: datetime | None = None,
    import_id: int | None = None,
) -> SavedGame | None:
    """Store an analysed game and its blunders, with the import it came from. None when
    the game was saved meanwhile (by another import running at the same time): nothing is
    written then."""
    ids = repo.add_game(
        conn,
        new_game(analysed),
        [new_blunder(b) for b in analysed.blunders],
        now=now,
        import_id=import_id,
    )
    if ids is None:
        return None
    return SavedGame(analysed, ids.game_id, ids.blunder_ids)


def new_game(analysed: AnalysedGame) -> NewGame:
    """The ``games`` row for an analysed game. Unknown headers stay None."""
    queued = analysed.queued
    game, source, side = queued.game, queued.source, queued.side
    assert game is not None and source is not None and side is not None
    assert queued.fingerprint is not None
    raw_tc = game.header("TimeControl")
    tc = timecontrol.parse(raw_tc)
    return NewGame(
        fingerprint=queued.fingerprint,
        source=source.source,
        my_color=side,
        start_fen=game.start_fen,
        pgn=game.pgn,
        engine_name=analysed.analysis.engine_name,
        engine_depth=analysed.analysis.depth,
        site_label=source.label,
        external_id=source.url or source.game_id,
        white=game.header("White"),
        black=game.header("Black"),
        white_elo=pgn.parse_int(game.header("WhiteElo")),
        black_elo=pgn.parse_int(game.header("BlackElo")),
        result=game.result,
        played_on=pgn.parse_date(game.header("Date")),
        time_control=raw_tc,
        tc_base_s=None if tc is None else tc.base_s,
        tc_inc_s=None if tc is None else tc.inc_s,
        speed=None if tc is None else timecontrol.speed(tc),
        opening=game.header("Opening"),
        eco=game.header("ECO"),
        has_clocks=game.has_clocks,
    )


def new_blunder(found: FoundBlunder) -> NewBlunder:
    """The ``blunders`` row for one finding: everything the machine fills in."""
    f, h = found.finding, found.hints
    return NewBlunder(
        ply=f.ply.index,
        move_no=f.ply.move_no,
        fen_before=f.ply.fen_before,
        played_uci=f.ply.uci,
        played_san=f.ply.san,
        best_uci=f.best_uci,
        best_san=f.best_san,
        best_line_san=f.best_line_san,
        accept_uci=f.accept_uci,
        eval_before=f.eval_before,
        eval_after=f.eval_after,
        swing=f.swing,
        judgment=f.judgment,
        refutation_san=f.refutation_san,
        clock_left_s=h.clock_left_s,
        time_spent_s=h.time_spent_s,
        auto_causes=h.causes,
    )


# ---------------------------------------------------------------- running an import

# Given a ready game, its place among the ready games and how many there are, the progress
# reporter for that game: ``with progress_for(game, k, n) as report: ... report(done, total)``.
ProgressFor = Callable[[QueuedGame, int, int], AbstractContextManager[engine.Progress | None]]


class Stopped(Exception):
    """Raised inside :func:`run` when ``should_stop()`` says so, between positions."""


@dataclass(frozen=True, slots=True)
class RunResult:
    queue: tuple[QueuedGame, ...]  # in file order; a game saved meanwhile is now a duplicate
    saved: dict[int, SavedGame]  # by game number, each saved as soon as it was analysed
    error: str | None = None  # why the engine stopped, ready to show
    stopped: bool = False  # should_stop() asked to stop

    @property
    def finished(self) -> bool:
        return self.error is None and not self.stopped


def run(
    conn: sqlite3.Connection,
    queue: Sequence[QueuedGame],
    analyser: engine.Analyser,
    *,
    depth: int,
    thresholds: Thresholds,
    progress_for: ProgressFor | None = None,
    should_stop: Callable[[], bool] | None = None,
    batch: Batch | None = None,
) -> RunResult:
    """Analyse and save each ready game of ``queue``, one by one (CLAUDE.md §7.4, §7.6).

    ``batch`` names the import (the file, a paste, a sync). It's remembered when the first
    game is saved, so an import that adds nothing leaves no trace in the Games list.

    Each game is saved as soon as it's analysed. If the engine fails, or ``should_stop()``
    turns true (checked after each position), the games before it stay saved, the game being
    analysed isn't, and importing the same text again finishes the rest.
    """
    games = list(queue)
    where = {q.number: i for i, q in enumerate(games)}
    ready = [q for q in games if q.status == "ready"]
    saved: dict[int, SavedGame] = {}
    import_id: int | None = None

    def result(error: str | None = None, stopped: bool = False) -> RunResult:
        return RunResult(tuple(games), saved, error, stopped)

    for k, queued in enumerate(ready, start=1):
        if should_stop is not None and should_stop():
            return result(stopped=True)
        reporter = (progress_for or _no_progress)(queued, k, len(ready))
        try:
            with reporter as report:
                analysed = analyse(
                    queued,
                    analyser,
                    depth=depth,
                    thresholds=thresholds,
                    progress=_progress(report, should_stop),
                )
        except Stopped:
            return result(stopped=True)
        except engine.EngineError as exc:
            return result(error=str(exc))
        if batch is not None and import_id is None:
            import_id = repo.add_import(conn, batch)
        done = save(conn, analysed, import_id=import_id)
        if done is None:  # another import saved it meanwhile
            games[where[queued.number]] = replace(
                queued, status="duplicate", reason=ALREADY_IMPORTED
            )
        else:
            saved[queued.number] = done
    return result()


def _no_progress(queued: QueuedGame, k: int, n: int) -> AbstractContextManager[None]:
    return nullcontext()


def _progress(
    report: engine.Progress | None, should_stop: Callable[[], bool] | None
) -> engine.Progress | None:
    if should_stop is None:
        return report

    def hook(done: int, total: int) -> None:
        if report is not None:
            report(done, total)
        if should_stop():
            raise Stopped

    return hook


# ---------------------------------------------------------------- FEN quick entry

FenResult = Literal["logged", "already_logged", "best_move", "not_a_mistake"]
MARKS: dict[Judgment, str] = {"blunder": "??", "mistake": "?", "inaccuracy": "?!"}


@dataclass(frozen=True, slots=True)
class FenOutcome:
    """What happened to a FEN quick entry, with a message ready to show."""

    result: FenResult
    message: str
    entry_id: int | None = None  # the new entry, or the one logged earlier
    saved: SavedGame | None = None  # when logged


def find_logged(conn: sqlite3.Connection, queued: QueuedGame) -> FenOutcome | None:
    """The outcome when this position, move, opponent and date are already logged; checked
    before Stockfish runs. None when it's new."""
    assert queued.fingerprint is not None
    earlier = repo.find_saved(conn, queued.fingerprint)
    return None if earlier is None else _already_logged(queued, earlier)


def log_fen(
    conn: sqlite3.Connection,
    queued: QueuedGame,
    analyser: engine.Analyser,
    *,
    depth: int,
    thresholds: Thresholds,
) -> FenOutcome:
    """Analyse a FEN quick entry (from :func:`prepare_fen`) and save it when the move costs
    at least an inaccuracy. Stockfish's own choice, or a move under the inaccuracy line,
    isn't logged: there'd be nothing to re-test (CLAUDE.md §9)."""
    assert queued.game is not None and queued.side is not None
    label = queued.game.plies[0].label
    analysed = analyse(queued, analyser, depth=depth, thresholds=thresholds, flag_at="inaccuracy")
    if not analysed.blunders:
        evals = analysed.analysis.evals
        swing = detect.swing(evals[0], evals[1], queued.side)
        if swing >= thresholds.inaccuracy:  # not flagged, so it was the best move
            return FenOutcome(
                "best_move", f"{label} is Stockfish's own choice here. Nothing was logged."
            )
        return FenOutcome(
            "not_a_mistake",
            f"{label} isn't a mistake by Stockfish's measure (swing {swing:.2f}; "
            f"inaccuracies start at {thresholds.inaccuracy:.2f}). Nothing was logged.",
        )
    saved = save(conn, analysed)
    if saved is None:  # logged meanwhile by another command
        outcome = find_logged(conn, queued)
        assert outcome is not None
        return outcome
    (blunder,) = analysed.blunders
    (entry_id,) = saved.blunder_ids
    judgment = blunder.finding.judgment
    article = "an" if judgment == "inaccuracy" else "a"
    message = f"Logged {label}{MARKS[judgment]} as {article} {judgment}: entry #{entry_id}."
    return FenOutcome("logged", message, entry_id, saved)


def _already_logged(queued: QueuedGame, earlier: SavedIds) -> FenOutcome:
    assert queued.game is not None
    label = queued.game.plies[0].label
    entry_id = earlier.blunder_ids[0] if earlier.blunder_ids else None
    where = f" (entry #{entry_id})" if entry_id is not None else ""
    message = f"You've already logged {label} in this position{where}. Nothing was added."
    return FenOutcome("already_logged", message, entry_id)


# ---------------------------------------------------------------- report


def summary(queue: Iterable[QueuedGame], saved: Iterable[SavedGame]) -> str:
    """``"4 games read · 1 skipped (duplicate) · 1 needs side · 3 blunders added"``."""
    queue = tuple(queue)
    blunders = sum(len(s.blunder_ids) for s in saved)
    statuses = [q.status for q in queue]
    parts = [_count(len(queue), "game") + " read"]
    if n := statuses.count("duplicate"):
        parts.append(f"{n} skipped (duplicate)")
    if n := statuses.count("needs_side"):
        parts.append(f"{n} {'needs' if n == 1 else 'need'} side")
    if n := statuses.count("error"):
        parts.append(_count(n, "error"))
    parts.append(f"{_count(blunders, 'blunder')} added")
    return " \N{MIDDLE DOT} ".join(parts)


def _count(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"
