"""The Journal's test setup: a scratch config.toml with the extension on, and Blunderbook's
database next to journal.db, all in tmp_path, so no test touches your real files.

Not a conftest.py: core's tests import their own ``conftest`` by name, and a second one on
the path would shadow it. Each test module imports these fixtures instead."""

from pathlib import Path

import pytest

from blunderbook import config

FENCE = "```"

ELEPHANT = f"""# The Elephant trap

The d5 pawn looks free, but after 5. cxd5 exd5 6. Nxd5?? Nxd5 7. Bxd8 Bb4+ White loses
the queen back. #qgd #traps

{FENCE}pgn
[Event "Club night"]
[White "Ivanov"]
[Black "Petrova"]
[Opening "Queen's Gambit Declined"]
[ECO "D51"]
1. d4 d5 2. c4 e6 3. Nc3 Nf6 4. Bg5 Nbd7 5. cxd5 exd5 6. Nxd5?? Nxd5 7. Bxd8 Bb4+ *
{FENCE}

{FENCE}fen
r1bqkb1r/pppn1ppp/5n2/3p2B1/3P4/2N5/PP2PPPP/R2QKBNR w KQkq - 0 6
{FENCE}

[[log 12]]
"""


@pytest.fixture(autouse=True)
def cfg_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """config.toml with the Journal on, and Blunderbook's database next to journal.db."""
    path = tmp_path / "home" / "config.toml"
    monkeypatch.setattr(config, "config_path", lambda: path)
    monkeypatch.setattr(config, "db_path", lambda: tmp_path / "data" / "blunderbook.db")
    config.save(config.Config(extensions=config.ExtensionsConfig(enabled=("journal",))), path)
    return path
