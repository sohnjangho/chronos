"""Condition 저장 모양(R5)과 자동 점검 여부."""

import json

import pytest

from app.harness.conditions import (
    BASE_RULES,
    Condition,
    ConditionFormatError,
    read_conditions,
    validate_params,
)

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
        "checkable": True,  # fix round 1 (M10): 읽기 전용, from_dict 는 무시한다
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


# ── fix round 1: params 검사와 형식 오류 (F1) ───────────────────────

GOOD_PARAMS = [
    ("finish_by", {"date": "2027-03-04"}),
    ("start_after", {"date": "2027-03-04"}),
    ("milestone_by", {"activity_id": "A", "date": "2027-03-04"}),
    ("resource_cap", {"resource_id": "crane", "capacity": 0}),
    ("calendar", {"days_per_week": 6, "holidays": "KR"}),
    ("calendar", {"days_per_week": 5, "holidays": ["2027-03-02"]}),
    ("blocked_period", {"start_md": [12, 1], "end_md": [2, 29], "tag": "타설"}),
    ("min_gap", {"after_tag": "타설", "days": 7}),
    ("min_gap", {"after_tag": "타설", "days": 7, "unit": "calendar_days"}),
    ("max_duration", {"days": 0}),
    ("finish_by", {"date": "1900-01-01"}),
    ("finish_by", {"date": "2199-12-31"}),
    ("text_only", {}),
    ("duration_per_unit", {}),
]


@pytest.mark.parametrize(("kind", "params"), GOOD_PARAMS)
def test_good_params(kind, params):
    assert validate_params(kind, params) is None


BAD_PARAMS = [
    ("finish_by", {}, "'date' 칸이 없습니다."),
    ("finish_by", {"date": "2027-02-30"}, "'date' 칸 값이 올바르지 않습니다: 날짜(YYYY-MM-DD)"),
    ("finish_by", {"date": 20270304}, "'date' 칸 값이 올바르지 않습니다: 날짜(YYYY-MM-DD)"),
    ("milestone_by", {"activity_id": "", "date": "2027-03-04"}, "'activity_id' 칸 값이 올바르지 않습니다: 빈칸이 아닌 글자"),
    ("resource_cap", {"resource_id": "crane", "capacity": -1}, "'capacity' 칸 값이 올바르지 않습니다: 0 이상의 정수"),
    ("resource_cap", {"resource_id": "crane", "capacity": True}, "'capacity' 칸 값이 올바르지 않습니다: 0 이상의 정수"),
    ("resource_cap", {"resource_id": "crane", "capacity": 2.0}, "'capacity' 칸 값이 올바르지 않습니다: 0 이상의 정수"),
    ("calendar", {"days_per_week": 4, "holidays": []}, "'days_per_week' 칸 값이 올바르지 않습니다: 5·6·7 가운데 하나"),
    ("calendar", {"days_per_week": 5, "holidays": ["03-02"]},
     "'holidays' 칸 값이 올바르지 않습니다: \"KR\" 또는 날짜(YYYY-MM-DD) 목록"),
    ("calendar", {"days_per_week": 5}, "'holidays' 칸이 없습니다."),
    ("blocked_period", {"start_md": [2, 30], "end_md": [3, 1], "tag": "타설"}, "'start_md' 칸 값이 올바르지 않습니다: [월, 일]"),
    ("blocked_period", {"start_md": [13, 1], "end_md": [3, 1], "tag": "타설"}, "'start_md' 칸 값이 올바르지 않습니다: [월, 일]"),
    ("blocked_period", {"start_md": [12, 1], "end_md": [2], "tag": "타설"}, "'end_md' 칸 값이 올바르지 않습니다: [월, 일]"),
    ("blocked_period", {"start_md": [12, 1], "end_md": [2, 28]}, "'tag' 칸이 없습니다."),
    ("min_gap", {"after_tag": "타설", "days": "7"}, "'days' 칸 값이 올바르지 않습니다: 0 이상의 정수"),
    ("min_gap", {"after_tag": "타설", "days": 7, "unit": "weeks"},
     "'unit' 칸 값이 올바르지 않습니다: \"workdays\" 또는 \"calendar_days\""),
    ("max_duration", {}, "'days' 칸이 없습니다."),
    ("text_only", [], "'params' 칸 값이 올바르지 않습니다: 객체"),
    # fix round 2: 월·일이 너무 큰 정수, 날짜 범위, YYYY-MM-DD 가 아닌 ISO 꼴
    ("blocked_period", {"start_md": [2147483648, 1], "end_md": [3, 1], "tag": "타설"},
     "'start_md' 칸 값이 올바르지 않습니다: [월, 일]"),
    ("blocked_period", {"start_md": [1, 1], "end_md": [1, 2**31], "tag": "타설"},
     "'end_md' 칸 값이 올바르지 않습니다: [월, 일]"),
    ("start_after", {"date": "9999-12-31"}, "날짜는 1900년부터 2199년 사이여야 합니다."),
    ("finish_by", {"date": "0001-01-01"}, "날짜는 1900년부터 2199년 사이여야 합니다."),
    ("finish_by", {"date": "1899-12-31"}, "날짜는 1900년부터 2199년 사이여야 합니다."),
    ("milestone_by", {"activity_id": "A", "date": "2200-01-01"}, "날짜는 1900년부터 2199년 사이여야 합니다."),
    ("calendar", {"days_per_week": 5, "holidays": ["2027-03-02", "2300-01-01"]},
     "날짜는 1900년부터 2199년 사이여야 합니다."),
    ("finish_by", {"date": "20270304"}, "'date' 칸 값이 올바르지 않습니다: 날짜(YYYY-MM-DD)"),
    ("finish_by", {"date": "2027-W10-1"}, "'date' 칸 값이 올바르지 않습니다: 날짜(YYYY-MM-DD)"),
    ("finish_by", {"date": "２０２７-03-04"}, "'date' 칸 값이 올바르지 않습니다: 날짜(YYYY-MM-DD)"),
    ("calendar", {"days_per_week": 5, "holidays": ["20270302"]},
     "'holidays' 칸 값이 올바르지 않습니다: \"KR\" 또는 날짜(YYYY-MM-DD) 목록"),
    ("made_up", {}, "알 수 없는 조건 종류입니다: made_up"),
]


@pytest.mark.parametrize(("kind", "params", "message"), BAD_PARAMS)
def test_bad_params(kind, params, message):
    assert validate_params(kind, params) == message


def test_from_dict_raises_a_format_error_naming_the_condition():
    with pytest.raises(ConditionFormatError) as missing_id:
        Condition.from_dict({"layer": "input", "kind": "text_only", "params": {}, "text": "", "source": ""})
    assert (missing_id.value.condition_id, missing_id.value.message) == ("?", "'id' 칸이 없습니다.")
    assert isinstance(missing_id.value, ValueError)
    with pytest.raises(ConditionFormatError) as missing_kind:
        Condition.from_dict({"id": "c1"})
    assert (missing_kind.value.condition_id, missing_kind.value.message) == ("c1", "'kind' 칸이 없습니다.")
    with pytest.raises(ConditionFormatError) as bad_params:
        Condition.from_dict({**WINTER.to_dict(), "params": {"start_md": [12, 1], "end_md": [2, 28]}})
    assert (bad_params.value.condition_id, bad_params.value.message) == ("i1", "'tag' 칸이 없습니다.")
    with pytest.raises(ConditionFormatError) as base_layer:
        Condition.from_dict({**WINTER.to_dict(), "layer": "base"})
    assert base_layer.value.message == "기본 규칙은 바꿀 수 없습니다."


def test_from_dict_reads_stored_base_rules():
    assert [Condition.from_dict(b.to_dict()) for b in BASE_RULES] == list(BASE_RULES)


def test_read_conditions_splits_good_and_bad():
    stored = [{"id": "c1"}, WINTER.to_dict(), "oops", {"kind": "text_only"}]
    good, bad = read_conditions(stored)
    assert good == [WINTER]
    assert bad == [
        {"condition_id": "c1", "message": "'kind' 칸이 없습니다."},
        {"condition_id": "?", "message": "조건이 객체가 아닙니다."},
        {"condition_id": "?", "message": "'id' 칸이 없습니다."},
    ]


@pytest.mark.parametrize("kind", ["no_cycle", "no_dangling", "valid"])
def test_base_rule_kinds_cannot_be_reused_under_another_id(kind):
    # fix round 2: 기본 규칙 종류(구조 점검)는 기본 규칙 id 로만 쓸 수 있다.
    with pytest.raises(ConditionFormatError) as e:
        Condition.from_dict({"id": "x", "layer": "input", "kind": kind, "params": {}, "text": "", "source": ""})
    assert e.value.message == "기본 규칙 종류는 바꿀 수 없습니다."
