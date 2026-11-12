"""Reading FIDE's lists (ROADMAP 16.1): one player's fields, the zip, and which players are
kept (the world top 100 and each federation's top 50 in Open, Women, Juniors and Girls)."""

from pathlib import Path

import pytest
from blunderbook_rankings import fide, net
from rankings_fakes import (  # noqa: F401  (fixtures)
    FIXTURES,
    cfg_file,
    fide_zip,
    player,
    xml,
)


def write(tmp_path: Path, data: bytes, name: str = "list.zip") -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def read(tmp_path: Path, *players: dict[str, str], member: str = "standard_nov26frl_xml.xml"):
    path = write(tmp_path, fide_zip(xml(*players), member))
    return fide.read_list(path, "standard", "2026-01")


# ---------------------------------------------------------------- one player


def test_player_fields() -> None:
    got = fide.player(player(1503014, 2830, name="Carlsen,  Magnus ", title="GM"))
    assert got == fide.Player(1503014, "Carlsen, Magnus", "NOR", "M", "GM", 1990, 2830, 9)


@pytest.mark.parametrize("flag", ["i", "wi", "I", "WI"])
def test_inactive_players_are_left_out(flag: str) -> None:
    assert fide.player(player(1, 2500, flag=flag)) is None


def test_w_flag_is_an_active_woman() -> None:
    got = fide.player(player(1, 2400, sex="F", flag="w"))
    assert got is not None and got.sex == "F"


@pytest.mark.parametrize(
    "fields",
    [
        {"rating": "0"},
        {"rating": ""},
        {"fideid": ""},
        {"fideid": "x"},
        {"name": "  "},
    ],
)
def test_unrated_or_unnamed_players_are_left_out(fields: dict[str, str]) -> None:
    assert fide.player(player(1, 2400) | fields) is None


def test_titles() -> None:
    def title(**fields: str) -> str | None:
        got = fide.player(player(1, 2400) | fields)
        assert got is not None
        return got.title

    assert title(title="GM") == "GM"
    assert title(title="g") == "GM"  # the TXT lists' codes
    assert title(title="wg") == "WGM"
    assert title(title="", w_title="WIM") == "WIM"  # a woman's title when there's no other
    assert title(title="IM", w_title="WGM") == "IM"
    assert title(title="") is None


def test_missing_fields_are_none() -> None:
    got = fide.player(player(1, 2400, fed=" ", sex="", born="0", games=""))
    assert got is not None
    assert (got.fed, got.sex, got.born, got.games) == (None, None, None, None)


def test_member_month() -> None:
    assert fide.member_month("standard_nov26frl_xml.xml") == "2026-11"
    assert fide.member_month("BLITZ_JAN27FRL_XML.XML") == "2027-01"
    assert fide.member_month("players.xml") is None


def test_month_label() -> None:
    assert fide.month_label("2026-11") == "November 2026"
    assert fide.month_label("2027-01") == "January 2027"


# ---------------------------------------------------------------- the zip


def test_the_sample_list(tmp_path: Path) -> None:
    data = (FIXTURES / "fide_standard_sample.xml").read_bytes()
    got = fide.read_list(write(tmp_path, fide_zip(data)), "standard", "2026-01")
    assert got.month == "2026-11"
    assert (got.read, got.active) == (7, 4)  # one inactive, one unrated, one inactive woman
    assert [(p.name, p.title, p.fed) for p in got.players] == [
        ("Smith, John", "GM", "ENG"),
        ("Ivanova, Anna", "IM", "ESP"),
        ("Chowdhury, Nila", "WFM", "BAN"),
        ("Rahman, Karim", None, "BAN"),
    ]
    assert got.players[-1].born is None


def test_month_falls_back(tmp_path: Path) -> None:
    got = read(tmp_path, player(1, 2400), member="players_list.xml")
    assert got.month == "2026-01"


def test_progress_and_stop(tmp_path: Path) -> None:
    path = write(tmp_path, fide_zip(xml(*(player(i, 2000 + i % 500) for i in range(1, 2501)))))
    seen: list[float] = []
    got = fide.read_list(path, "rapid", "2026-11", seen.append)
    assert got.read == 2500 and got.speed == "rapid"
    assert seen[-1] == 1.0 and seen == sorted(seen) and len(seen) >= 3
    with pytest.raises(net.Stopped):
        fide.read_list(path, "rapid", "2026-11", stop=lambda: True)


def test_not_a_zip(tmp_path: Path) -> None:
    with pytest.raises(fide.BadList, match="FIDE's standard list isn't a zip file"):
        fide.read_list(write(tmp_path, b"<html>Not found</html>"), "standard", "2026-11")


def test_two_files_in_the_zip(tmp_path: Path) -> None:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("a.xml", xml(player(1, 2400)))
        archive.writestr("b.xml", xml(player(2, 2400)))
    with pytest.raises(fide.BadList, match="should hold one XML file"):
        fide.read_list(write(tmp_path, buf.getvalue()), "standard", "2026-11")


def test_not_xml_in_the_zip(tmp_path: Path) -> None:
    path = write(tmp_path, fide_zip(b"ID NAME", "standard_nov26frl.txt"))
    with pytest.raises(fide.BadList, match="should hold one XML file"):
        fide.read_list(path, "standard", "2026-11")


def test_broken_xml(tmp_path: Path) -> None:
    path = write(tmp_path, fide_zip(b"<playerslist><player><fideid>1</player>"))
    with pytest.raises(fide.BadList, match="FIDE's standard list couldn't be read"):
        fide.read_list(path, "standard", "2026-11")


def test_too_big(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = write(tmp_path, fide_zip(xml(player(1, 2400))))
    monkeypatch.setattr(fide, "MAX_XML_BYTES", 100)
    with pytest.raises(fide.BadList, match="too big"):
        fide.read_list(path, "standard", "2026-11")


# ---------------------------------------------------------------- who's kept


def kept(players: list[dict[str, str]], tmp_path: Path) -> set[int]:
    return {p.fide_id for p in read(tmp_path, *players).players}


def test_world_top_100_and_federation_top_50(tmp_path: Path) -> None:
    big = [player(i, 2000 + i, fed="AAA") for i in range(1, 151)]  # 150 players
    small = [player(1000 + i, 1500 + i, fed="BBB") for i in range(1, 11)]
    got = kept(big + small, tmp_path)
    # The world's top 100 are all AAA (51..150); BBB's ten are its top 50; AAA's top 50 are
    # among the world's.
    assert got == set(range(51, 151)) | set(range(1001, 1011))


def test_women_juniors_and_girls_lists(tmp_path: Path) -> None:
    strong = [player(i, 2600 + i, fed="AAA") for i in range(1, 151)]
    woman = player(500, 1800, fed="AAA", sex="F")
    junior = player(501, 1700, fed="AAA", born="2006")  # 20 in 2026: still a junior
    too_old = player(502, 1700, fed="AAA", born="2005")
    girl = player(503, 1600, fed="AAA", sex="F", born="2012")
    got = kept([*strong, woman, junior, too_old, girl], tmp_path)
    assert {500, 501, 503} <= got
    assert 502 not in got


def test_kept_players_are_sorted(tmp_path: Path) -> None:
    got = read(tmp_path, player(3, 2500), player(1, 2600), player(2, 2500)).players
    assert [p.fide_id for p in got] == [1, 2, 3]  # equal ratings: the lower ID first


def test_ties_at_the_cut(tmp_path: Path) -> None:
    same = [player(i, 2400, fed="AAA") for i in range(1, 121)]
    assert kept(same, tmp_path) == set(range(1, 101))  # the lower IDs, as the list sorts


def test_categories() -> None:
    def cats(**fields: str) -> list[str]:
        got = fide.player(player(1, 2400) | fields)
        assert got is not None
        return list(fide.categories(got, 2026))

    assert cats() == ["open"]
    assert cats(sex="F") == ["open", "women"]
    assert cats(birthday="2010") == ["open", "juniors"]
    assert cats(sex="F", birthday="2010") == ["open", "women", "juniors", "girls"]
    assert cats(birthday="") == ["open"]


# ---------------------------------------------------------------- a real list (2026-11-12)


def test_a_recorded_list(tmp_path: Path) -> None:
    """Five records from FIDE's real blitz list. Its member has no month in its name, so
    the month is the one the update passes in (from the file's Last-Modified)."""
    data = (FIXTURES / "fide_blitz_recorded.xml").read_bytes()
    path = write(tmp_path, fide_zip(data, "blitz_rating_list.xml"))
    got = fide.read_list(path, "blitz", "2026-11")
    assert got.month == "2026-11"
    assert (got.read, got.active) == (5, 4)  # Kasparov is inactive
    assert [(p.name, p.fed, p.title, p.rating) for p in got.players] == [
        ("Carlsen, Magnus", "NOR", "GM", 2860),
        ("Nakamura, Hikaru", "USA", "GM", 2800),
        ("Gukesh D", "IND", "GM", 2659),
        ("Hou, Yifan", "CHN", "GM", 2521),  # GM over her WGM
    ]
    hou = got.players[-1]
    assert (hou.sex, hou.born) == ("F", 1994)
    gukesh = got.players[2]
    assert list(fide.categories(gukesh, 2026)) == ["open", "juniors"]  # born 2006: 20 in 2026
