"""`blunderbook serve` (CLAUDE.md §9, §10): 127.0.0.1 only, the port taken first, the daily
backup and the database ready before the first request, Ctrl+C stops cleanly. One test runs
the real server in a thread and talks to it over HTTP."""

import socket
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from typing import Any

import chess
import httpx
import pytest
import uvicorn
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


def two_migrations() -> tuple[connection.Migration, ...]:
    real = connection.MIGRATIONS.joinpath("0001_init.sql").read_text("utf-8")
    return (
        connection.Migration(1, "0001_init.sql", real),
        connection.Migration(2, "0002_extra.sql", "CREATE TABLE extra (x INTEGER);"),
    )


def test_upgrade_at_start_is_backed_up(
    cfg_file: Path, db_file: Path, runs: Runs, port: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_game(db_file)
    set_backup(cfg_file, auto=False)
    monkeypatch.setattr(connection, "load_migrations", two_migrations)
    result = serve(port)
    assert result.exit_code == 0, result.output
    (made,) = backup.list_backups(db_file.parent / "backups")
    assert made.reason == "pre-migrate"
    assert "Backed up the database before upgrading it" in result.output
    with closing(connection.connect(db_file, mode="ro")) as conn:
        assert connection.user_version(conn) == 2


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
    monkeypatch.setattr(connection, "load_migrations", two_migrations)
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
