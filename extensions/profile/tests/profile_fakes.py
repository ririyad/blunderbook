"""The Profile's test setup: a scratch config.toml with the extension on and both usernames
set, the sites faked at ``host.fetch_ratings``, and games for your Log, so no test touches
your real files or the network.

Not a conftest.py: core's tests import their own ``conftest`` by name, and a second one on
the path would shadow it. Each test module imports these fixtures instead."""

from contextlib import closing
from datetime import UTC, date, datetime
from pathlib import Path

import chess
import pytest

from blunderbook import config, host
from blunderbook.core.models import (
    Color,
    Game,
    GameRow,
    NewGame,
    Rating,
    SiteRatings,
    Source,
    Speed,
    SyncSource,
)
from blunderbook.db import connection, repo

LICHESS = SiteRatings(
    source="lichess",
    username="Rashed",
    ratings=(
        Rating(
            kind="blitz",
            rating=1647,
            games=812,
            best=1712,
            best_at=datetime(2026, 8, 14, 18, 22, tzinfo=UTC),
            wins=401,
            losses=392,
            draws=47,
        ),
        Rating(kind="classical", rating=1702, provisional=True, games=3),
        Rating(kind="daily", rating=1611, games=9),
        Rating(kind="puzzle", rating=1985, games=2104),
    ),
)
CHESSCOM = SiteRatings(
    source="chesscom",
    username="rashed_blitz",
    ratings=(
        Rating(kind="blitz", rating=1502, games=1289, best=1561, wins=620, losses=598, draws=71),
        Rating(kind="puzzle", rating=None, best=2104),
    ),
)


@pytest.fixture(autouse=True)
def cfg_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """config.toml with the Profile on and a username for each site, and Blunderbook's
    database next to profile.db, both in tmp_path."""
    path = tmp_path / "home" / "config.toml"
    monkeypatch.setattr(config, "config_path", lambda: path)
    monkeypatch.setattr(config, "db_path", lambda: tmp_path / "data" / "blunderbook.db")
    save_config(path)
    return path


def save_config(path: Path, *, lichess: str = "rashed", chesscom: str = "rashed_blitz") -> None:
    config.save(
        config.Config(
            lichess=config.LichessConfig(username=lichess, token="lip_secret"),
            chesscom=config.ChesscomConfig(username=chesscom, contact="rashed@example.com"),
            extensions=config.ExtensionsConfig(enabled=("profile",)),
        ),
        path,
    )


class Sites:
    """Stands in for ``host.fetch_ratings``: what each site answers, or the problem it has."""

    def __init__(self) -> None:
        self.answers: dict[SyncSource, SiteRatings | str] = {
            "lichess": LICHESS,
            "chesscom": CHESSCOM,
        }
        self.asked: list[SyncSource] = []

    def __call__(self, site: SyncSource) -> SiteRatings:
        self.asked.append(site)
        answer = self.answers[site]
        if isinstance(answer, str):
            raise host.HostError(answer)
        return answer


@pytest.fixture
def sites(monkeypatch: pytest.MonkeyPatch) -> Sites:
    fake = Sites()
    monkeypatch.setattr(host, "fetch_ratings", fake)
    return fake


def new_game(
    number: int,
    source: Source,
    speed: Speed | None,
    day: date | None,
    rating: int | None,
    *,
    me: Color = "white",
) -> NewGame:
    """A game you played, with your rating on your side and another on theirs."""
    return NewGame(
        fingerprint=f"fp-{number}",
        source=source,
        my_color=me,
        start_fen=chess.STARTING_FEN,
        pgn="1. e4 e5 *",
        engine_name="Stockfish 17.1",
        engine_depth=12,
        white="Rashed" if me == "white" else "Them",
        black="Them" if me == "white" else "Rashed",
        white_elo=rating if me == "white" else 2400,
        black_elo=2400 if me == "white" else rating,
        played_on=day,
        speed=speed,
    )


def row(
    number: int,
    source: Source,
    speed: Speed | None,
    day: date | None,
    rating: int | None,
    *,
    me: Color = "white",
    blunders: int = 0,
) -> GameRow:
    """The same game as your Log lists it (``Log.games()``), with its blunders counted."""
    game = new_game(number, source, speed, day, rating, me=me)
    saved = Game(
        **{name: getattr(game, name) for name in NewGame.__slots__},
        id=number,
        analysis_status="done",
        imported_at=datetime(2026, 11, 16, tzinfo=UTC),
    )
    return GameRow(game=saved, batch=None, blunders=blunders, mistakes=0, inaccuracies=0, missed=0)


def fill_log(*games: NewGame) -> None:
    """Save games to your Log, in this order."""
    with closing(connection.open_db(config.db_path(), create=True)) as conn:
        for game in games:
            assert repo.add_game(conn, game) is not None
