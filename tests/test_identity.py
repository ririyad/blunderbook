import hashlib
from pathlib import Path

import pytest

from blunderbook.core import pgn
from blunderbook.core.identity import FINGERPRINT_PLIES, fingerprint, my_side, normalize_name
from blunderbook.core.models import ParsedGame, SourceInfo
from blunderbook.core.source import detect_source

FIXTURES = Path(__file__).parent / "fixtures" / "pgn"
NAMES = ["Rashed"]


def games_in(name: str) -> tuple[ParsedGame, ...]:
    return pgn.parse((FIXTURES / name).read_text("utf-8")).games


def only_game(text: str) -> ParsedGame:
    result = pgn.parse(text)
    assert result.problems == ()
    assert len(result.games) == 1
    return result.games[0]


def sha1(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()


def fp(game: ParsedGame) -> str:
    return fingerprint(game, detect_source(game.headers))


# ---------------------------------------------------------------- side detection (§7.3)


@pytest.mark.parametrize(
    ("name", "side"),
    [
        ("qgd_elephant.pgn", "white"),
        ("scholars_mate.pgn", "black"),
        ("legal_trap.pgn", "black"),
        ("blackburne_shilling.pgn", "white"),
        ("back_rank.pgn", "white"),
        ("petroff_trap.pgn", "black"),
        ("otb_club_no_clocks.pgn", "white"),
        ("chesscom_unmatched_name.pgn", None),  # needs_side
    ],
)
def test_fixture_sides(name: str, side: str | None) -> None:
    (game,) = games_in(name)
    assert my_side(game.headers, NAMES) == side


def test_multi_game_sides() -> None:
    assert [my_side(g.headers, NAMES) for g in games_in("multi_game.pgn")] == [
        "white",
        "white",
        None,  # game 4 is a bare move list with no players
    ]


def test_configured_username_finds_the_unmatched_side() -> None:
    (game,) = games_in("chesscom_unmatched_name.pgn")
    assert my_side(game.headers, [*NAMES, "", "rashed_blitz"]) == "black"


@pytest.mark.parametrize(
    ("header", "names"),
    [
        ("Rashed", ["rashed"]),
        ("RASHED", ["Rashed"]),
        ("  Rashed  ", ["Rashed"]),
        ("Rashed", ["  Rashed "]),
        ("Straße", ["STRASSE"]),  # casefold, not just lower
    ],
)
def test_matching_is_trimmed_and_case_insensitive(header: str, names: list[str]) -> None:
    assert my_side({"White": header, "Black": "Karim S."}, names) == "white"


def test_no_partial_matches() -> None:
    headers = {"White": "Rashed Khan", "Black": "rashed_blitz"}
    assert my_side(headers, ["Rashed"]) is None


def test_both_sides_matching_is_never_guessed() -> None:
    headers = {"White": "rashed_blitz", "Black": "Rashed"}
    assert my_side(headers, ["Rashed", "rashed_blitz"]) is None


@pytest.mark.parametrize("names", [[], [""], ["  "], ["?"]])
def test_empty_or_unknown_names_never_match(names: list[str]) -> None:
    assert my_side({"White": "?", "Black": ""}, names) is None
    assert my_side({}, names) is None


def test_normalize_name() -> None:
    assert normalize_name("  Rashed_Blitz ") == "rashed_blitz"


# ---------------------------------------------------------------- fingerprints (§7.4)


def test_site_game_id_fingerprints() -> None:
    (lichess,) = games_in("scholars_mate.pgn")
    (chesscom,) = games_in("legal_trap.pgn")
    assert fp(lichess) == sha1("lichess:sCh0lar1")
    assert fp(chesscom) == sha1("chesscom:live/140512345678")


def test_site_id_ignores_everything_else() -> None:
    a = only_game('[Site "https://lichess.org/abcd1234"]\n[White "A"]\n\n1. e4 *')
    b = only_game('[Site "https://lichess.org/abcd1234/black"]\n[White "B"]\n\n1. d4 d5 *')
    assert fp(a) == fp(b) == sha1("lichess:abcd1234")


def test_content_fingerprint_matches_the_spec() -> None:
    (game,) = games_in("qgd_elephant.pgn")
    moves = " ".join(p.san for p in game.plies[:30])
    assert fp(game) == sha1(f"rashed|karim s.|2026-10-12|{moves}")


def test_content_fingerprint_uses_the_first_30_plies() -> None:
    moves = (
        "1. Nf3 Nf6 2. Ng1 Ng8 3. Nf3 Nf6 4. Ng1 Ng8 5. Nf3 Nf6 6. Ng1 Ng8 7. Nf3 Nf6 "
        "8. Ng1 Ng8 9. Nf3 Nf6 10. Ng1 Ng8 11. Nf3 Nf6 12. Ng1 Ng8 13. Nf3 Nf6 "
        "14. Ng1 Ng8 15. Nf3 Nf6"
    )
    headers = '[White "A"]\n[Black "B"]\n[Date "2026.01.02"]\n\n'
    base = only_game(f"{headers}{moves} *")
    longer = only_game(f"{headers}{moves} 16. e4 e5 *")
    assert len(base.plies) == FINGERPRINT_PLIES
    assert fp(base) == fp(longer)


def test_content_fingerprint_ignores_formatting_comments_and_clocks() -> None:
    plain = only_game('[White "Rashed"]\n[Black "Karim"]\n[Date "2026.10.12"]\n\n1. e4 e5 2. Nf3 *')
    noisy = only_game(
        '[Event "Casual"]\r\n[White " RASHED "]\r\n[Black "karim"]\r\n[Date "2026.10.12"]\r\n'
        '[Result "1-0"]\r\n\r\n1. e4 { [%clk 0:03:00] } e5 $1 (1... c5 2. Nf3) '
        "2. Nf3 { [%eval 0.3] } 1-0\r\n"
    )
    assert fp(plain) == fp(noisy)


@pytest.mark.parametrize(
    "change",
    [
        ('[White "Rashed"]', '[White "Imran"]'),
        ('[Black "Karim"]', '[Black "Karim S."]'),
        ('[Date "2026.10.12"]', '[Date "2026.10.13"]'),
        ("2. Nf3", "2. Nc3"),
    ],
)
def test_content_fingerprint_changes_with_the_game(change: tuple[str, str]) -> None:
    text = '[White "Rashed"]\n[Black "Karim"]\n[Date "2026.10.12"]\n\n1. e4 e5 2. Nf3 *'
    assert fp(only_game(text)) != fp(only_game(text.replace(*change)))


def test_swapped_colours_are_different_games() -> None:
    a = only_game('[White "Rashed"]\n[Black "Karim"]\n\n1. e4 *')
    b = only_game('[White "Karim"]\n[Black "Rashed"]\n\n1. e4 *')
    assert fp(a) != fp(b)


def test_partial_or_missing_dates() -> None:
    (petroff,) = games_in("petroff_trap.pgn")  # Date "2026.??.??" is kept as written
    moves = " ".join(p.san for p in petroff.plies)
    assert fp(petroff) == sha1(f"coach imran|rashed|2026.??.??|{moves}")
    unknown = only_game('[Date "????.??.??"]\n\n1. e4 *')
    missing = only_game("1. e4 *")
    assert fp(unknown) == fp(missing) == sha1("|||e4")


def test_same_moves_from_different_positions_dont_collide() -> None:
    a = only_game('[SetUp "1"]\n[FEN "4k3/8/8/8/8/8/8/R3K3 w - - 0 1"]\n\n1. Ra8+ *')
    b = only_game('[SetUp "1"]\n[FEN "4k3/8/8/8/8/8/7P/R3K3 w - - 0 1"]\n\n1. Ra8+ *')
    assert fp(a) != fp(b)
    assert fp(a) == sha1("|||Ra8+|4k3/8/8/8/8/8/8/R3K3 w - - 0 1")


def test_every_fixture_game_has_its_own_fingerprint() -> None:
    names = sorted(p.name for p in FIXTURES.glob("*.pgn"))
    prints = [fp(g) for name in names for g in games_in(name)]
    assert len(prints) == 11
    assert len(set(prints)) == len(prints)
    assert all(len(p) == 40 for p in prints)


def test_fingerprint_needs_the_source_it_was_given() -> None:
    (game,) = games_in("scholars_mate.pgn")
    assert fingerprint(game, SourceInfo("pgn", "PGN file")) != fp(game)
