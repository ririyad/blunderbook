"""The Rankings' commands (ROADMAP 16.1): `blunderbook rankings update` and `status`, on their
own and through `blunderbook` with the extension turned on."""

import tomllib
from collections.abc import Iterator
from contextlib import closing
from dataclasses import replace
from datetime import date
from pathlib import Path

import blunderbook_rankings
import pytest
from blunderbook_rankings import commands, extension, fide, lichess, net, store
from rankings_fakes import (  # noqa: F401  (fixtures)
    DEC,
    Server,
    cfg_file,
    serve_fide,
    serve_sites,
    server,
    status,
)
from typer.testing import CliRunner

from blunderbook import cli, config, ext, host
from blunderbook.db import connection

runner = CliRunner()
DOT = "\N{MIDDLE DOT}"


@pytest.fixture(autouse=True)
def today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(blunderbook_rankings, "_today", lambda: date(2026, 11, 12))


@pytest.fixture
def restore_commands() -> Iterator[None]:
    groups = list(cli.app.registered_groups)
    yield
    cli.app.registered_groups[:] = groups


def call(*args: str) -> tuple[int, str]:
    """The exit code and the output, without the daily backup's line."""
    result = runner.invoke(commands, list(args))
    lines = result.output.splitlines(keepends=True)
    return result.exit_code, "".join(x for x in lines if not x.startswith("Daily backup: "))


NOT_YET = (
    "FIDE: not downloaded yet. Run: blunderbook rankings update fide (about 35 MB).\n"
    "Lichess: not downloaded yet. Run: blunderbook rankings update lichess\n"
    "Chess.com: not downloaded yet. Run: blunderbook rankings update chesscom\n"
)
ALL_UPDATED = (
    "FIDE November 2026: standard, rapid and blitz lists updated.\n"
    "Lichess: 5 leaderboards updated.\n"
    "Chess.com: 4 leaderboards updated.\n"
)


def serve_all(fake: Server) -> None:
    serve_fide(fake)
    serve_sites(fake)


def test_status_before_any_update() -> None:
    code, out = call("status")
    assert code == 0, out
    assert out == NOT_YET


def test_update_all_and_status(server: Server) -> None:
    serve_all(server)
    code, out = call("update")
    assert code == 0, out
    assert out == ALL_UPDATED
    code, out = call("status")
    assert code == 0, out
    lines = out.splitlines()
    assert lines[0].startswith(
        f"FIDE: November 2026 lists {DOT} standard 1 {DOT} rapid 1 {DOT} blitz 1 players kept"
        f" {DOT} downloaded "
    )
    assert lines[1].startswith(f"Lichess: 5 leaderboards, top 100 {DOT} downloaded ")
    assert lines[2].startswith(f"Chess.com: 4 leaderboards, top 50 {DOT} downloaded ")
    assert len(lines) == 3  # not stale, no error


@pytest.mark.parametrize(
    ("source", "said"),
    [
        ("fide", "FIDE November 2026: standard, rapid and blitz lists updated.\n"),
        ("lichess", "Lichess: 5 leaderboards updated.\n"),
        ("chesscom", "Chess.com: 4 leaderboards updated.\n"),
    ],
)
def test_update_one_source(server: Server, source: str, said: str) -> None:
    serve_all(server)
    code, out = call("update", source)
    assert code == 0, out
    assert out == said
    hosts = {r.url.host for r in server.requests}
    assert len(hosts) == 1  # only that source's site


def test_update_again(server: Server) -> None:
    serve_all(server)
    call("update")
    code, out = call("update")
    assert code == 0, out
    assert out == (
        "FIDE: already up to date (November 2026 lists).\n"
        "Lichess: 5 leaderboards updated.\n"  # no ETag: always fetched (five small answers)
        "Chess.com: already up to date.\n"
    )


def test_chesscom_contact_in_the_user_agent(server: Server, cfg_file: Path) -> None:
    cfg = config.load(cfg_file)
    config.save(replace(cfg, chesscom=config.ChesscomConfig(contact="me@example.org")), cfg_file)
    serve_all(server)
    code, out = call("update")
    assert code == 0, out
    agents = {r.url.host: r.headers["User-Agent"] for r in server.requests}
    assert agents["api.chess.com"] == (
        f"Blunderbook-Rankings/{net.VERSION} (local chess app; contact: me@example.org)"
    )
    assert agents["lichess.org"] == net.USER_AGENT  # sent to Chess.com only
    assert agents["ratings.fide.com"] == net.USER_AGENT


def test_stale_list(server: Server, monkeypatch: pytest.MonkeyPatch) -> None:
    serve_fide(server)
    call("update", "fide")
    monkeypatch.setattr(blunderbook_rankings, "_today", lambda: date(2026, 12, 2))
    code, out = call("status")
    assert code == 0, out
    assert out.splitlines()[1] == (
        "A newer FIDE list is usually out after the 1st: blunderbook rankings update fide"
    )


def test_one_failure_doesnt_stop_the_others(server: Server) -> None:
    serve_all(server)
    call("update")
    server.on(fide.url("standard"), status(503))
    server.on(lichess.url("blitz"), status(500))
    code, out = call("update")
    assert code == 1
    assert out == (
        f"FIDE: ratings.fide.com answered HTTP 503 for {fide.url('standard')}.\n"
        "The FIDE lists you had are kept.\n"
        f"Lichess: lichess.org answered HTTP 500 for {lichess.url('blitz')}.\n"
        "The Lichess lists you had are kept.\n"
        "Chess.com: already up to date.\n"
    )
    code, out = call("status")
    assert code == 0, out
    lines = out.splitlines()
    assert lines[0].startswith("FIDE: November 2026 lists")
    assert lines[1].startswith("FIDE: the update on ")
    assert lines[1].endswith(
        f" failed: ratings.fide.com answered HTTP 503 for {fide.url('standard')}."
    )
    assert lines[2].startswith("Lichess: 5 leaderboards, top 100")  # still the old ones
    assert lines[3].startswith("Lichess: the update on ")
    assert lines[4].startswith("Chess.com: 4 leaderboards")


def test_stopped(server: Server, monkeypatch: pytest.MonkeyPatch) -> None:
    serve_all(server)

    def interrupted(*args: object, **kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(lichess, "parse", interrupted)
    code, out = call("update")
    assert code == 130
    assert out == (
        "FIDE November 2026: standard, rapid and blitz lists updated.\n"
        "Stopped. The Lichess lists weren't changed.\n"
    )
    with closing(host.open_db(extension)) as conn:
        assert store.source(conn, "fide") is not None  # done before the stop
        assert store.source(conn, "lichess") is None
        assert store.source(conn, "chesscom") is None


def test_takes_the_daily_backup(server: Server, cfg_file: Path) -> None:
    with closing(connection.open_db(config.db_path(), create=True)) as conn:
        conn.execute(
            "INSERT INTO imports (label, kind, started_at) VALUES ('x', 'file', '2026-01-01')"
        )
    serve_all(server)
    result = runner.invoke(commands, ["update"])
    assert result.exit_code == 0, result.output
    assert result.output.startswith("Daily backup: ")


def test_through_blunderbook(server: Server, cfg_file: Path, restore_commands: None) -> None:
    config.save(config.Config(), cfg_file)
    on = runner.invoke(cli.app, ["ext", "enable", "rankings"])
    assert on.exit_code == 0, on.output
    assert on.output.startswith("Turned on rankings (Rankings).\n")
    cli.add_extension_commands()
    serve_all(server)
    result = runner.invoke(cli.app, ["rankings", "update"])
    assert result.exit_code == 0, result.output
    assert ext.db_path(extension).exists()


def test_rankings_db_is_backed_up_once(server: Server, cfg_file: Path) -> None:
    """Only the newest backup of rankings.db is kept: the lists can be downloaded again."""
    with closing(connection.open_db(config.db_path(), create=True)):
        pass
    serve_fide(server, "dec26", DEC)
    call("update", "fide")
    folder = config.backup_folder(config.load(cfg_file))
    for _ in range(3):
        done = runner.invoke(cli.app, ["backup"])
        assert done.exit_code == 0, done.output
    assert "Deleted 1 older backup, keeping only the newest." in done.output
    assert len([p for p in folder.iterdir() if p.name.startswith("rankings-")]) == 1
    assert extension.backups_kept == 1


def test_only_the_host_api_is_used() -> None:
    package = Path(blunderbook_rankings.__file__).parent
    assert ext.boundary_problems(package) == []


def test_version_matches_the_package() -> None:
    project = Path(blunderbook_rankings.__file__).parent.parent / "pyproject.toml"
    assert tomllib.loads(project.read_text("utf-8"))["project"]["version"] == net.VERSION
