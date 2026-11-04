import json

import pytest

from blunderbook.core.models import CAUSES, Eval


def test_causes_fixed_order() -> None:
    assert CAUSES == (
        "Hung a piece",
        "Missed their threat",
        "Missed my tactic",
        "Miscalculated a line",
        "Time trouble",
        "Moved too fast",
        "Wrong plan",
        "Opening gap",
        "Endgame technique",
        "Overconfident / tilt",
        "Skipped blunder check",
        "Other",
    )


@pytest.mark.parametrize(
    ("ev", "stored"),
    [
        (Eval(cp=36), '{"cp": 36}'),
        (Eval(cp=-120), '{"cp": -120}'),
        (Eval(cp=0), '{"cp": 0}'),
        (Eval(mate=3), '{"mate": 3}'),
        (Eval(mate=-2), '{"mate": -2}'),
        (Eval(mate=0), '{"mate": 0}'),
    ],
)
def test_eval_json_round_trip(ev: Eval, stored: str) -> None:
    assert json.dumps(ev.to_dict()) == stored
    assert Eval.from_dict(json.loads(stored)) == ev


@pytest.mark.parametrize("kwargs", [{}, {"cp": 10, "mate": 2}])
def test_eval_needs_exactly_one_value(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        Eval(**kwargs)


@pytest.mark.parametrize("bad", [1.5, True, "36"])
def test_eval_rejects_non_int(bad: object) -> None:
    with pytest.raises(TypeError):
        Eval(cp=bad)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "data",
    [{}, {"cp": 1, "mate": 1}, {"score": 1}, {"cp": 1, "extra": 0}],
)
def test_eval_from_dict_rejects_bad_shape(data: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        Eval.from_dict(data)


@pytest.mark.parametrize("data", [{"cp": 1.0}, {"mate": "2"}, {"cp": None}])
def test_eval_from_dict_rejects_non_int(data: dict[str, object]) -> None:
    with pytest.raises(TypeError):
        Eval.from_dict(data)
