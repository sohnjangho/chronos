"""진행 API: GET /api/schedules/{id}/progress, 그리고 프로그램 라우터 자동 등록."""

from dataclasses import replace
from datetime import date

import pytest
from fastapi import FastAPI

from app.agent import context
from app.core.model import Activity, CalendarSpec, Relation, Schedule, WbsNode
from app.main import include_program_routers
from app.programs.progress import service
from app.store.schedules import load
from app.store.versions import save_new_version
from tests import schedules


def get_progress(client, admin, sid, unit=None) -> dict:
    query = f"?unit={unit}" if unit else ""
    r = client.get(f"/api/schedules/{sid}/progress{query}", headers=admin)
    assert r.status_code == 200, r.json()
    return r.json()


def _save(session, sid, schedule, base) -> int:
    return save_new_version(
        session, sid, schedule, [], by_kind="user", by_name="김하늘", note="실적", changes=[], base_version=base
    )


def _plan() -> Schedule:
    """WBS 1 기초·2 골조. A(5, wbs 1) → B(5, wbs 2) → M(준공, wbs 2). Plan: A 3/1~3/5, B 3/8~3/12, M 3/12."""
    return Schedule(
        start=date(2027, 3, 1),
        calendar=CalendarSpec(days_per_week=5),
        wbs=(WbsNode("1", "기초", None), WbsNode("2", "골조", None)),
        activities=(
            Activity("A", "작업 A", "task", "1", 5),
            Activity("B", "작업 B", "task", "2", 5),
            Activity("M", "준공", "finish_ms", "2", 0),
        ),
        relations=(Relation("A", "B"), Relation("B", "M")),
    )


def _with(schedule: Schedule, data_date: date, **a_fields) -> Schedule:
    a = replace(schedule.activities[0], **a_fields)
    return replace(schedule, data_date=data_date, activities=(a, *schedule.activities[1:]))


@pytest.fixture
def sid_progress(session) -> int:
    """버전 1 = Plan. 버전 2: Data Date 3/3, A 실적 시작 3/1·진도 0.2·남은 4일 → A 3/1~3/8, B 3/9~3/15, M 3/15."""
    plan = _plan()
    sid = schedules.store(session, plan)
    _save(session, sid, _with(plan, date(2027, 3, 3), actual_start=date(2027, 3, 1), progress=0.2, rd=4), 1)
    return sid


def test_now_values(client, admin, sid_progress):
    p = get_progress(client, admin, sid_progress)
    assert (p["plan_now"], p["actual_now"], p["gap"], p["spi"]) == (20.0, 10.0, -10.0, 0.5)
    assert p["finish"] == {"current": "2027-03-15", "plan": "2027-03-12", "deadline": None, "delta": 1, "deadline_float": None}
    assert p["counts"] == {"total": 2, "done": 0, "in_progress": 1, "late": 2}
    assert (p["schedule_id"], p["version"], p["data_date"], p["data_date_assumed"]) == (sid_progress, 2, "2027-03-03", False)
    assert (p["unit"], p["weight_mode"]) == ("week", "duration")


def test_weekly_curve(client, admin, sid_progress):
    c = get_progress(client, admin, sid_progress)["curve"]
    assert [x["date"] for x in c] == ["2027-03-01", "2027-03-03", "2027-03-08", "2027-03-15", "2027-03-16"]
    assert [x["plan_cum"] for x in c] == [0.0, 20.0, 50.0, 100.0, 100.0]
    assert [x["actual_cum"] for x in c] == [0.0, 10.0, None, None, None]
    assert [x["forecast_cum"] for x in c] == [None, 10.0, 40.0, 90.0, 100.0]
    assert [x["plan_period"] for x in c] == [0.0, 20.0, 30.0, 50.0, 0.0]


def test_tables(client, admin, sid_progress):
    p = get_progress(client, admin, sid_progress)
    assert p["wbs"] == [{"code": "1", "name": "기초", "weight": 0.5, "plan": 40.0, "actual": 20.0, "diff": -20.0},
                        {"code": "2", "name": "골조", "weight": 0.5, "plan": 0.0, "actual": 0.0, "diff": 0.0}]
    assert p["milestones"] == [{"id": "M", "name": "준공", "plan": "2027-03-12", "actual_or_forecast": "2027-03-15", "delta": 1, "status": "지연"}]
    assert [d["id"] for d in p["top_delays"]] == ["A", "B"] and p["top_delays"][0]["finish_impact"] == 1
    assert p["lookahead"]["blocked"] == [{"id": "B", "name": "작업 B", "date": "2027-03-09", "reason": "선행 미완: A"}]
    assert p["spi_trend"] == [{"date": "2027-03-03", "spi": 0.5}]


def test_lookahead_window(client, admin, sid_progress):
    la = get_progress(client, admin, sid_progress)["lookahead"]
    assert (la["from"], la["to"]) == ("2027-03-03", "2027-03-23")
    assert la["starts"] == [{"id": "B", "name": "작업 B", "date": "2027-03-09"}]  # 이미 시작한 A·마일스톤 M 은 없음
    assert la["finishes"] == [{"id": "A", "name": "작업 A", "date": "2027-03-08"}, {"id": "B", "name": "작업 B", "date": "2027-03-15"}]


def test_cpm_block(client, admin, sid_progress):
    assert get_progress(client, admin, sid_progress)["cpm"] == {
        "plan_compliance": None,
        "critical_variance": {"days": 1, "max_id": "A"},
        "finish_variance": {"days": 1, "plan": "2027-03-12", "current": "2027-03-15"},
    }


def test_plan_compliance(client, admin, session, sid_progress):
    """버전 3: A 실적 3/1~3/5 끝남, Data Date 3/15."""
    v2, _, n = load(session, sid_progress)
    _save(session, sid_progress, _with(v2, date(2027, 3, 15), actual_finish=date(2027, 3, 5), progress=1.0, rd=None), n)
    assert get_progress(client, admin, sid_progress)["cpm"]["plan_compliance"] == {"pct": 50, "done": 1, "due": 2}


def test_deadline_is_the_earliest_enabled_finish_by(client, admin, session):
    def finish_by(cid, day, enabled=True):
        return {"id": cid, "layer": "input", "kind": "finish_by", "params": {"date": day}, "text": "준공 기한",
                "source": "프롬프트", "enabled": enabled}

    sid = schedules.store(session, _plan(), [finish_by("i1", "2027-03-10", enabled=False), finish_by("i2", "2027-03-19")])
    assert get_progress(client, admin, sid)["finish"] == {
        "current": "2027-03-12", "plan": "2027-03-12", "deadline": "2027-03-19", "delta": 0, "deadline_float": 5
    }


def _manual_mode_without_weights(monkeypatch) -> None:
    """Task 21 의 manual 모드에서 가중치를 하나도 넣지 않은 일정이 view_data 에 주는 모양(weight 모두 0).

    Task 21(weight_mode 칸) 이 들어오기 전이라 view_data 를 감싸 그 모양을 만든다.
    """
    real = service.view_data

    def manual(session, schedule_id, computed=None):
        v = real(session, schedule_id, computed)
        acts = [{**a, "weight": 0.0, "manual_weight": None} for a in v["activities"]]
        return {**v, "weight_mode": "manual", "activities": acts}

    monkeypatch.setattr(service, "view_data", manual)


def _edge_sid(session, case) -> int:
    if case == "only_milestones":
        base = schedules.make(
            [Activity("S", "착공", "start_ms", "1", 0), Activity("F", "준공", "finish_ms", "1", 0)], [Relation("S", "F")]
        )
    else:
        base = schedules.sample()  # A 3일 → B 2일, Plan 3/1~3/5
    day = {"before_start": date(2027, 2, 22), "after_finish": date(2027, 4, 1)}.get(case, date(2027, 3, 3))
    sid = schedules.store(session, base)
    _save(session, sid, replace(base, data_date=day), 1)
    return sid


@pytest.mark.parametrize("case", ["before_start", "after_finish", "only_milestones", "manual_without_weights"])
def test_progress_edges(client, admin, session, monkeypatch, case):
    sid = _edge_sid(session, case)
    if case == "manual_without_weights":
        _manual_mode_without_weights(monkeypatch)
    p = get_progress(client, admin, sid)  # 예외 없음
    expected = {"before_start": (0.0, 0.0, None), "after_finish": (100.0, 0.0, 0.0),
                "only_milestones": (0.0, 0.0, None), "manual_without_weights": (0.0, 0.0, None)}[case]
    assert (p["plan_now"], p["actual_now"], p["spi"]) == expected
    assert p["weight_mode"] == ("manual" if case == "manual_without_weights" else "duration")


def test_missing_data_date_uses_today(client, admin, sid, monkeypatch):
    monkeypatch.setattr(context, "today", lambda: date(2027, 3, 3))
    p = get_progress(client, admin, sid)
    assert (p["data_date"], p["data_date_assumed"]) == ("2027-03-03", True)


def test_month_unit_and_bad_unit(client, admin, sid_progress):
    assert get_progress(client, admin, sid_progress, unit="month")["curve"][0]["date"] == "2027-03-01"
    r = client.get(f"/api/schedules/{sid_progress}/progress?unit=day", headers=admin)
    assert (r.status_code, r.json()["code"]) == (422, "invalid_request")


def test_unknown_schedule_is_404(client, admin):
    r = client.get("/api/schedules/999/progress", headers=admin)
    assert (r.status_code, r.json()["code"], r.json()["message"]) == (404, "not_found", "일정을 찾을 수 없습니다.")


def test_uncomputable_schedule_is_422(client, admin, session, sid):
    broken = replace(schedules.sample(), relations=(Relation("A", "B"), Relation("B", "A")))
    _save(session, sid, broken, 1)  # 저장은 계산을 확인하지 않는다
    r = client.get(f"/api/schedules/{sid}/progress", headers=admin)
    assert (r.status_code, r.json()["code"], r.json()["message"]) == (422, "schedule_invalid", "선후 관계가 고리를 이룹니다.")


def test_login_required(client, sid):
    assert client.get(f"/api/schedules/{sid}/progress").status_code == 401


def test_program_routers_are_discovered(client, admin):
    assert {"approvals", "progress", "schedule"} <= set(include_program_routers(FastAPI()))
    assert client.get("/api/settings/approval", headers=admin).status_code == 200
