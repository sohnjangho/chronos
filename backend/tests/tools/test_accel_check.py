"""도구 points.accel_check — 「〔작업〕을 n일 당기면?」 당긴 일수 가운데 준공 반영·다음 결정 줄(읽기, 카드 accel_check).

만회안 묶음(shorten.make)·비교판 요약 표의 같은 칸(준공 반영 m/n일·다음 결정 줄)과 설정값 accel_warn_ratio 도 본다.
"""

from dataclasses import replace
from datetime import date

import pytest

from app.agent import context
from app.core.accel import MIXED_REASON
from app.core.model import Relation
from app.programs.scenarios import compare
from app.store import scenarios
from app.store.schedules import load
from app.store.settings import accel_warn_ratio
from app.store.tables import Setting
from app.tools.registry import call, list_tools
from tests.approval_doubles import finish_by
from tests.schedules import make, store, task


def named(i: str, od: int, **k):
    return task(i, od, name=f"{i} 작업", **k)


def side():
    """A 6 → B 4 → D 2 와 나란한 X 9 → D(주 5일, 3/1 시작). X 의 여유 1."""
    return make([named("A", 6), named("B", 4), named("X", 9), named("D", 2)],
                [Relation("A", "B"), Relation("B", "D"), Relation("X", "D")])


def chain():
    """A 6 → B 4 → C 5. 준공 3/19."""
    return make([named("A", 6), named("B", 4), named("C", 5)], [Relation("A", "B"), Relation("B", "C")])


def put(session, key: str, value: str) -> None:
    session.add(Setting(key=key, value=value))
    session.commit()


async def check(ctx, session, schedule, **args):
    sctx = replace(ctx, schedule_id=store(session, schedule))
    return await call("points.accel_check", args, sctx)


def test_system_prompt_asks_to_check_pull_effect_first():
    prompt = context.system_prompt()
    assert "작업을 당기거나 자원을 더하자는 요청에는 먼저 당김 효과를 확인해 보여 준다" in prompt
    assert "points__accel_check" in prompt and "scenario__create" in prompt


def test_spec_is_read_only():
    spec = {t.name: t for t in list_tools()}["points.accel_check"]
    assert spec.mutates is False


async def test_blocked_pull_warns_and_names_next_chain(ctx, session, events):
    r = await check(ctx, session, side(), activity_id="B", days=3)
    assert r.ok, r.error
    o = r.output
    assert (o["kind"], o["activity_id"], o["name"], o["od_before"], o["od_after"]) == ("accel_check", "B", "B 작업", 4, 1)
    assert (o["pulled_days"], o["reached_days"], o["warn"]) == (3, 1, True)
    assert (o["finish_before"], o["finish_after"]) == ("2027-03-16", "2027-03-15")
    assert o["warn_line"] == "당긴 3일 중 1일만 준공에 반영됩니다"
    assert o["summary_line"] == "B 작업 3일 당김 → 준공 1일 당겨짐"
    assert o["next_chain"] == [{"activity_id": "X", "name": "X 작업", "point": True},
                               {"activity_id": "D", "name": "D 작업", "point": True}]
    assert o["same_chain"] is False
    assert [e.type for e in events] == ["card"] and events[0].data == o


async def test_full_reach_has_no_warn_line(ctx, session):
    r = await check(ctx, session, chain(), activity_id="C", days=2)
    o = r.output
    assert (o["pulled_days"], o["reached_days"], o["warn"], o["warn_line"], o["same_chain"]) == (2, 2, False, None, True)
    assert [c["activity_id"] for c in o["next_chain"]] == ["A", "B"]


async def test_point_marks_follow_window_setting(ctx, session):
    put(session, "points_window_weeks", "1")  # 3/1~3/8: X 는 포인트, D(3/12 시작)는 아니다
    r = await check(ctx, session, side(), activity_id="B", days=3)
    assert [(c["activity_id"], c["point"]) for c in r.output["next_chain"]] == [("X", True), ("D", False)]


async def test_warn_ratio_setting(ctx, session):
    r = await check(ctx, session, side(), activity_id="B", days=2)  # 2일 → 1일, 0.5 == 기본값 → 경고 없음
    assert (r.output["reached_days"], r.output["warn"]) == (1, False)
    put(session, "accel_warn_ratio", "0.6")
    r = await check(ctx, session, side(), activity_id="B", days=2)
    assert r.output["warn"] is True and r.output["warn_line"] == "당긴 2일 중 1일만 준공에 반영됩니다"


@pytest.mark.parametrize("value, expected", [("0.3", 0.3), ("1.0", 1.0), ("0.05", 0.5), ("1.5", 0.5), ("많이", 0.5)])
def test_accel_warn_ratio_bounds(session, value, expected):
    assert accel_warn_ratio(session) == 0.5
    put(session, "accel_warn_ratio", value)
    assert accel_warn_ratio(session) == expected


async def test_started_work_is_refused(ctx, session, events):
    s = make([named("A", 6, actual_start=date(2027, 3, 1)), named("B", 4)], [Relation("A", "B")])
    r = await check(ctx, session, s, activity_id="A", days=2)
    assert not r.ok and "실적" in r.error and events == []


async def test_unknown_work_is_refused(ctx, session):
    r = await check(ctx, session, chain(), activity_id="Z", days=1)
    assert not r.ok and "Z" in r.error


async def test_needs_a_schedule(ctx):
    r = await call("points.accel_check", {"activity_id": "A", "days": 1}, ctx)
    assert not r.ok


# ── 만회안 묶음·비교판 요약 ────────────────────────────────────────────


async def test_recovery_options_and_compare_summary_carry_accel(ctx, session):
    sid = store(session, chain(), [finish_by("2027-03-16")])  # 목표 3일
    r = await call("shorten.make", {}, replace(ctx, schedule_id=sid))
    assert r.ok, r.error
    a, b = r.output["options"]
    assert (a["key"], a["gain"], a["pulled_days"], a["accel_warn"]) == ("A", 3, 3, False)  # A 6 − SS 3
    assert [c["activity_id"] for c in a["next_chain"]] == ["C"]  # 병행한 A·B 를 뺀 크리티컬
    assert (b["key"], b["gain"], b["pulled_days"]) == ("B", 3, 3)  # 압축 A 6→4(2일), C 5→4(1일)
    assert [c["activity_id"] for c in b["next_chain"]] == ["B"]
    sides = {s["ref"]: s for s in compare.summary(session, sid)["sides"]}
    assert sides["current"]["accel"] is None
    got = sides[f"s:{a['scenario_id']}"]["accel"]
    assert got == {"pulled_days": 3, "finish_gain": 3, "warn": False, "next_chain": a["next_chain"]}


def _agent_copy(session, sid: int, schedule) -> int:
    _, conditions, n = load(session, sid)
    row = scenarios.create(session, schedule_id=sid, base_version=n, name="만약에", source="agent", schedule=schedule,
                           conditions=conditions, created_by="관리자")
    session.commit()
    return row.id


def test_compare_summary_derives_accel_for_what_if_copies(session):
    sid = store(session, side())
    base = load(session, sid)[0]
    pulled = replace(base, activities=tuple(replace(a, od=1) if a.id == "B" else a for a in base.activities))
    mixed = replace(pulled, activities=tuple(replace(a, od=7) if a.id == "A" else a for a in pulled.activities))
    good, bad = _agent_copy(session, sid, pulled), _agent_copy(session, sid, mixed)
    sides = {s["ref"]: s for s in compare.summary(session, sid)["sides"]}
    got = sides[f"s:{good}"]
    assert got["accel"] == {"pulled_days": 3, "finish_gain": 1, "warn": True,
                            "next_chain": [{"activity_id": "X", "name": "X 작업", "point": True},
                                           {"activity_id": "D", "name": "D 작업", "point": True}]}
    assert got["accel_reason"] is None
    assert (sides[f"s:{bad}"]["accel"], sides[f"s:{bad}"]["accel_reason"]) == (None, MIXED_REASON)


async def test_scenario_create_returns_accel(ctx, session, events):
    sid = store(session, side())
    args = {"name": "B 1일", "base_version": 1, "changes": [{"op": "update_activity", "id": "B", "od": 1}]}
    r = await call("scenario.create", args, replace(ctx, schedule_id=sid))
    assert r.ok, r.error
    assert (r.output["accel"]["pulled_days"], r.output["accel"]["finish_gain"], r.output["accel_reason"]) == (3, 1, None)
    assert events[0].data["accel"] == r.output["accel"]
