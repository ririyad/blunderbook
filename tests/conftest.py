"""Shared test setup.

Engine tests are marked ``@pytest.mark.engine`` and skipped when no Stockfish is found.
They use the app's own lookup: ``BLUNDERBOOK_STOCKFISH``, then your config.toml (read
only), then ``stockfish`` on PATH. So ``blunderbook engine set PATH`` once is enough.
"""

import sys
from collections.abc import Callable
from functools import cache
from pathlib import Path

import httpx
import pytest

from blunderbook import config
from blunderbook.db import connection

FAKE_UCI = Path(__file__).parent / "fixtures" / "fake_uci.py"


@cache
def _stockfish() -> config.StockfishLocation:
    try:
        cfg: config.Config | None = config.load()
    except config.ConfigError:
        cfg = None
    return config.locate_stockfish(config=cfg)


def _skip_reason() -> str:
    problem = _stockfish().problem or "Stockfish not found"
    return problem.splitlines()[0]


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if _stockfish().path is not None:
        return
    skip = pytest.mark.skip(reason=_skip_reason())
    for item in items:
        if "engine" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def db_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Every test gets its own database path, so no test ever touches your real one."""
    path = tmp_path / "data" / "blunderbook.db"
    monkeypatch.setattr(config, "db_path", lambda: path)
    return path


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never call Lichess or Chess.com (CLAUDE.md §8): httpx's real transport only
    reaches this computer. Adapters get a MockTransport instead."""
    real = httpx.HTTPTransport.handle_request

    def local_only(self: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        if request.url.host not in ("127.0.0.1", "localhost"):
            raise AssertionError(f"A test tried to reach {request.url.host}")
        return real(self, request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", local_only)


@pytest.fixture(scope="session")
def stockfish_path() -> Path:
    path = _stockfish().path
    if path is None:
        pytest.skip(_skip_reason())
    return path


@pytest.fixture
def fake_engine() -> Callable[..., list[str]]:
    """Builds the command line for the fake UCI engine in tests/fixtures/fake_uci.py."""

    def command(*args: str) -> list[str]:
        return [sys.executable, "-I", str(FAKE_UCI), *args]

    return command


# ---------------------------------------------------------------- a newer app

_REAL_MIGRATIONS = connection.load_migrations()
LATEST = connection.latest_version()


def with_next_migration(*_: object) -> tuple[connection.Migration, ...]:
    """The real migrations plus a made-up next one, as a newer Blunderbook would ship.
    Patch it over ``connection.load_migrations`` to test an upgrade."""
    n = LATEST + 1
    extra = connection.Migration(n, f"{n:04}_extra.sql", "CREATE TABLE extra (x INTEGER);")
    return (*_REAL_MIGRATIONS, extra)
