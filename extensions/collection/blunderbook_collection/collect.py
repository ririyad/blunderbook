"""Adding games to a collection (ROADMAP 12.1): queue them (:func:`games.prepare`), add the
ones already analysed, then analyse and save the new ones, each as soon as it's done.

Like core's import (CLAUDE.md §7.4): each game is saved whole, in one transaction, as soon as
it's analysed. If the engine stops, or you press Ctrl+C, the games before it are kept and
adding the same text again finishes the rest. A collection is made with its first game, so
an import that adds nothing leaves no empty collection.
"""

import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field

from blunderbook import host
from blunderbook.core import engine
from blunderbook_collection import games, store

OpenEngine = Callable[[], AbstractContextManager[engine.Engine]]
ProgressFor = Callable[[games.Queued, int, int], engine.Progress]  # (game, k, of n)


@dataclass(slots=True)
class Result:
    queue: tuple[games.Queued, ...]
    collection_id: int | None = None  # None when nothing was added
    created: bool = False  # the collection was made by this import
    added: dict[int, int] = field(default_factory=dict)  # game number -> game id
    engine_name: str | None = None
    depth: int | None = None
    error: str | None = None  # why the analysis stopped
    stopped: bool = False  # you pressed Ctrl+C


def queue(conn: sqlite3.Connection, text: str, name: str) -> tuple[games.Queued, ...]:
    found = store.find(conn, name)
    return games.prepare(
        text,
        collection=found.name if found else name,
        analysed=store.analysed(conn),
        members=store.members(conn, found.id) if found else set(),
    )


def add(
    conn: sqlite3.Connection,
    name: str,
    queued: tuple[games.Queued, ...],
    open_engine: OpenEngine,
    *,
    depth: int,
    progress_for: ProgressFor | None = None,
    on_engine: Callable[[engine.Engine], object] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> Result:
    """Add the ``known`` games, then analyse and add the ``ready`` ones. Never raises for
    the engine: a failure is ``error`` (``host.HostError`` when there's no Stockfish,
    ``EngineError`` when it stops), and Ctrl+C is ``stopped``. So is ``should_stop()``
    turning true, checked between positions (the page's import, when ``serve`` stops): the
    game being analysed isn't saved."""
    result = Result(queued)
    known = store.analysed(conn)
    for q in queued:
        if q.status == "known":
            assert q.fingerprint is not None
            _member(conn, result, name, known[q.fingerprint], q.number)
    ready = [q for q in queued if q.status == "ready"]
    if not ready:
        return result
    try:
        with open_engine() as sf:
            result.engine_name, result.depth = sf.name, depth
            if on_engine is not None:
                on_engine(sf)
            for k, q in enumerate(ready, start=1):
                assert q.game is not None
                if should_stop is not None and should_stop():
                    raise _Stop
                progress = progress_for(q, k, len(ready)) if progress_for else None
                progress = _stopping(progress, should_stop)
                scored = games.score(q.game, sf, depth=depth, progress=progress)
                at = store.now()
                with host.transaction(conn):
                    game_id = store.save_game(
                        conn,
                        games.info(q),
                        scored,
                        engine_name=sf.name,
                        engine_depth=depth,
                        at=at,
                    )
                    _member(conn, result, name, game_id, q.number, inside=True)
    except (host.HostError, engine.EngineError) as exc:
        result.error = str(exc)
    except KeyboardInterrupt, _Stop:
        result.stopped = True
    return result


class _Stop(Exception):
    """``should_stop()`` turned true."""


def _stopping(
    progress: engine.Progress | None, should_stop: Callable[[], bool] | None
) -> engine.Progress | None:
    if should_stop is None:
        return progress
    check = should_stop

    def hook(done: int, total: int) -> None:
        if progress is not None:
            progress(done, total)
        if check():
            raise _Stop

    return hook


def summary(result: Result) -> str:
    """``"4 games read · 2 added · 1 skipped · 1 error"``: what an import did."""
    added = skipped = errors = left = 0
    for q in result.queue:
        if q.number in result.added:
            added += 1
        elif q.status in ("member", "duplicate"):
            skipped += 1
        elif q.status == "error":
            errors += 1
        else:
            left += 1
    n = len(result.queue)
    parts = [f"{n} {'game' if n == 1 else 'games'} read", f"{added} added"]
    if skipped:
        parts.append(f"{skipped} skipped")
    if errors:
        parts.append(f"{errors} {'error' if errors == 1 else 'errors'}")
    if left:
        parts.append(f"{left} not analysed")
    return " \N{MIDDLE DOT} ".join(parts)


def _member(
    conn: sqlite3.Connection,
    result: Result,
    name: str,
    game_id: int,
    number: int | None = None,
    *,
    inside: bool = False,
) -> None:
    """Put a game in the collection (made if it's missing), in a transaction unless
    ``inside`` one already."""
    if not inside:
        with host.transaction(conn):
            _member(conn, result, name, game_id, number, inside=True)
        return
    at = store.now()
    cid, made = store.ensure_collection(conn, name, at)
    store.add_member(conn, cid, game_id, at)
    result.collection_id = cid
    result.created = result.created or made
    if number is not None:
        result.added[number] = game_id
