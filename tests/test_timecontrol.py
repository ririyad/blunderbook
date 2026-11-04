import pytest

from blunderbook.core import timecontrol
from blunderbook.core.models import TimeControl


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("180", TimeControl(180, 0)),
        ("180+2", TimeControl(180, 2)),
        ("1500+10", TimeControl(1500, 10)),
        ("0+1", TimeControl(0, 1)),
        ("  600+5 \n", TimeControl(600, 5)),
    ],
)
def test_parse_simple(raw: str, expected: TimeControl) -> None:
    assert timecontrol.parse(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "-",
        "?",
        "1/86400",  # Chess.com daily
        "40/7200:3600",  # multi-period OTB
        "*60",  # sandclock
        "180+",
        "+2",
        "180+0.5",
        "3 min",
    ],
)
def test_parse_unknown_is_none(raw: str | None) -> None:
    assert timecontrol.parse(raw) is None


@pytest.mark.parametrize(
    ("base", "inc", "expected"),
    [
        (60, 0, "bullet"),
        (120, 1, "bullet"),  # 160
        (0, 4, "bullet"),  # 160
        (179, 0, "bullet"),  # last second of bullet
        (180, 0, "blitz"),  # boundary: 180 is not < 180
        (180, 2, "blitz"),  # 260
        (300, 3, "blitz"),  # 420
        (479, 0, "blitz"),
        (480, 0, "rapid"),  # boundary
        (600, 5, "rapid"),  # 800
        (900, 10, "rapid"),  # 1300
        (1499, 0, "rapid"),
        (1500, 0, "classical"),  # boundary
        (1500, 10, "classical"),  # 1900
        (5400, 30, "classical"),
    ],
)
def test_speed(base: int, inc: int, expected: str) -> None:
    assert timecontrol.speed(TimeControl(base, inc)) == expected


@pytest.mark.parametrize(
    ("base", "inc", "expected"),
    [
        (180, 2, "3+2"),
        (1500, 10, "25+10"),
        (180, 0, "3+0"),
        (60, 0, "1+0"),
        (0, 1, "0+1"),
        (90, 0, "1.5+0"),
        (30, 0, "0.5+0"),
        (15, 0, "0.25+0"),
        (20, 0, "0.33+0"),
    ],
)
def test_label(base: int, inc: int, expected: str) -> None:
    assert timecontrol.label(TimeControl(base, inc)) == expected


def test_parse_then_classify_round_trip() -> None:
    tc = timecontrol.parse("180+2")
    assert tc is not None
    assert (timecontrol.speed(tc), timecontrol.label(tc)) == ("blitz", "3+2")
