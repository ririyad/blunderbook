"""Optional sync adapters (Lichess, Chess.com). They only download PGN text."""

from typing import Final

from blunderbook.config import Config
from blunderbook.core.models import SyncSource
from blunderbook.sources.base import SourceAdapter
from blunderbook.sources.chesscom import ChesscomAdapter
from blunderbook.sources.lichess import LichessAdapter

SITES: Final[dict[SyncSource, str]] = {"lichess": "Lichess", "chesscom": "Chess.com"}


def username(name: SyncSource, cfg: Config) -> str:
    """The configured account for a site ("" when it isn't set)."""
    return (cfg.lichess.username if name == "lichess" else cfg.chesscom.username).strip()


def adapter_for(name: SyncSource, cfg: Config) -> SourceAdapter:
    """The adapter for a site, from config.toml. Raises SyncError for a missing setting."""
    if name == "lichess":
        return LichessAdapter(cfg.lichess.username, cfg.lichess.token)
    return ChesscomAdapter(cfg.chesscom.username, cfg.chesscom.contact)
