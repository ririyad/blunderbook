"""Shared test setup.

Engine tests are marked ``@pytest.mark.engine`` and skipped when no Stockfish binary is
found. Set ``BLUNDERBOOK_STOCKFISH`` to the binary's path, or put ``stockfish`` on PATH.
"""

import os
import shutil
from pathlib import Path

import pytest

STOCKFISH_ENV = "BLUNDERBOOK_STOCKFISH"


def find_stockfish() -> Path | None:
    configured = os.environ.get(STOCKFISH_ENV, "").strip()
    if configured:
        path = Path(configured)
        return path if path.is_file() else None
    found = shutil.which("stockfish")
    return Path(found) if found else None


def _skip_reason() -> str:
    configured = os.environ.get(STOCKFISH_ENV, "").strip()
    if configured:
        return f"{STOCKFISH_ENV} points to a missing file: {configured}"
    return f"Stockfish not found (set {STOCKFISH_ENV} or put stockfish on PATH)"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if find_stockfish() is not None:
        return
    skip = pytest.mark.skip(reason=_skip_reason())
    for item in items:
        if "engine" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def stockfish_path() -> Path:
    path = find_stockfish()
    if path is None:
        pytest.skip(_skip_reason())
    return path
