"""`blunderbook sync` (CLAUDE.md §8, §9): the adapters against recorded responses (no network),
a scripted engine, a temp config and database. Also `sync_state` in the repo, and the sync
questions `init` asks."""

from collections.abc import Callable, Iterator
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from test_cli_import import StubEngine, program
from test_sync_chesscom import site as chesscom_site
from test_sync_lichess import GAMES as LICHESS_GAMES
from typer.testing import CliRunner

from blunderbook import cli, config, sources
from blunderbook.cli import app
from blunderbook.config import ChesscomConfig, LichessConfig
from blunderbook.core import engine
from blunderbook.core.models import SyncSource
from blunderbook.core.source import game_time
from blunderbook.db import connection, repo
from blunderbook.sources.chesscom import ChesscomAdapter
from blunderbook.sources.lichess import LichessAdapter

runner = CliRunner()
DOT = "\N{MIDDLE DOT}"
TOKEN = "lip_secret0123456789"
NEWEST_LICHESS = datetime(2026, 10, 14, 9, 15, 3, tzinfo=UTC)  # the second fixture game

Handler = Callable[[httpx.Request], httpx.Response]


def lichess_site(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=LICHESS_GAMES)


@pytest.fixture
def cfg_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "home" / "config.toml"
    monkeypatch.setattr(config, "config_path", lambda: path)
    monkeypatch.delenv(config.STOCKFISH_ENV, raising=False)
    monkeypatch.setattr("shutil.which", lambda _: None)
    monkeypatch.delenv("ONEDRIVE", raising=False)
    return path


def configure(tmp_path: Path, cfg_file: Path, **changes: Any) -> None:
    exe = program(tmp_path / "sf")
    base = config.Config(my_names=("Rashed",), stockfish_path=str(exe))
    config.save(replace(base, **changes), cfg_file)


@pytest.fixture
def stub(monkeypatch: pytest.MonkeyPatch) -> StubEngine:
    """Flags 6. Nxd5 in the Elephant (the first Lichess game); cp 20 everywhere else."""
    import chess

    from blunderbook.core.engine import Line
    from blunderbook.core.models import Eval

    elephant = "r1bqkb1r/pppn1ppp/5n2/3p2B1/3P4/2N5/PP2PPPP/R2QKBNR w KQkq - 0 6"
    after = "r1bqkb1r/pppn1ppp/5n2/3N2B1/3P4/8/PP2PPPP/R2QKBNR b KQkq - 0 6"
    sf = StubEngine(
        {
            elephant: Line(Eval(cp=36), tuple(map(chess.Move.from_uci, ["e2e3", "f8e7"]))),
            after: Line(Eval(cp=-409), (chess.Move.from_uci("f6d5"),)),
        }
    )

    def fake_open(command: list[str], **settings: Any) -> StubEngine:
        sf.opened_with = {"command": command, **settings}
        return sf

    monkeypatch.setattr(engine.Engine, "open", staticmethod(fake_open))
    return sf


class Sites:
    """Stands in for `sources.adapter_for`: the real adapters, each with a MockTransport
    client. Records every request."""

    def __init__(self) -> None:
        self.handlers: dict[str, Handler] = {"lichess": lichess_site, "chesscom": chesscom_site}
        self.requests: list[httpx.Request] = []

    def __call__(self, name: SyncSource, cfg: config.Config) -> Any:
        handler = self.handlers[name]

        def record(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return handler(request)

        client = httpx.Client(transport=httpx.MockTransport(record))
        if name == "lichess":
            return LichessAdapter(
                cfg.lichess.username, cfg.lichess.token, client=client, sleep=lambda s: None
            )
        return ChesscomAdapter(
            cfg.chesscom.username, cfg.chesscom.contact, client=client, sleep=lambda s: None
        )

    def hosts(self) -> list[str]:
        return [r.url.host for r in self.requests]


@pytest.fixture
def sites(monkeypatch: pytest.MonkeyPatch) -> Sites:
    fake = Sites()
    monkeypatch.setattr(sources, "adapter_for", fake)
    return fake


LICHESS = LichessConfig(username="Rashed")
CHESSCOM = ChesscomConfig(username="Rashed_Blitz", contact="rashed@example.org")


def state(db_file: Path, source: SyncSource) -> Any:
    with closing(connection.open_db(db_file)) as conn:
        return repo.get_sync_state(conn, source)


def entry_moves(db_file: Path) -> list[str]:
    with closing(connection.open_db(db_file)) as conn:
        return [e.blunder.played_san for e in repo.list_entries(conn)]


def games(db_file: Path) -> int:
    with closing(connection.open_db(db_file)) as conn:
        return len(repo.known_fingerprints(conn))


# ---------------------------------------------------------------- what to sync


def test_nothing_to_sync(tmp_path: Path, cfg_file: Path, sites: Sites, db_file: Path) -> None:
    configure(tmp_path, cfg_file)
    result = runner.invoke(app, ["sync"])
    assert result.exit_code == 1
    assert "Nothing to sync: set your username under [lichess] or [chesscom]" in result.output
    assert sites.requests == []
    assert not db_file.exists()


@pytest.mark.parametrize(
    ("site", "message"),
    [
        ("lichess", r"Set your Lichess username under [lichess] in config.toml."),
        ("chesscom", r"Set your Chess.com username under [chesscom] in config.toml."),
    ],
)
def test_a_site_without_a_username(
    tmp_path: Path, cfg_file: Path, sites: Sites, site: str, message: str
) -> None:
    configure(tmp_path, cfg_file, lichess=LICHESS if site == "chesscom" else LichessConfig())
    result = runner.invoke(app, ["sync", site])
    assert result.exit_code == 1
    assert message in result.output
    assert sites.requests == []


def test_unknown_site(tmp_path: Path, cfg_file: Path, sites: Sites) -> None:
    configure(tmp_path, cfg_file, lichess=LICHESS)
    assert runner.invoke(app, ["sync", "playchess"]).exit_code == 2


def test_all_syncs_only_the_sites_you_set_up(
    tmp_path: Path, cfg_file: Path, sites: Sites, stub: StubEngine
) -> None:
    configure(tmp_path, cfg_file, lichess=LICHESS)
    result = runner.invoke(app, ["sync"])
    assert result.exit_code == 0, result.output
    assert set(sites.hosts()) == {"lichess.org"}


# ---------------------------------------------------------------- a sync that works


def test_sync_imports_and_records_how_far_it_got(
    tmp_path: Path, cfg_file: Path, sites: Sites, stub: StubEngine, db_file: Path
) -> None:
    configure(tmp_path, cfg_file, lichess=LICHESS)
    result = runner.invoke(app, ["sync", "lichess"])
    assert result.exit_code == 0, result.output
    assert "Lichess (Rashed): all your games." in result.output
    assert "Downloaded 2 games." in result.output
    assert "6. Nxd5??" in result.output
    assert f"2 games read {DOT} 1 blunder added" in result.output
    assert entry_moves(db_file) == ["Nxd5"]
    with closing(connection.connect(db_file, mode="ro")) as conn:
        labels = conn.execute("SELECT label, kind FROM imports").fetchall()
    assert [tuple(r) for r in labels] == [("Lichess sync", "sync")]  # for the Games tab
    saved = state(db_file, "lichess")
    assert saved.username == "Rashed"
    assert saved.last_synced == NEWEST_LICHESS
    assert saved.last_error is None
    assert saved.last_run_at is not None
    assert "since" not in sites.requests[0].url.params


def test_the_next_sync_asks_only_for_newer_games_and_adds_nothing(
    tmp_path: Path, cfg_file: Path, sites: Sites, stub: StubEngine, db_file: Path
) -> None:
    configure(tmp_path, cfg_file, lichess=LICHESS)
    assert runner.invoke(app, ["sync"]).exit_code == 0
    stub.opened_with = {}
    again = runner.invoke(app, ["sync"])
    assert again.exit_code == 0, again.output
    assert "Lichess (Rashed): games since 2026-10-14" in again.output
    since = int(NEWEST_LICHESS.timestamp() * 1000)
    assert sites.requests[-1].url.params["since"] == str(since)
    # The site sends the same games again here: they're counted, not listed one by one.
    assert f"2 games read {DOT} 2 skipped (duplicate) {DOT} 0 blunders added" in again.output
    assert "Already imported" not in again.output
    assert stub.opened_with == {}  # nothing new to analyse
    assert entry_moves(db_file) == ["Nxd5"]
    assert state(db_file, "lichess").last_synced == NEWEST_LICHESS


def test_no_new_games(
    tmp_path: Path, cfg_file: Path, sites: Sites, stub: StubEngine, db_file: Path
) -> None:
    configure(tmp_path, cfg_file, lichess=LICHESS)
    sites.handlers["lichess"] = lambda request: httpx.Response(200, content=b"")
    result = runner.invoke(app, ["sync"])
    assert result.exit_code == 0, result.output
    assert "No new games." in result.output
    assert state(db_file, "lichess").last_error is None


def test_chesscom_sync(
    tmp_path: Path, cfg_file: Path, sites: Sites, stub: StubEngine, db_file: Path
) -> None:
    configure(tmp_path, cfg_file, chesscom=CHESSCOM)
    result = runner.invoke(app, ["sync", "chesscom"])
    assert result.exit_code == 0, result.output
    assert "Chess.com (Rashed_Blitz): all your games." in result.output
    assert f"3 games read {DOT} 0 blunders added" in result.output
    assert games(db_file) == 3  # your username is one of your names, so every side is known
    assert state(db_file, "chesscom").last_synced == datetime(2026, 10, 31, tzinfo=UTC)

    sites.requests.clear()
    assert runner.invoke(app, ["sync", "chesscom"]).exit_code == 0
    assert [r.url.path for r in sites.requests] == [
        "/pub/player/rashed_blitz/games/archives",
        "/pub/player/rashed_blitz/games/2026/10/pgn",
    ]


def test_both_sites(
    tmp_path: Path, cfg_file: Path, sites: Sites, stub: StubEngine, db_file: Path
) -> None:
    configure(tmp_path, cfg_file, lichess=LICHESS, chesscom=CHESSCOM)
    result = runner.invoke(app, ["sync", "all"])
    assert result.exit_code == 0, result.output
    assert result.output.index("Lichess (Rashed)") < result.output.index("Chess.com (")
    assert games(db_file) == 5
    assert state(db_file, "lichess").last_error is None
    assert state(db_file, "chesscom").last_error is None


def test_another_account_starts_from_the_beginning(
    tmp_path: Path, cfg_file: Path, sites: Sites, stub: StubEngine
) -> None:
    configure(tmp_path, cfg_file, lichess=LICHESS)
    assert runner.invoke(app, ["sync"]).exit_code == 0
    configure(tmp_path, cfg_file, lichess=LichessConfig(username="rashed_alt"))
    result = runner.invoke(app, ["sync"])
    assert "Lichess (rashed_alt): all your games." in result.output
    assert "since" not in sites.requests[-1].url.params


def test_the_daily_backup_runs_first(
    tmp_path: Path, cfg_file: Path, sites: Sites, stub: StubEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []
    monkeypatch.setattr(cli, "_daily_backup", lambda cfg: order.append("backup"))
    real = sites.__call__

    def adapter_for(name: SyncSource, cfg: config.Config) -> Any:
        order.append(name)
        return real(name, cfg)

    monkeypatch.setattr(sources, "adapter_for", adapter_for)
    configure(tmp_path, cfg_file, lichess=LICHESS)
    assert runner.invoke(app, ["sync"]).exit_code == 0
    assert order == ["backup", "lichess"]


# ---------------------------------------------------------------- a sync that fails


def test_a_failed_download_records_the_error_and_changes_nothing(
    tmp_path: Path, cfg_file: Path, sites: Sites, stub: StubEngine, db_file: Path
) -> None:
    configure(tmp_path, cfg_file, lichess=LICHESS)
    assert runner.invoke(app, ["sync"]).exit_code == 0
    before = (entry_moves(db_file), games(db_file), state(db_file, "lichess").last_synced)

    sites.handlers["lichess"] = lambda request: httpx.Response(503)
    result = runner.invoke(app, ["sync"])
    assert result.exit_code == 1
    message = (
        "Lichess answered HTTP 503. Run the sync again later. Nothing was imported from Lichess."
    )
    assert message in result.output
    after = state(db_file, "lichess")
    assert after.last_error == message
    assert (entry_moves(db_file), games(db_file), after.last_synced) == before

    sites.handlers["lichess"] = lichess_site
    assert runner.invoke(app, ["sync"]).exit_code == 0
    assert state(db_file, "lichess").last_error is None  # cleared by the next good run


def test_a_download_that_breaks_halfway_imports_nothing(
    tmp_path: Path, cfg_file: Path, sites: Sites, stub: StubEngine, db_file: Path
) -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        def body() -> Iterator[bytes]:
            yield LICHESS_GAMES[: LICHESS_GAMES.index(b"[Event", 10)]
            raise httpx.ReadError("connection reset")

        return httpx.Response(200, content=body())

    sites.handlers["lichess"] = broken
    configure(tmp_path, cfg_file, lichess=LICHESS)
    result = runner.invoke(app, ["sync"])
    assert result.exit_code == 1
    assert "Can't download your Lichess games: connection reset" in result.output
    assert games(db_file) == 0
    assert state(db_file, "lichess").last_synced is None


def test_the_token_never_shows(
    tmp_path: Path, cfg_file: Path, sites: Sites, stub: StubEngine, db_file: Path
) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        raise httpx.ConnectError(f"proxy said: Bearer {TOKEN}", request=request)

    sites.handlers["lichess"] = refuse
    configure(tmp_path, cfg_file, lichess=LichessConfig(username="Rashed", token=TOKEN))
    result = runner.invoke(app, ["sync"])
    assert result.exit_code == 1
    assert TOKEN not in result.output
    assert TOKEN not in state(db_file, "lichess").last_error
    for file in db_file.parent.glob(db_file.name + "*"):  # the database and its -wal
        assert TOKEN.encode() not in file.read_bytes(), file.name


def test_a_missing_contact_is_recorded(
    tmp_path: Path, cfg_file: Path, sites: Sites, stub: StubEngine, db_file: Path
) -> None:
    configure(tmp_path, cfg_file, chesscom=ChesscomConfig(username="Rashed_Blitz"))
    result = runner.invoke(app, ["sync"])
    assert result.exit_code == 1
    assert "Set contact under [chesscom] in config.toml" in result.output
    assert "Set contact under [chesscom]" in state(db_file, "chesscom").last_error
    assert sites.requests == []


def test_one_site_failing_still_syncs_the_other(
    tmp_path: Path, cfg_file: Path, sites: Sites, stub: StubEngine, db_file: Path
) -> None:
    sites.handlers["lichess"] = lambda request: httpx.Response(500)
    configure(tmp_path, cfg_file, lichess=LICHESS, chesscom=CHESSCOM)
    result = runner.invoke(app, ["sync"])
    assert result.exit_code == 1
    assert state(db_file, "lichess").last_error is not None
    assert state(db_file, "chesscom").last_error is None
    assert games(db_file) == 3


def test_no_stockfish(
    tmp_path: Path, cfg_file: Path, sites: Sites, stub: StubEngine, db_file: Path
) -> None:
    configure(tmp_path, cfg_file, lichess=LICHESS)
    config.save(config.Config(my_names=("Rashed",), lichess=LICHESS), cfg_file)  # PATH: none
    result = runner.invoke(app, ["sync"])
    assert result.exit_code == 1
    assert "Can't analyse:" in result.output
    assert "Can't analyse:" in state(db_file, "lichess").last_error
    assert state(db_file, "lichess").last_synced is None
    assert games(db_file) == 0


def test_analysis_that_stops_keeps_the_saved_games_but_not_the_progress(
    tmp_path: Path, cfg_file: Path, sites: Sites, stub: StubEngine, db_file: Path
) -> None:
    stub.fail_after = 25  # the first game has 19 positions
    configure(tmp_path, cfg_file, lichess=LICHESS)
    result = runner.invoke(app, ["sync"])
    assert result.exit_code == 1
    assert "Analysis stopped: Stockfish stopped unexpectedly." in result.output
    assert entry_moves(db_file) == ["Nxd5"]
    saved = state(db_file, "lichess")
    assert saved.last_synced is None  # the next run downloads them again
    assert saved.last_error.startswith("Analysis stopped")
    assert stub.closed

    stub.fail_after = None
    again = runner.invoke(app, ["sync"])
    assert again.exit_code == 0, again.output
    assert f"2 games read {DOT} 1 skipped (duplicate) {DOT} 0 blunders added" in again.output
    assert state(db_file, "lichess").last_synced == NEWEST_LICHESS


def test_a_database_it_cant_use(
    tmp_path: Path, cfg_file: Path, sites: Sites, db_file: Path
) -> None:
    db_file.parent.mkdir(parents=True)
    db_file.write_bytes(b"not a database at all, just some text that fills the header")
    configure(tmp_path, cfg_file, lichess=LICHESS)
    result = runner.invoke(app, ["sync"])
    assert result.exit_code == 1
    assert "Can't sync: the database can't be used." in result.output
    assert sites.requests == []


# ---------------------------------------------------------------- sync_state in the repo


@pytest.fixture
def conn(db_file: Path) -> Iterator[Any]:
    with closing(connection.open_db(db_file, create=True)) as c:
        yield c


def test_record_sync_moves_on_and_never_back(conn: Any) -> None:
    first = datetime(2026, 10, 1, tzinfo=UTC)
    later = datetime(2026, 10, 5, tzinfo=UTC)
    assert repo.get_sync_state(conn, "lichess") is None
    repo.record_sync(conn, "lichess", username="Rashed", newest=later)
    assert repo.record_sync(conn, "lichess", username="Rashed", newest=first).last_synced == later
    assert repo.record_sync(conn, "lichess", username="Rashed").last_synced == later


def test_record_sync_failure_keeps_the_progress(conn: Any) -> None:
    newest = datetime(2026, 10, 5, tzinfo=UTC)
    repo.record_sync(conn, "chesscom", username="Rashed_Blitz", newest=newest)
    failed = repo.record_sync(
        conn,
        "chesscom",
        username="Rashed_Blitz",
        newest=datetime(2026, 11, 1, tzinfo=UTC),
        error="Oops.",
        now=datetime(2026, 11, 6, 8, tzinfo=UTC),
    )
    assert failed.last_synced == newest
    assert failed.last_error == "Oops."
    assert failed.last_run_at == datetime(2026, 11, 6, 8, tzinfo=UTC)


def test_record_sync_another_username_starts_again(conn: Any) -> None:
    repo.record_sync(conn, "lichess", username="Rashed", newest=datetime(2026, 10, 5, tzinfo=UTC))
    assert repo.record_sync(conn, "lichess", username="RASHED").last_synced is not None
    other = repo.record_sync(conn, "lichess", username="rashed_alt", error="Oops.")
    assert other.username == "rashed_alt" and other.last_synced is None


def test_record_sync_needs_aware_times(conn: Any) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        repo.record_sync(conn, "lichess", username="Rashed", newest=datetime(2026, 10, 5))


# ---------------------------------------------------------------- game_time


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"UTCDate": "2026.10.14", "UTCTime": "09:15:03"}, datetime(2026, 10, 14, 9, 15, 3)),
        (
            {
                "UTCDate": "2026.10.30",
                "UTCTime": "21:02:00",
                "EndDate": "2026.10.30",
                "EndTime": "21:04:31",
            },
            datetime(2026, 10, 30, 21, 4, 31),
        ),
        ({"EndDate": "2026.10.31"}, datetime(2026, 10, 31)),
        ({"UTCDate": "2026.10.14", "UTCTime": "25:61:00"}, datetime(2026, 10, 14)),
        ({"EndDate": "????.??.??", "UTCDate": "2026.10.14"}, datetime(2026, 10, 14)),
        ({"Date": "2026.10.14"}, None),  # a local date only: not a site game time
        ({}, None),
    ],
)
def test_game_time(headers: dict[str, str], expected: datetime | None) -> None:
    got = game_time(headers)
    assert got == (None if expected is None else expected.replace(tzinfo=UTC))


# ---------------------------------------------------------------- init


def test_init_asks_for_the_sync_accounts(cfg_file: Path) -> None:
    answers = "Rashed\n\n\n Rashed \nRashed_Blitz\nme@example.org\n"
    result = runner.invoke(app, ["init"], input=answers)
    assert result.exit_code == 0, result.output
    assert "Sync (optional)" in result.output
    assert "Chess.com asks apps to say how to reach the person using them" in result.output
    assert "token under [lichess]" in result.output
    assert "Next: blunderbook import FILE.pgn or blunderbook sync" in result.output
    saved = config.load(cfg_file)
    assert saved.lichess.username == "Rashed"
    assert saved.chesscom == ChesscomConfig(username="Rashed_Blitz", contact="me@example.org")


def test_init_skips_contact_without_a_chesscom_username(cfg_file: Path) -> None:
    result = runner.invoke(app, ["init"], input="Rashed\n\n\n\n\n")
    assert result.exit_code == 0, result.output
    assert "Contact for Chess.com" not in result.output
    assert "Next: blunderbook import FILE.pgn\n" in result.output
    saved = config.load(cfg_file)
    assert saved.lichess == LichessConfig() and saved.chesscom == ChesscomConfig()


def test_init_keeps_the_token(cfg_file: Path) -> None:
    config.save(config.Config(lichess=LichessConfig(username="Rashed", token=TOKEN)), cfg_file)
    result = runner.invoke(app, ["init"], input="Rashed\n\n\n\n\n")
    assert result.exit_code == 0, result.output
    assert TOKEN not in result.output
    assert config.load(cfg_file).lichess == LichessConfig(username="Rashed", token=TOKEN)
