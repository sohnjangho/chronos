"""Condition 저장 모양(R5)과 자동 점검 여부."""

import json

import pytest

from app.harness.conditions import Condition

WINTER = Condition(
    "i1",
    "input",
    "blocked_period",
    {"start_md": [12, 1], "end_md": [2, 28], "tag": "타설"},
    "동절기 타설 금지",
    "프롬프트",
    enabled=False,
    overridden_by="i2",
)


def test_round_trip_through_json():
    d = json.loads(json.dumps(WINTER.to_dict()))
    assert d == {
        "id": "i1",
        "layer": "input",
        "kind": "blocked_period",
        "params": {"start_md": [12, 1], "end_md": [2, 28], "tag": "타설"},
        "text": "동절기 타설 금지",
        "source": "프롬프트",
        "enabled": False,
        "overridden_by": "i2",
    }
    assert Condition.from_dict(d) == WINTER


def test_to_dict_does_not_share_params():
    d = WINTER.to_dict()
    d["params"]["start_md"][0] = 11
    assert WINTER.params["start_md"] == [12, 1]


def test_from_dict_fills_missing_optional_keys():
    d = {"id": "c1", "layer": "input", "kind": "finish_by", "params": {"date": "2027-03-04"},
         "text": "준공 03.04 이전", "source": "프롬프트"}
    c = Condition.from_dict(d)
    assert (c.enabled, c.overridden_by) == (True, None)
    assert c == Condition("c1", "input", "finish_by", {"date": "2027-03-04"}, "준공 03.04 이전", "프롬프트")


@pytest.mark.parametrize(("field", "value"), [("kind", "made_up"), ("layer", "team")])
def test_from_dict_rejects_unknown_kind_or_layer(field, value):
    d = {**WINTER.to_dict(), field: value}
    with pytest.raises(ValueError):
        Condition.from_dict(d)


def test_checkable():
    def make(kind: str) -> Condition:
        return Condition("c", "input", kind, {}, "", "프롬프트")

    assert make("finish_by").checkable and make("calendar").checkable
    assert not make("text_only").checkable and not make("duration_per_unit").checkable
