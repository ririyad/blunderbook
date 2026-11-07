"""The host API (CLAUDE.md §15): what an extension may use from Blunderbook, besides the pure
``blunderbook.core`` modules and the page modules under ``/js/``.

It is stable for one ``ext.HOST_API``: something may be added without a bump, nothing is
removed or changed. An extension imports only this module, ``blunderbook.ext`` (for
``Extension``) and ``blunderbook.core``.

For routes (an extension's router is mounted at ``/api/ext/<name>``):

- ``ExtDb``: a connection to the extension's own database, per request.
- ``Log``: your Log, read-only (the database is opened ``mode=ro``: a write fails in SQLite).
- ``same_origin``: add ``dependencies=[Depends(host.same_origin)]`` to a route that changes
  something, so only the Blunderbook page can call it.

For anything (routes and commands):

- ``settings()``: your names, thresholds and engine settings. Never a token or a key.
- ``engine()``: Stockfish, found as Blunderbook finds it, in a ``with`` block.
- ``read_log()``: your Log, read-only, outside a request (``with host.read_log() as log``).
- ``open_db(extension)``: the extension's own database outside a request, created and
  upgraded (backed up first) if needed.
"""

import sqlite3
from collections.abc import Collection, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request

from blunderbook import config, ext
from blunderbook.api.common import same_origin
from blunderbook.core.engine import Engine, EngineError
from blunderbook.core.models import Entry, Game, Source, Status, Thresholds
from blunderbook.db import connection, repo

__all__ = [
    "ExtDb",
    "HostError",
    "Log",
    "LogReader",
    "Settings",
    "engine",
    "open_db",
    "read_log",
    "same_origin",
    "settings",
]


class HostError(Exception):
    """Something the host can't give: no Stockfish, a broken config.toml. Plain message."""


# ---------------------------------------------------------------- settings and engine


@dataclass(frozen=True, slots=True)
class Settings:
    """The settings an extension may read. Tokens and keys are never in it."""

    my_names: tuple[str, ...]  # my_names plus your Lichess and Chess.com usernames
    thresholds: Thresholds
    engine_depth: int
    engine_threads: int
    engine_hash_mb: int


def settings() -> Settings:
    """Read config.toml now. Raises HostError."""
    cfg = _config()
    return Settings(
        my_names=tuple(name for name in config.all_names(cfg) if name.strip()),
        thresholds=cfg.thresholds,
        engine_depth=cfg.engine_depth,
        engine_threads=cfg.engine_threads,
        engine_hash_mb=cfg.engine_hash_mb,
    )


def engine() -> Engine:
    """Start Stockfish, found as CLAUDE.md §6 says (``BLUNDERBOOK_STOCKFISH``, then
    ``stockfish_path``, then ``PATH``), with your threads and hash. Use it in a ``with``
    block so it always closes. Raises HostError."""
    cfg = _config()
    location = config.locate_stockfish(None, cfg, config_dir=config.config_path().parent)
    if location.path is None:
        raise HostError(f"Can't analyse: {location.problem or config.NOT_FOUND}")
    try:
        return Engine.open(
            [str(location.path)], threads=cfg.engine_threads, hash_mb=cfg.engine_hash_mb
        )
    except EngineError as exc:
        raise HostError(f"Can't start Stockfish: {exc}") from None


def _config() -> config.Config:
    try:
        return config.load(config.config_path())
    except config.ConfigError as exc:
        raise HostError(str(exc)) from None


# ---------------------------------------------------------------- your Log, read-only


class LogReader:
    """Your Log, read-only. The connection is opened ``mode=ro``, so nothing can change
    it, by mistake or otherwise."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def entries(
        self,
        *,
        source: Source | None = None,
        statuses: Collection[Status] = (),
        cause: str | None = None,
        due_by: date | None = None,
    ) -> list[Entry]:
        """The Log, newest first, filtered as ``GET /api/blunders`` is."""
        return repo.list_entries(
            self._conn, source=source, statuses=statuses, cause=cause, due_by=due_by
        )

    def entry(self, blunder_id: int) -> Entry | None:
        return repo.get_entry(self._conn, blunder_id)

    def game(self, game_id: int) -> Game | None:
        return repo.get_game(self._conn, game_id)


def _read_only(db: Path) -> sqlite3.Connection:
    return connection.connect(db, mode="ro", any_thread=True)


@contextmanager
def read_log() -> Iterator[LogReader]:
    """Your Log, outside a request. Raises ``StorageError`` when there's no database yet."""
    with closing(_read_only(config.db_path())) as conn:
        yield LogReader(conn)


def open_db(extension: ext.Extension) -> sqlite3.Connection:
    """The extension's own database, outside a request: created if it's missing, upgraded
    (backed up first) if it's older. Close it with ``contextlib.closing``. Raises HostError
    or ``StorageError``."""
    return ext.open_db(extension, _config())


# ---------------------------------------------------------------- route dependencies


def _log(request: Request) -> Iterator[LogReader]:
    with closing(_read_only(request.app.state.db_path)) as conn:
        yield LogReader(conn)


def _ext_db(request: Request) -> Iterator[sqlite3.Connection]:
    """The database of the extension whose route this is (``/api/ext/<name>/...``)."""
    parts = request.url.path.split("/")
    name = parts[3] if len(parts) > 3 and parts[1:3] == ["api", "ext"] else ""
    extension = request.app.state.extensions.get(name)
    if extension is None or ext.store(extension) is None:
        raise RuntimeError("ExtDb is only for the routes of an extension with a database.")
    path = ext.db_path(extension, request.app.state.db_path)
    with closing(connection.connect(path, any_thread=True)) as conn:
        yield conn


Log = Annotated[LogReader, Depends(_log)]
ExtDb = Annotated[sqlite3.Connection, Depends(_ext_db)]
