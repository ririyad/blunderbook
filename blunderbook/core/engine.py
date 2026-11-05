"""Stockfish wrapper and the two analysis passes (CLAUDE.md §7.6).

- :func:`probe` checks that a program is Stockfish and reads its version.
- :class:`Engine` is one running Stockfish process. Always use it as a context manager,
  so the process is closed even when analysis fails.
- :func:`analyse_game` runs pass 1 (every position, once) and pass 2 (MultiPV 3 on
  flagged positions only) and returns the findings for one side.

Scores leave this module as :class:`Eval` from White's point of view.
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from types import TracebackType
from typing import Final, Protocol, Self

import chess
import chess.engine

from blunderbook.core import detect
from blunderbook.core.models import (
    Color,
    Eval,
    Finding,
    GameAnalysis,
    Judgment,
    ParsedGame,
    Ply,
    Thresholds,
)

MIN_STOCKFISH_MAJOR: Final = 17
MULTIPV: Final = 3  # pass 2 asks for the top 3 moves

_VERSION: Final = re.compile(r"Stockfish (\d+)(?:\.(\d+))?\b")

Progress = Callable[[int, int], None]  # (positions done, total)


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


def version_note(info: EngineInfo) -> str | None:
    """A warning to show when the engine's version can't be trusted for our rules."""
    if info.outdated:
        return (
            f"Blunderbook expects Stockfish {MIN_STOCKFISH_MAJOR} or newer. "
            "Older versions can judge positions differently."
        )
    if info.dev_build:
        return "This looks like a development build, so its version can't be checked."
    return None


@dataclass(frozen=True, slots=True)
class Line:
    """One engine line: its score (White POV) and principal variation."""

    score: Eval
    pv: tuple[chess.Move, ...] = ()

    @property
    def move(self) -> chess.Move | None:
        """The line's first move; for pass 1, the engine's best move."""
        return self.pv[0] if self.pv else None


class Analyser(Protocol):
    """What :func:`analyse_game` needs from an engine. :class:`Engine` is the real one."""

    @property
    def name(self) -> str: ...

    def lines(
        self, board: chess.Board, depth: int, multipv: int = 1, *, game: object = None
    ) -> list[Line]: ...


# ---------------------------------------------------------------- the engine process


class Engine:
    """A running Stockfish. Open with :meth:`open`, inside a ``with`` block."""

    def __init__(self, simple: chess.engine.SimpleEngine, info: EngineInfo) -> None:
        self._simple = simple
        self.info = info
        self.closed = False

    @classmethod
    def open(
        cls,
        command: str | Sequence[str],
        *,
        threads: int | None = None,
        hash_mb: int | None = None,
        timeout: float = 10.0,
    ) -> Self:
        """Start the engine, check it's Stockfish, and apply Threads / Hash if given.

        Raises EngineError (with the process already closed) if any of that fails.
        """
        simple = _popen(command, timeout)
        try:
            info = _identify(simple.id.get("name", "").strip())
            _configure(simple, threads=threads, hash_mb=hash_mb)
        except BaseException:
            simple.close()
            raise
        return cls(simple, info)

    @property
    def name(self) -> str:
        return self.info.name

    def lines(
        self, board: chess.Board, depth: int, multipv: int = 1, *, game: object = None
    ) -> list[Line]:
        """Analyse ``board`` (with its move history) to ``depth``; best line first.

        ``game`` is any object identifying the game: the engine starts a new game
        (``ucinewgame``) whenever it changes.
        """
        try:
            infos = self._simple.analyse(
                board, chess.engine.Limit(depth=depth), multipv=multipv, game=game
            )
        except chess.engine.EngineTerminatedError:
            raise EngineError("Stockfish stopped unexpectedly.") from None
        except chess.engine.EngineError as exc:
            raise EngineError(f"Stockfish couldn't analyse a position: {exc}") from None
        return [_line(info) for info in infos if "score" in info]

    def close(self) -> None:
        self._simple.close()
        self.closed = True

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def probe(command: str | Sequence[str], timeout: float = 10.0) -> EngineInfo:
    """Start the engine, read its name, and close it.

    Raises EngineError if it can't start, doesn't speak UCI, is too slow to answer, or
    isn't Stockfish. Every game is judged by the same engine (CLAUDE.md §1.5).
    """
    with Engine.open(command, timeout=timeout) as engine:
        return engine.info


def _popen(command: str | Sequence[str], timeout: float) -> chess.engine.SimpleEngine:
    cmd = command if isinstance(command, str) else list(command)
    try:
        return chess.engine.SimpleEngine.popen_uci(cmd, timeout=timeout)
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


def _identify(name: str) -> EngineInfo:
    if not name.startswith("Stockfish"):
        shown = name or "an unnamed engine"
        raise EngineError(f"This is {shown}, not Stockfish. Blunderbook only uses Stockfish.")
    match = _VERSION.match(name)
    if match is None:
        return EngineInfo(name=name, major=None, minor=None)
    major, minor = match.groups()
    return EngineInfo(name=name, major=int(major), minor=int(minor) if minor else None)


def _configure(
    simple: chess.engine.SimpleEngine, *, threads: int | None, hash_mb: int | None
) -> None:
    wanted = {"Threads": threads, "Hash": hash_mb}
    options = {k: v for k, v in wanted.items() if v is not None and k in simple.options}
    if not options:
        return
    try:
        simple.configure(options)
    except chess.engine.EngineError as exc:
        raise EngineError(f"Stockfish didn't accept the settings: {exc}") from None
    except chess.engine.EngineTerminatedError:
        raise EngineError("Stockfish stopped unexpectedly.") from None


def _line(info: chess.engine.InfoDict) -> Line:
    score = info["score"].white()
    mate = score.mate()
    if mate is not None:
        value = Eval(mate=mate)
    else:
        cp = score.score()
        assert cp is not None  # a Cp score always has a value
        value = Eval(cp=cp)
    return Line(value, tuple(info.get("pv", ())))


# ---------------------------------------------------------------- analysis passes


def terminal_line(board: chess.Board) -> Line | None:
    """The score of a finished position, without asking the engine (CLAUDE.md §7.6).

    Checkmate: ``mate 0`` (the side to move is mated). Stalemate and automatic draws
    (insufficient material, 75 moves, fivefold repetition): ``cp 0``. Draws that must be
    claimed (threefold, 50 moves) aren't the end of the game, so the engine scores them.
    """
    outcome = board.outcome(claim_draw=False)
    if outcome is None:
        return None
    if outcome.termination == chess.Termination.CHECKMATE:
        return Line(Eval(mate=0))
    return Line(Eval(cp=0))


def analyse_game(
    game: ParsedGame,
    me: Color,
    analyser: Analyser,
    *,
    depth: int,
    thresholds: Thresholds,
    progress: Progress | None = None,
    flag_at: Judgment = "blunder",
) -> GameAnalysis:
    """Find my blunders in ``game``.

    Pass 1 scores every position once (positions 0..N, finished positions without the
    engine). My moves whose swing reaches the ``flag_at`` line (the blunder line for
    imports), and that aren't the engine's best move, are flagged. Pass 2 asks for the top
    3 moves in each flagged position, to know which re-test answers to accept.

    ``progress(done, total)`` is called after each position. ``total`` starts as N + 1 and
    grows by the number of flagged moves once pass 1 is over.
    """
    key = object()  # one ucinewgame per game
    n = len(game.plies)
    total = n + 1

    board = chess.Board(game.start_fen)
    pass1: list[Line] = []
    for i in range(n + 1):
        pass1.append(_evaluate(analyser, board, depth, key, game, i))
        if progress is not None:
            progress(i + 1, total)
        if i < n:
            board.push(chess.Move.from_uci(game.plies[i].uci))

    flagged: list[tuple[Ply, float]] = []
    for ply in game.plies:
        if ply.color != me:
            continue
        before, after = pass1[ply.index], pass1[ply.index + 1]
        swing = detect.swing(before.score, after.score, me)
        best = before.move
        if detect.is_flagged(swing, ply.uci, best.uci() if best else None, thresholds, flag_at):
            flagged.append((ply, swing))

    total += len(flagged)
    findings: list[Finding] = []
    for k, (ply, swing) in enumerate(flagged, start=1):
        multi = analyser.lines(_board_at(game, ply.index), depth, MULTIPV, game=key)
        findings.append(
            _finding(ply, swing, pass1[ply.index], pass1[ply.index + 1], multi, me, thresholds)
        )
        if progress is not None:
            progress(n + 1 + k, total)

    return GameAnalysis(
        engine_name=analyser.name,
        depth=depth,
        evals=tuple(line.score for line in pass1),
        findings=tuple(findings),
    )


def _evaluate(
    analyser: Analyser, board: chess.Board, depth: int, key: object, game: ParsedGame, i: int
) -> Line:
    done = terminal_line(board)
    if done is not None:
        return done
    found = analyser.lines(board, depth, 1, game=key)
    if not found:
        where = game.plies[i - 1].label if i else "the start position"
        raise EngineError(f"Stockfish gave no score after {where}.")
    return found[0]


def _board_at(game: ParsedGame, index: int) -> chess.Board:
    """The position before ply ``index``, with the moves that led to it."""
    board = chess.Board(game.start_fen)
    for ply in game.plies[:index]:
        board.push(chess.Move.from_uci(ply.uci))
    return board


def _finding(
    ply: Ply,
    swing: float,
    before: Line,
    after: Line,
    multi: list[Line],
    me: Color,
    thresholds: Thresholds,
) -> Finding:
    best = before.move
    judgment = detect.judgment(swing, thresholds)
    assert best is not None and judgment is not None  # both hold for a flagged move
    candidates = [(move.uci(), line.score) for line in multi if (move := line.move) is not None]
    return Finding(
        ply=ply,
        eval_before=before.score,
        eval_after=after.score,
        swing=swing,
        judgment=judgment,
        best_uci=best.uci(),
        best_san=chess.Board(ply.fen_before).san(best),
        best_line_san=detect.best_line_san(ply.fen_before, before.pv),
        refutation_san=detect.refutation_san(ply.fen_after, after.pv),
        refutation_uci=tuple(move.uci() for move in after.pv),
        accept_uci=detect.accepted_moves(
            candidates, me, best.uci(), thresholds.accept_margin_cp, played_uci=ply.uci
        ),
    )
