"""What the sites and the kinds of play are called, on the command line and on the page."""

from typing import Final

from blunderbook.core.models import RatingKind, SyncSource

SITE_NAMES: Final[dict[SyncSource, str]] = {"lichess": "Lichess", "chesscom": "Chess.com"}
KIND_NAMES: Final[dict[RatingKind, str]] = {
    "bullet": "Bullet",
    "blitz": "Blitz",
    "rapid": "Rapid",
    "classical": "Classical",
    "daily": "Daily",
    "puzzle": "Puzzles",
}
NO_ACCOUNTS: Final = (
    "No usernames yet: set yours under [lichess] or [chesscom] in config.toml,\n"
    "or run blunderbook init."
)


def kind_name(source: SyncSource, kind: RatingKind) -> str:
    """What a kind of play is called. Lichess calls daily chess correspondence."""
    if source == "lichess" and kind == "daily":
        return "Correspondence"
    return KIND_NAMES[kind]
