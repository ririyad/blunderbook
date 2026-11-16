"""The Profile's commands (ROADMAP 17.2): `blunderbook profile refresh` and `show`, on their
own and through `blunderbook` with the extension turned on. The sites are faked at
``host.fetch_ratings``: nothing here makes a request."""

from collections.abc import Iterator
from contextlib import closing
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import blunderbook_profile
import pytest
from blunderbook_profile import commands, extension, kind_name, store
from profile_fakes import (  # noqa: F401  (fixtures)
    CHESSCOM,
    LICHESS,
    Sites,
    cfg_file,
    fill_log,
    new_game,
    save_config,
    sites,
)
from typer.testing import CliRunner

from blunderbook import cli, config, ext, host
from blunderbook.core.models import Rating
from blunderbook.db import connection

runner = CliRunner()
DOT = "\N{MIDDLE DOT}"
DASH = "\N{EM DASH}"


@pytest.fixture
def restore_commands() -> Iterator[None]:
    groups = list(cli.app.registered_groups)
    yield
    cli.app.registered_groups[:] = groups


def call(*args: str) -> tuple[int, list[str]]:
    """The exit code and the output's lines, without the daily backup's line and with each
    "fetched ..." time cut off (it's now, in your time zone)."""
    result = runner.invoke(commands, list(args))
    lines = [x for x in result.output.splitlines() if not x.startswith("Daily backup: ")]
    return result.exit_code, [x.split(f" {DOT} fetched ")[0] for x in lines]


LICHESS_LINES = [
    "Lichess (Rashed)",
    f"  Blitz          1647 {DOT} best 1712 {DOT} 401 W / 392 L / 47 D",
    "  Classical      1702?",
    "  Correspondence 1611",
    "  Puzzles        1985",
]
CHESSCOM_LINES = [
    "Chess.com (rashed_blitz)",
    f"  Blitz          1502 {DOT} best 1561 {DOT} 620 W / 598 L / 71 D",
    f"  Puzzles        {DASH} {DOT} best 2104",
]


# ---------------------------------------------------------------- refresh


def test_refresh_asks_both_sites_and_keeps_the_answers(sites: Sites) -> None:
    code, lines = call("refresh")
    assert code == 0
    assert lines == LICHESS_LINES + CHESSCOM_LINES
    assert sites.asked == ["lichess", "chesscom"]
    with closing(host.open_db(extension)) as conn:
        kept = store.latest(conn, "lichess")
        assert kept is not None and kept.ratings == LICHESS.ratings
        assert store.latest(conn, "chesscom") is not None


def test_the_fetched_time_is_shown(sites: Sites) -> None:
    result = runner.invoke(commands, ["refresh", "lichess"])
    now = datetime.now(UTC).astimezone()
    assert result.output.splitlines()[0].startswith(
        f"Lichess (Rashed) {DOT} fetched {now.day} {now:%b %Y} "
    )


@pytest.mark.parametrize(
    ("site", "said"), [("lichess", LICHESS_LINES), ("chesscom", CHESSCOM_LINES)]
)
def test_refresh_one_site(sites: Sites, site: str, said: list[str]) -> None:
    code, lines = call("refresh", site)
    assert (code, lines) == (0, said)
    assert sites.asked == [site]


def test_refresh_skips_a_site_with_no_username(sites: Sites, cfg_file: Path) -> None:
    save_config(cfg_file, chesscom="")
    code, lines = call("refresh")
    assert (code, lines) == (0, LICHESS_LINES)
    assert sites.asked == ["lichess"]


def test_refresh_a_site_with_no_username_says_what_to_set(sites: Sites, cfg_file: Path) -> None:
    save_config(cfg_file, chesscom="")
    code, lines = call("refresh", "chesscom")
    assert code == 1
    assert lines == ["Set your Chess.com username under [chesscom] in config.toml."]
    assert sites.asked == []


def test_refresh_with_no_usernames(sites: Sites, cfg_file: Path) -> None:
    save_config(cfg_file, lichess="", chesscom="")
    code, lines = call("refresh")
    assert code == 1
    assert lines == [
        "No usernames yet: set yours under [lichess] or [chesscom] in config.toml,",
        "or run blunderbook init.",
    ]
    assert sites.asked == []
    assert not ext.db_path(extension).exists()  # nothing was touched


def test_one_site_failing_doesnt_stop_the_other(sites: Sites) -> None:
    assert call("refresh")[0] == 0
    sites.answers["lichess"] = "Lichess is limiting requests right now (HTTP 429). Try again."
    code, lines = call("refresh")
    assert code == 1
    assert lines == [
        "Lichess is limiting requests right now (HTTP 429). Try again.",
        "The Lichess ratings you had are kept.",
        *CHESSCOM_LINES,
    ]
    with closing(host.open_db(extension)) as conn:
        kept = store.latest(conn, "lichess")
        assert kept is not None and kept.ratings == LICHESS.ratings


def test_no_ratings_on_a_site(sites: Sites) -> None:
    sites.answers["lichess"] = replace(LICHESS, ratings=())
    code, lines = call("refresh", "lichess")
    assert (code, lines) == (0, ["Lichess (Rashed)", "  No ratings yet."])


def test_refresh_shows_the_change_since_the_fetch_before(sites: Sites) -> None:
    week_ago = datetime.now(UTC) - timedelta(days=7)
    with closing(host.open_db(extension)) as conn:
        earlier = store.save(conn, LICHESS, at=week_ago)
    sites.answers["lichess"] = replace(
        LICHESS,
        ratings=(
            Rating(kind="blitz", rating=1659, games=830, best=1712),
            Rating(kind="classical", rating=1702, provisional=True, games=3),  # didn't move
            Rating(kind="puzzle", rating=1970, games=2150),
        ),
    )
    code, lines = call("refresh", "lichess")
    since = f"since {earlier.day.day} {earlier.day:%b %Y}"
    assert code == 0
    assert lines == [
        "Lichess (Rashed)",
        f"  Blitz          1659 {DOT} +12 {since} {DOT} best 1712",
        "  Classical      1702?",
        f"  Puzzles        1970 {DOT} -15 {since}",
    ]


def test_refresh_takes_the_daily_backup(sites: Sites) -> None:
    with closing(connection.open_db(config.db_path(), create=True)) as conn:
        conn.execute(
            "INSERT INTO imports (label, kind, started_at) VALUES ('x', 'file', '2026-01-01')"
        )
    result = runner.invoke(commands, ["refresh"])
    assert result.exit_code == 0, result.output
    assert result.output.startswith("Daily backup: ")


def test_a_broken_config_is_a_plain_message(sites: Sites, cfg_file: Path) -> None:
    cfg_file.write_text("engine_depth = 'deep'\n")
    for command in ("refresh", "show"):
        result = runner.invoke(commands, [command])
        assert result.exit_code == 1
        assert "engine_depth" in result.output
    assert sites.asked == []


# ---------------------------------------------------------------- show


def test_show_before_any_refresh(sites: Sites) -> None:
    code, lines = call("show")
    assert code == 0
    assert lines == [
        "Lichess (rashed): not fetched yet. Run: blunderbook profile refresh lichess",
        "Chess.com (rashed_blitz): not fetched yet. Run: blunderbook profile refresh chesscom",
    ]
    assert sites.asked == []  # show never asks a site


def test_show_with_no_username(sites: Sites, cfg_file: Path) -> None:
    save_config(cfg_file, lichess="")
    assert call("show")[1] == [
        "Lichess: no username under [lichess] in config.toml.",
        "Chess.com (rashed_blitz): not fetched yet. Run: blunderbook profile refresh chesscom",
    ]


def test_show_what_was_fetched(sites: Sites) -> None:
    call("refresh")
    sites.asked.clear()
    code, lines = call("show")
    assert (code, lines) == (0, LICHESS_LINES + CHESSCOM_LINES)
    assert sites.asked == []


def test_show_keeps_a_fetch_after_the_username_is_removed(sites: Sites, cfg_file: Path) -> None:
    call("refresh", "lichess")
    save_config(cfg_file, lichess="")
    assert call("show")[1][: len(LICHESS_LINES)] == LICHESS_LINES


def test_show_adds_your_rating_from_your_games(sites: Sites) -> None:
    fill_log(
        new_game(1, "lichess", "blitz", date(2026, 11, 1), 1640),
        new_game(2, "lichess", "blitz", date(2026, 11, 9), 1647, me="black"),
        new_game(3, "chesscom", "rapid", date(2026, 10, 7), 1655),
        new_game(4, "otb", "classical", date(2026, 11, 10), 1800),  # not a site rating
    )
    assert call("show")[1][2:] == [
        "From your games:",
        f"  Lichess blitz       1647 {DOT} 9 Nov 2026",
        f"  Chess.com rapid     1655 {DOT} 7 Oct 2026",
    ]


def test_daily_chess_is_correspondence_on_lichess() -> None:
    assert kind_name("lichess", "daily") == "Correspondence"
    assert kind_name("chesscom", "daily") == "Daily"
    assert kind_name("lichess", "puzzle") == "Puzzles"


# ---------------------------------------------------------------- with Blunderbook


def test_through_blunderbook(sites: Sites, cfg_file: Path, restore_commands: None) -> None:
    config.save(
        config.Config(lichess=config.LichessConfig(username="rashed", token="lip_secret")),
        cfg_file,
    )
    on = runner.invoke(cli.app, ["ext", "enable", "profile"])
    assert on.exit_code == 0, on.output
    assert on.output.startswith("Turned on profile (Profile).\n")
    cli.add_extension_commands()
    result = runner.invoke(cli.app, ["profile", "refresh"])
    assert result.exit_code == 0, result.output
    assert "lip_secret" not in result.output
    assert sites.asked == ["lichess"]
    assert ext.db_path(extension).exists()


def test_profile_db_is_in_the_backups(sites: Sites, cfg_file: Path) -> None:
    with closing(connection.open_db(config.db_path(), create=True)):
        pass
    call("refresh")
    done = runner.invoke(cli.app, ["backup"])
    assert done.exit_code == 0, done.output
    folder = config.backup_folder(config.load(cfg_file))
    assert len([p for p in folder.iterdir() if p.name.startswith("profile-")]) == 1
    assert extension.backups_kept is None  # its history can't be downloaded again


def test_only_the_host_api_is_used() -> None:
    package = Path(blunderbook_profile.__file__).parent
    assert ext.boundary_problems(package) == []
