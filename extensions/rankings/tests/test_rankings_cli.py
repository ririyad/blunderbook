"""The Rankings' commands (ROADMAP 16.1): `blunderbook rankings update` and `status`, on their
own and through `blunderbook` with the extension turned on."""

import tomllib
from collections.abc import Iterator
from contextlib import closing
from datetime import date
from pathlib import Path

import blunderbook_rankings
import pytest
from blunderbook_rankings import commands, extension, fide, net, store
from rankings_fakes import (  # noqa: F401  (fixtures)
    DEC,
    Server,
    cfg_file,
    serve_fide,
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


def test_status_before_any_update() -> None:
    code, out = call("status")
    assert code == 0, out
    assert out == (
        "FIDE: not downloaded yet. Run: blunderbook rankings update fide (about 35 MB).\n"
    )


def test_update_and_status(server: Server) -> None:
    serve_fide(server)
    code, out = call("update", "fide")
    assert code == 0, out
    assert out == "FIDE November 2026: standard, rapid and blitz lists updated.\n"
    code, out = call("status")
    assert code == 0, out
    lines = out.splitlines()
    assert lines[0].startswith(
        f"FIDE: November 2026 lists {DOT} standard 1 {DOT} rapid 1 {DOT} blitz 1 players kept"
        f" {DOT} downloaded "
    )
    assert len(lines) == 1  # not stale, no error


def test_update_defaults_to_fide(server: Server) -> None:
    serve_fide(server)
    code, out = call("update")
    assert code == 0, out
    assert out.startswith("FIDE November 2026")


def test_update_again(server: Server) -> None:
    serve_fide(server)
    call("update")
    code, out = call("update")
    assert code == 0, out
    assert out == "FIDE: already up to date (November 2026 lists).\n"


def test_stale_list(server: Server, monkeypatch: pytest.MonkeyPatch) -> None:
    serve_fide(server)
    call("update")
    monkeypatch.setattr(blunderbook_rankings, "_today", lambda: date(2026, 12, 2))
    code, out = call("status")
    assert code == 0, out
    assert out.splitlines()[1] == (
        "A newer FIDE list is usually out after the 1st: blunderbook rankings update fide"
    )


def test_failed_update(server: Server) -> None:
    serve_fide(server)
    call("update")
    server.on(fide.url("standard"), status(503))
    code, out = call("update")
    assert code == 1
    assert out == (
        f"FIDE: ratings.fide.com answered HTTP 503 for {fide.url('standard')}.\n"
        "The lists you had are kept.\n"
    )
    code, out = call("status")
    assert code == 0, out
    assert out.splitlines()[0].startswith("FIDE: November 2026 lists")
    assert out.splitlines()[-1].endswith(
        f"failed: ratings.fide.com answered HTTP 503 for {fide.url('standard')}."
    )


def test_stopped(server: Server, monkeypatch: pytest.MonkeyPatch) -> None:
    serve_fide(server)

    def interrupted(*args: object, **kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(fide, "read_list", interrupted)
    code, out = call("update")
    assert code == 130
    assert out == "Stopped. Nothing was changed.\n"
    with closing(host.open_db(extension)) as conn:
        assert store.source(conn, "fide") is None


def test_takes_the_daily_backup(server: Server, cfg_file: Path) -> None:
    with closing(connection.open_db(config.db_path(), create=True)) as conn:
        conn.execute(
            "INSERT INTO imports (label, kind, started_at) VALUES ('x', 'file', '2026-01-01')"
        )
    serve_fide(server)
    result = runner.invoke(commands, ["update"])
    assert result.exit_code == 0, result.output
    assert result.output.startswith("Daily backup: ")


def test_through_blunderbook(server: Server, cfg_file: Path, restore_commands: None) -> None:
    config.save(config.Config(), cfg_file)
    on = runner.invoke(cli.app, ["ext", "enable", "rankings"])
    assert on.exit_code == 0, on.output
    assert on.output.startswith("Turned on rankings (Rankings).\n")
    cli.add_extension_commands()
    serve_fide(server)
    result = runner.invoke(cli.app, ["rankings", "update"])
    assert result.exit_code == 0, result.output
    assert ext.db_path(extension).exists()


def test_rankings_db_is_backed_up(server: Server, cfg_file: Path) -> None:
    with closing(connection.open_db(config.db_path(), create=True)):
        pass
    serve_fide(server, "dec26", DEC)
    call("update")
    done = runner.invoke(cli.app, ["backup"])
    assert done.exit_code == 0, done.output
    folder = config.backup_folder(config.load(cfg_file))
    assert any(p.name.startswith("rankings-") for p in folder.iterdir())


def test_only_the_host_api_is_used() -> None:
    package = Path(blunderbook_rankings.__file__).parent
    assert ext.boundary_problems(package) == []


def test_version_matches_the_package() -> None:
    project = Path(blunderbook_rankings.__file__).parent.parent / "pyproject.toml"
    assert tomllib.loads(project.read_text("utf-8"))["project"]["version"] == net.VERSION
