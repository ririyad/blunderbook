from pathlib import Path

import pytest

from blunderbook.core import pgn
from blunderbook.core.models import SourceInfo
from blunderbook.core.source import detect_source

FIXTURES = Path(__file__).parent / "fixtures" / "pgn"


def headers_of(name: str) -> dict[str, str]:
    result = pgn.parse((FIXTURES / name).read_text("utf-8"))
    return dict(result.games[0].headers)


# ---------------------------------------------------------------- fixtures (CLAUDE.md §12)

LICHESS_SCHOLAR = SourceInfo("lichess", "Lichess", "sCh0lar1", "https://lichess.org/sCh0lar1")
LICHESS_BACK_RANK = SourceInfo("lichess", "Lichess", "bAckR4nk", "https://lichess.org/bAckR4nk")
CHESSCOM_LEGAL = SourceInfo(
    "chesscom", "Chess.com", "live/140512345678", "https://www.chess.com/game/live/140512345678"
)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("qgd_elephant.pgn", SourceInfo("pgn", "PGN file")),
        ("scholars_mate.pgn", LICHESS_SCHOLAR),
        ("legal_trap.pgn", CHESSCOM_LEGAL),
        ("blackburne_shilling.pgn", SourceInfo("pgn", "PGN file")),
        ("back_rank.pgn", LICHESS_BACK_RANK),
        ("petroff_trap.pgn", SourceInfo("pgn", "PGN file")),
        ("otb_club_no_clocks.pgn", SourceInfo("otb", "Over the board · Dhaka Chess Club")),
        ("chesscom_unmatched_name.pgn", SourceInfo("chesscom", "Chess.com")),
        ("multi_game.pgn", SourceInfo("otb", "Over the board · Dhaka Chess Club")),
    ],
)
def test_fixture_sources(name: str, expected: SourceInfo) -> None:
    assert detect_source(headers_of(name)) == expected


# ---------------------------------------------------------------- Lichess


@pytest.mark.parametrize(
    "site",
    [
        "https://lichess.org/abcd1234",
        "http://lichess.org/abcd1234",
        "https://www.lichess.org/abcd1234",
        "lichess.org/abcd1234",
        "https://lichess.org/abcd1234wxyz",  # 12-character full id from a player's link
        "https://lichess.org/abcd1234/black",
        "https://lichess.org/abcd1234/",
        "https://lichess.org/abcd1234#32",
        "https://LICHESS.ORG/abcd1234",
    ],
)
def test_lichess_game_id(site: str) -> None:
    info = detect_source({"Site": site})
    assert info == SourceInfo("lichess", "Lichess", "abcd1234", "https://lichess.org/abcd1234")


@pytest.mark.parametrize(
    "site",
    [
        "https://lichess.org",
        "lichess.org",
        "https://lichess.org/study/AbCdEfGh/IjKlMnOp",
        "https://lichess.org/broadcast/round/AbCdEfGh",
        "https://lichess.org/analysis",
        "https://lichess.org/abc123",  # too short to be a game id
        "https://lichess.org/abcd12345",  # 9 characters: neither an id nor a full id
    ],
)
def test_lichess_without_a_game_id(site: str) -> None:
    assert detect_source({"Site": site}) == SourceInfo("lichess", "Lichess")


def test_lichess_named_only_in_event() -> None:
    info = detect_source({"Event": "Lichess Titled Arena", "Site": "?"})
    assert info == SourceInfo("lichess", "Lichess")


def test_lichess_id_is_case_sensitive() -> None:
    assert detect_source({"Site": "https://lichess.org/AbCd1234"}).game_id == "AbCd1234"


# ---------------------------------------------------------------- Chess.com


@pytest.mark.parametrize(
    ("link", "game_id"),
    [
        ("https://www.chess.com/game/live/140512345678", "live/140512345678"),
        ("https://www.chess.com/game/daily/987654321", "daily/987654321"),
        ("https://www.chess.com/analysis/game/live/140512345678", "live/140512345678"),
        ("https://www.chess.com/live/game/140512345678", "live/140512345678"),
        ("https://www.chess.com/daily/game/987654321", "daily/987654321"),
        ("https://www.chess.com/game/live/140512345678?move=12", "live/140512345678"),
        ("https://www.Chess.com/Game/Live/140512345678", "live/140512345678"),
    ],
)
def test_chesscom_game_id_from_link(link: str, game_id: str) -> None:
    info = detect_source({"Site": "Chess.com", "Link": link})
    assert info == SourceInfo(
        "chesscom", "Chess.com", game_id, f"https://www.chess.com/game/{game_id}"
    )


def test_chesscom_game_url_in_site() -> None:
    info = detect_source({"Site": "https://www.chess.com/game/live/140512345678"})
    assert info.game_id == "live/140512345678"


def test_chesscom_link_wins_over_site() -> None:
    info = detect_source(
        {
            "Site": "https://www.chess.com/game/live/111",
            "Link": "https://www.chess.com/game/live/222",
        }
    )
    assert info.game_id == "live/222"


@pytest.mark.parametrize(
    "headers",
    [
        {"Site": "Chess.com"},
        {"Site": "chess.com", "Link": "https://www.chess.com/member/rashed_blitz"},
        {"Site": "?", "Event": "Chess.com Rapid Championship"},
    ],
)
def test_chesscom_without_a_game_id(headers: dict[str, str]) -> None:
    assert detect_source(headers) == SourceInfo("chesscom", "Chess.com")


@pytest.mark.parametrize(
    ("headers", "source"),
    [
        ({"Site": "playchess.com"}, "pgn"),  # ChessBase's server, not Chess.com
        ({"Site": "https://www.playchess.com/game/live/1"}, "pgn"),
        ({"Site": "Dhaka", "Event": "Playchess.com Open"}, "otb"),
        ({"Site": "chess.community.example"}, "pgn"),
        ({"Site": "https://www.chess.com"}, "chesscom"),
        ({"Site": "?", "Event": "Live Chess (chess.com)"}, "chesscom"),
    ],
)
def test_chesscom_is_matched_as_a_whole_name(headers: dict[str, str], source: str) -> None:
    assert detect_source(headers).source == source


# ---------------------------------------------------------------- over the board / PGN file


@pytest.mark.parametrize(
    "site",
    ["Dhaka Chess Club", "Dhaka BAN", "St. Louis USA", "St.Louis", "INT", "Internet"],
)
def test_over_the_board(site: str) -> None:
    assert detect_source({"Site": site}) == SourceInfo("otb", f"Over the board · {site}")


def test_over_the_board_label_is_trimmed() -> None:
    assert (
        detect_source({"Site": "  Dhaka Chess Club "}).label == "Over the board · Dhaka Chess Club"
    )


@pytest.mark.parametrize(
    "site",
    [
        "https://www.chessbase.com",
        "http://example.org/games/1",
        "playchess.com",
        "www.chess24.com/en/game/123",
        "ftp://files.example.net",
    ],
)
def test_other_websites_are_pgn_files(site: str) -> None:
    assert detect_source({"Site": site}) == SourceInfo("pgn", "PGN file")


@pytest.mark.parametrize(
    "headers",
    [{}, {"Site": "?"}, {"Site": ""}, {"Site": "  "}, {"Event": "Casual game", "Site": "?"}],
)
def test_no_site_is_a_pgn_file(headers: dict[str, str]) -> None:
    assert detect_source(headers) == SourceInfo("pgn", "PGN file")


def test_event_alone_never_means_over_the_board() -> None:
    assert detect_source({"Event": "Club rapid night"}).source == "pgn"
