"""`blunderbook serve` (CLAUDE.md §9, §10): 127.0.0.1 only, the port taken first, the daily
backup and the database ready before the first request, Ctrl+C stops cleanly. One test runs
the real server in a thread and talks to it over HTTP."""

import socket
import sqlite3
import threading
import time
import webbrowser
from collections.abc import Callable, Iterator
from contextlib import closing
from dataclasses import replace
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Any

import chess
import httpx
import pytest
import uvicorn
from conftest import LATEST, with_next_migration
from typer.testing import CliRunner

from blunderbook import config
from blunderbook.cli import DEFAULT_PORT, app
from blunderbook.core.models import NewGame
from blunderbook.db import backup, connection, repo

runner = CliRunner()


@pytest.fixture
def cfg_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "home" / "config.toml"
    monkeypatch.setattr(config, "config_path", lambda: path)
    return path


def free_port() -> int:
    with closing(socket.socket()) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture
def port() -> int:
    return free_port()


class Runs:
    """What `uvicorn.Server.run` was asked to do, with the real run replaced."""

    def __init__(self) -> None:
        self.servers: list[uvicorn.Server] = []
        self.addresses: list[tuple[str, int]] = []


@pytest.fixture
def runs(monkeypatch: pytest.MonkeyPatch) -> Runs:
    seen = Runs()

    def fake_run(self: uvicorn.Server, sockets: list[socket.socket] | None = None) -> None:
        assert sockets is not None and len(sockets) == 1
        seen.servers.append(self)
        seen.addresses.append(sockets[0].getsockname())

    monkeypatch.setattr(uvicorn.Server, "run", fake_run)
    return seen


@pytest.fixture(autouse=True)
def opened(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Addresses `--open` handed to the browser; a test never opens a real one."""
    urls: list[str] = []

    def fake_open(url: str, *args: Any, **kwargs: Any) -> bool:
        host, port = url.removeprefix("http://").rstrip("/").split(":")
        with closing(socket.create_connection((host, int(port)), timeout=2)):
            pass  # already listening, so the browser's request waits for the server
        urls.append(url)
        return True

    monkeypatch.setattr(webbrowser, "open", fake_open)
    return urls


def add_game(db: Path) -> None:
    game = NewGame(
        fingerprint="fp",
        source="pgn",
        my_color="white",
        start_fen=chess.STARTING_FEN,
        pgn="1. e4 e5 *",
        engine_name="Stockfish 17.1",
        engine_depth=16,
    )
    with closing(connection.open_db(db, create=True)) as conn:
        repo.add_game(conn, game)


def set_backup(cfg_file: Path, **changes: Any) -> None:
    cfg = config.load(cfg_file)
    config.save(replace(cfg, backup=replace(cfg.backup, **changes)), cfg_file)


def serve(port: int) -> Any:
    return runner.invoke(app, ["serve", "--port", str(port)])


# ---------------------------------------------------------------- starting


def test_serves_on_localhost(cfg_file: Path, db_file: Path, runs: Runs, port: int) -> None:
    result = serve(port)
    assert result.exit_code == 0, result.output
    assert runs.addresses == [("127.0.0.1", port)]
    (server,) = runs.servers
    assert server.config.app.state.db_path == db_file
    assert f"Created the database {db_file}\n" in result.output  # ready before any request
    assert f"Blunderbook is running at http://127.0.0.1:{port}/\n" in result.output
    assert "Press Ctrl+C to stop." in result.output
    assert result.output.endswith("Stopped.\n")
    with closing(socket.socket()) as again:  # the port is let go
        again.bind(("127.0.0.1", port))


def test_does_not_open_a_browser_unless_asked(
    cfg_file: Path, runs: Runs, port: int, opened: list[str]
) -> None:
    assert serve(port).exit_code == 0
    assert opened == []


def test_open_shows_the_page_in_the_browser(
    cfg_file: Path, runs: Runs, port: int, opened: list[str]
) -> None:
    result = runner.invoke(app, ["serve", "--port", str(port), "--open"])
    assert result.exit_code == 0, result.output
    assert opened == [f"http://127.0.0.1:{port}/"]
    assert "Opened it in your browser. Press Ctrl+C to stop.\n" in result.output
    assert runs.addresses == [("127.0.0.1", port)]


@pytest.mark.parametrize("failure", ["no browser", "error"])
def test_open_without_a_browser_still_serves(
    cfg_file: Path, runs: Runs, port: int, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    def no_browser(url: str, *args: Any, **kwargs: Any) -> bool:
        if failure == "error":
            raise webbrowser.Error("could not locate runnable browser")
        return False

    monkeypatch.setattr(webbrowser, "open", no_browser)
    result = runner.invoke(app, ["serve", "--port", str(port), "--open"])
    assert result.exit_code == 0, result.output
    assert "Couldn't open a browser. Open that address yourself.\n" in result.output
    assert len(runs.servers) == 1


def test_default_port(cfg_file: Path, runs: Runs) -> None:
    with closing(socket.socket()) as probe:
        try:
            probe.bind(("127.0.0.1", DEFAULT_PORT))
        except OSError:
            pytest.skip(f"port {DEFAULT_PORT} is in use on this computer")
    result = runner.invoke(app, ["serve"])
    assert result.exit_code == 0, result.output
    assert runs.addresses == [("127.0.0.1", 8732)]


@pytest.mark.parametrize("bad", ["0", "65536", "http"])
def test_bad_port(cfg_file: Path, runs: Runs, bad: str) -> None:
    result = runner.invoke(app, ["serve", "--port", bad])
    assert result.exit_code == 2
    assert runs.servers == []


def test_ctrl_c_stops_cleanly(cfg_file: Path, port: int, monkeypatch: pytest.MonkeyPatch) -> None:
    def interrupted(self: uvicorn.Server, sockets: list[socket.socket] | None = None) -> None:
        raise KeyboardInterrupt  # what uvicorn does after shutting down on Ctrl+C

    monkeypatch.setattr(uvicorn.Server, "run", interrupted)
    result = serve(port)
    assert result.exit_code == 0, result.output
    assert result.output.endswith("Stopped.\n")
    assert "Aborted" not in result.output


def test_port_in_use_changes_nothing(cfg_file: Path, db_file: Path, runs: Runs) -> None:
    with closing(socket.socket()) as other:
        other.bind(("127.0.0.1", 0))
        other.listen()
        taken = other.getsockname()[1]
        result = serve(taken)
    assert result.exit_code == 1
    assert f"Port {taken} is already in use. Is Blunderbook already running?" in result.output
    assert f"blunderbook serve --port {taken + 1}" in result.output
    assert runs.servers == []
    assert not db_file.exists()  # nothing was touched


def test_bad_config(cfg_file: Path, runs: Runs, port: int) -> None:
    cfg_file.parent.mkdir(parents=True)
    cfg_file.write_text("engine_depth = 'deep'\n", "utf-8")
    result = serve(port)
    assert result.exit_code == 1
    assert "engine_depth" in result.output
    assert runs.servers == []


# ---------------------------------------------------------------- backups at start


def test_daily_backup_at_start(cfg_file: Path, db_file: Path, runs: Runs, port: int) -> None:
    add_game(db_file)
    result = serve(port)
    assert result.exit_code == 0, result.output
    (made,) = backup.list_backups(db_file.parent / "backups")
    assert f"Daily backup: {made.path}\n" in result.output
    assert serve(free_port()).output.count("Daily backup") == 0  # once a day


def test_no_daily_backup_when_off(cfg_file: Path, db_file: Path, runs: Runs, port: int) -> None:
    add_game(db_file)
    set_backup(cfg_file, auto=False)
    result = serve(port)
    assert result.exit_code == 0, result.output
    assert backup.list_backups(db_file.parent / "backups") == []


def test_upgrade_at_start_is_backed_up(
    cfg_file: Path, db_file: Path, runs: Runs, port: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_game(db_file)
    set_backup(cfg_file, auto=False)
    monkeypatch.setattr(connection, "load_migrations", with_next_migration)
    result = serve(port)
    assert result.exit_code == 0, result.output
    (made,) = backup.list_backups(db_file.parent / "backups")
    assert made.reason == "pre-migrate"
    assert "Backed up the database before upgrading it" in result.output
    with closing(connection.connect(db_file, mode="ro")) as conn:
        assert connection.user_version(conn) == LATEST + 1


def test_no_start_without_the_safety_copy(
    tmp_path: Path,
    cfg_file: Path,
    db_file: Path,
    runs: Runs,
    port: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_game(db_file)
    blocker = tmp_path / "a file"
    blocker.write_bytes(b"")
    set_backup(cfg_file, dir=str(blocker / "bk"), auto=False)
    monkeypatch.setattr(connection, "load_migrations", with_next_migration)
    result = serve(port)
    assert result.exit_code == 1
    assert "Can't start: the database can't be used.\nCan't back up the database" in result.output
    assert runs.servers == []
    with closing(socket.socket()) as again:  # the port was let go
        again.bind(("127.0.0.1", port))


# ---------------------------------------------------------------- the real server


@pytest.fixture
def live(cfg_file: Path, db_file: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """`blunderbook serve` running for real in a thread; yields its address."""
    servers: list[uvicorn.Server] = []
    real_run: Callable[..., None] = uvicorn.Server.run

    def run(self: uvicorn.Server, sockets: list[socket.socket] | None = None) -> None:
        servers.append(self)
        real_run(self, sockets=sockets)

    monkeypatch.setattr(uvicorn.Server, "run", run)
    add_game(db_file)
    port = free_port()
    outcome: dict[str, Any] = {}
    thread = threading.Thread(target=lambda: outcome.update(result=serve(port)), daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not (servers and servers[0].started):
        assert thread.is_alive(), outcome.get("result") and outcome["result"].output
        assert time.monotonic() < deadline, "the server didn't start"
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    servers[0].should_exit = True
    thread.join(10)
    assert not thread.is_alive()
    # Only the exit code: pytest swaps sys.stdout between test phases, under CliRunner's
    # feet in this thread. The other tests check what's printed.
    assert outcome["result"].exit_code == 0, outcome["result"].output


def test_real_server_answers(live: str) -> None:
    with httpx.Client(base_url=live, timeout=5) as http:
        page = http.get("/")
        assert page.status_code == 200
        assert '<script type="module" src="js/app.js"></script>' in page.text
        assert http.get("/js/views/log.js").headers["content-type"].startswith("text/javascript")
        assert http.get("/api/blunders").json() == []  # a game, but no entries
        refused = http.get("/api/blunders", headers={"Host": "evil.example"})
        assert refused.status_code == 400


# ---------------------------------------------------------------- extensions (9.3)


@pytest.fixture
def extensions_on(cfg_file: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    from blunderbook import ext

    points = [
        EntryPoint("notes", "ext_samples:notes", ext.GROUP),
        EntryPoint("broken", "ext_samples_broken:extension", ext.GROUP),
    ]
    monkeypatch.setattr(ext, "entry_points", lambda group: points)

    def turn_on(*names: str) -> None:
        cfg = config.load(cfg_file)
        config.save(replace(cfg, extensions=config.ExtensionsConfig(enabled=names)), cfg_file)

    return turn_on


def test_extensions_are_served(
    cfg_file: Path, db_file: Path, runs: Runs, port: int, extensions_on: Callable[..., None]
) -> None:
    extensions_on("notes")
    result = serve(port)
    assert result.exit_code == 0, result.output
    assert "Extensions: Notes\n" in result.output
    (server,) = runs.servers
    assert list(server.config.app.state.extensions) == ["notes"]
    with closing(connection.connect(db_file.parent / "notes.db", mode="ro")) as conn:
        assert connection.table_names(conn) == {"notes"}  # ready before any request


def test_a_broken_extension_is_left_out(
    cfg_file: Path, db_file: Path, runs: Runs, port: int, extensions_on: Callable[..., None]
) -> None:
    extensions_on("broken", "missing", "notes")
    db_file.parent.mkdir(parents=True)
    with closing(sqlite3.connect(db_file.parent.joinpath("notes.db"))) as conn:
        conn.execute("PRAGMA user_version = 9")  # made by a newer notes extension
    result = runner.invoke(app, ["serve", "--port", str(port)])
    assert result.exit_code == 0, result.output
    assert "Warning: the broken extension couldn't be loaded" in result.stderr
    assert "Warning: the missing extension is turned on but isn't installed" in result.stderr
    assert "Warning: the notes extension is left out. The database was made by a newer" in (
        result.stderr
    )
    assert "Extensions:" not in result.output
    (server,) = runs.servers
    assert server.config.app.state.extensions == {}
