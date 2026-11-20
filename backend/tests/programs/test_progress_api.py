"""진행 API: GET /api/schedules/{id}/progress, 그리고 프로그램 라우터 자동 등록."""

from dataclasses import replace
from datetime import date

import pytest
from fastapi import FastAPI

from app.agent import context
from app.core.calendar import WorkCalendar
from app.core.model import Activity, CalendarSpec, Relation, Schedule, WbsNode
from app.core.progress import Bar
from app.main import include_program_routers
from app.programs.progress import service
from app.store.schedules import load
from app.store.versions import save_new_version
from app.store.view import plan_changed
from tests import schedules


def get_progress(client, admin, sid, unit=None) -> dict:
    query = f"?unit={unit}" if unit else ""
    r = client.get(f"/api/schedules/{sid}/progress{query}", headers=admin)
    assert r.status_code == 200, r.json()
    return r.json()


def _save(session, sid, schedule, base) -> int:
    """표 고치기처럼 계획 칸이 바뀌면 계획 변경(Plan 을 새로 찍음), 실적만이면 물려받는다."""
    before = load(session, sid, base)[0]
    return save_new_version(session, sid, schedule, [], by_kind="user", by_name="김하늘", note="실적", changes=[],
                            base_version=base, plan_change=plan_changed(before, schedule))


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
    assert p["lookahead"]["blocked"] == [{"id": "B", "name": "작업 B", "date": "2027-03-09", "reason": "선행 미완료: A"}]
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


# --- fix round 1 ---------------------------------------------------------------------------------


@pytest.fixture
def sid_added(session, sid_progress) -> int:
    """sid_progress 버전 2 에 나중에 더한 C(15일, wbs 1, 실적 시작 3/1·진도 0.5·남은 14일 → 3/22)를 버전 3 으로.
    C 가 준공을 정해 크리티컬이고 A·B 는 여유가 생긴다. 액티비티를 더한 것은 계획 변경이라 Plan 은 그때의 예측
    (A·C 실적 포함, PM 결정 11-20 밤): A 3/1~3/8, B 3/9~3/15, C 3/1~3/22."""
    v2, _, n = load(session, sid_progress)
    c = Activity("C", "작업 C", "task", "1", 15, rd=14, progress=0.5, actual_start=date(2027, 3, 1))
    _save(session, sid_progress, replace(v2, activities=(*v2.activities, c)), n)
    return sid_progress


def test_activity_added_later_is_in_the_plan(client, admin, sid_added):
    """C 를 더한 버전이 Plan 을 새로 찍으므로 나중에 더한 C 도 Plan 이 있다(added_after_plan 0).
    가중치 A·B·C = 0.2·0.2·0.6. 3/3 아침 Plan: A 2/6·C 2/16 → 0.2×2/6 + 0.6×2/16 = 14.2%, 실적: A 0.2·C 0.5 → 34%."""
    p = get_progress(client, admin, sid_added)
    assert (p["plan_now"], p["actual_now"]) == (14.2, 34.0)
    assert p["added_after_plan"] == {"count": 0, "actual_pct": 0.0}
    assert p["curve"][-1]["plan_cum"] == 100.0
    assert p["counts"]["total"] == 3


def test_critical_variance_counts_a_task_added_later(client, admin, session, sid_added):
    """크리티컬은 C 뿐. 더한 때 Plan 은 3/1~3/22(16일)로 차이 0, 그 뒤 실적(남은 기간 15일, 계획 변경 아님)으로
    지금 3/1~3/23(17일) − Plan 16일 = 1."""
    assert get_progress(client, admin, sid_added)["cpm"]["critical_variance"] == {"days": 0, "max_id": "C"}
    v3, _, n = load(session, sid_added)
    _save(session, sid_added, replace(v3, activities=tuple(replace(a, rd=15) if a.id == "C" else a for a in v3.activities)), n)
    assert get_progress(client, admin, sid_added)["cpm"]["critical_variance"] == {"days": 1, "max_id": "C"}


def _bar(i, kind, wbs, weight, plan, now, **actuals) -> Bar:
    return Bar(id=i, kind=kind, wbs=wbs, weight=weight, plan_start=plan[0] if plan else None,
               plan_finish=plan[1] if plan else None, start=now[0], finish=now[1],
               actual_start=actuals.get("actual_start"), actual_finish=None, progress=actuals.get("progress", 0.0), tags=())


def _bars_with_one_unplanned() -> list[Bar]:
    """A·B·M 은 Plan 이 있고 C(실적 시작 3/1·진도 0.5) 는 Plan 이 없다(Plan 이 계산되지 않은 경우의 막대 모양)."""
    d = lambda day: date(2027, 3, day)
    return [
        _bar("A", "task", "1", 0.2, (d(1), d(5)), (d(1), d(8)), actual_start=d(1), progress=0.2),
        _bar("B", "task", "2", 0.2, (d(8), d(12)), (d(9), d(15))),
        _bar("M", "finish_ms", "2", 0.0, (d(12), d(12)), (d(22), d(22))),
        _bar("C", "task", "1", 0.6, None, (d(1), d(22)), actual_start=d(1), progress=0.5),
    ]


def test_bars_without_a_plan_are_reported_apart():
    """R4(뜻 유지): Plan 선·실적 선·SPI 는 Plan 이 있는 A·B 만(가중치 0.2·0.2 → 0.5·0.5 로 다시 나눔). C 는 따로.
    PM 결정 11-20 뒤로는 Plan 이 계산되지 않을 때만 생기는 모양이라 _rates 로 바로 잰다."""
    wbs = [{"code": "1", "name": "기초", "parent": None}, {"code": "2", "name": "골조", "parent": None}]
    p = service._rates(_bars_with_one_unplanned(), wbs, WorkCalendar(CalendarSpec(5)), date(2027, 3, 3), "week")
    assert (p["plan_now"], p["actual_now"], p["spi"]) == (20.0, 10.0, 0.5)
    assert p["added_after_plan"] == {"count": 1, "actual_pct": 50.0}
    assert p["curve"][-1]["plan_cum"] == 100.0
    assert p["wbs"][0] == {"code": "1", "name": "기초", "weight": 0.5, "plan": 40.0, "actual": 20.0, "diff": -20.0}


def test_critical_variance_is_null_without_a_planned_critical_task():
    """크리티컬이 Plan 없는 C 뿐이면 null(뜻 유지 — _critical_variance 로 바로 잰다)."""
    tasks = [b for b in _bars_with_one_unplanned() if b.kind == "task"]
    acts = {"A": {"critical": False}, "B": {"critical": False}, "C": {"critical": True}}
    assert service._critical_variance(tasks, acts, WorkCalendar(CalendarSpec(5))) is None


def test_lookahead_blocks_by_relation_type(client, admin, session, sid_progress):
    """I1: D(SS ← 시작한 A)·E(FF ← A)·G(SF ← B)는 막히지 않고, F(SS ← 시작 전 B)는 막힌다."""
    v2, _, n = load(session, sid_progress)
    extra = tuple(Activity(i, f"작업 {i}", "task", "2", 2) for i in ("D", "E", "F", "G"))
    rels = (Relation("A", "D", "SS"), Relation("A", "E", "FF"), Relation("B", "F", "SS"), Relation("B", "G", "SF"))
    _save(session, sid_progress, replace(v2, activities=(*v2.activities, *extra), relations=(*v2.relations, *rels)), n)
    la = get_progress(client, admin, sid_progress)["lookahead"]
    assert [(s["id"], s["date"]) for s in la["starts"]] == [
        ("D", "2027-03-03"), ("E", "2027-03-05"), ("G", "2027-03-08"), ("B", "2027-03-09"), ("F", "2027-03-09")
    ]
    assert la["blocked"] == [
        {"id": "B", "name": "작업 B", "date": "2027-03-09", "reason": "선행 미완료: A"},
        {"id": "F", "name": "작업 F", "date": "2027-03-09", "reason": "선행 미착수: B"},
    ]


def test_nested_wbs_rolls_up_to_the_top_group(client, admin, session):
    base = _plan()
    plan = replace(
        base,
        wbs=(WbsNode("1", "기초", None), WbsNode("1.1", "터파기", "1"), WbsNode("2", "골조", None)),
        activities=(replace(base.activities[0], wbs="1.1"), *base.activities[1:]),
    )
    sid = schedules.store(session, plan)
    _save(session, sid, _with(plan, date(2027, 3, 3), actual_start=date(2027, 3, 1), progress=0.2, rd=4), 1)
    assert get_progress(client, admin, sid)["wbs"] == [
        {"code": "1", "name": "기초", "weight": 0.5, "plan": 40.0, "actual": 20.0, "diff": -20.0},
        {"code": "2", "name": "골조", "weight": 0.5, "plan": 0.0, "actual": 0.0, "diff": 0.0},
    ]


def test_milestones_done_and_ahead(client, admin, session):
    """Plan: A(5) → M1, B(5) → M2 (모두 3/5). 지금: A 실적 3/1~3/3 끝·M1 실적 3/3, B 실적 3/1~3/3 끝 → M2 3/3."""
    m1 = Activity("M1", "기초 완료", "finish_ms", "1", 0)
    m2 = Activity("M2", "골조 완료", "finish_ms", "1", 0)
    s = schedules.make([schedules.task("A", 5), m1, schedules.task("B", 5), m2], [Relation("A", "M1"), Relation("B", "M2")])
    sid = schedules.store(session, s)
    a, _, b, _ = s.activities
    done = replace(a, actual_start=date(2027, 3, 1), actual_finish=date(2027, 3, 3), progress=1.0)
    b_done = replace(b, actual_start=date(2027, 3, 1), actual_finish=date(2027, 3, 3), progress=1.0)
    _save(session, sid, replace(s, activities=(done, replace(m1, actual_finish=date(2027, 3, 3)), b_done, m2)), 1)
    assert get_progress(client, admin, sid)["milestones"] == [
        {"id": "M1", "name": "기초 완료", "plan": "2027-03-05", "actual_or_forecast": "2027-03-03", "delta": -2, "status": "완료"},
        {"id": "M2", "name": "골조 완료", "plan": "2027-03-05", "actual_or_forecast": "2027-03-03", "delta": -2, "status": "앞섬"},
    ]


def test_top_delays_keep_five_by_delay_then_schedule_order(client, admin, session):
    longer = {"X1": 1, "X2": 3, "X3": 2, "X4": 3, "X5": 1, "X6": 2, "X7": 1}  # 서로 관계없는 2일 작업, 실적으로 이만큼 김
    s = schedules.make([schedules.task(i, 2) for i in longer])
    sid = schedules.store(session, s)
    started = tuple(replace(a, actual_start=date(2027, 3, 1), rd=2 + longer[a.id]) for a in s.activities)
    _save(session, sid, replace(s, activities=started), 1)
    top = get_progress(client, admin, sid)["top_delays"]
    assert [(t["id"], t["delay"], t["finish_impact"]) for t in top] == [
        ("X2", 3, 3), ("X4", 3, 3), ("X3", 2, 0), ("X6", 2, 0), ("X1", 1, 0)
    ]


def test_plan_compliance_percent_rounds_half_up(client, admin, session):
    """m8: 8개 가운데 1개 → 12.5 → 13 (짝수 반올림이면 12)."""
    s = schedules.make([schedules.task(f"T{i}", 1) for i in range(1, 9)])  # 모두 Plan 3/1 하루
    sid = schedules.store(session, s)
    first = replace(s.activities[0], actual_start=date(2027, 3, 1), actual_finish=date(2027, 3, 1), progress=1.0)
    _save(session, sid, replace(s, data_date=date(2027, 3, 15), activities=(first, *s.activities[1:])), 1)
    assert get_progress(client, admin, sid)["cpm"]["plan_compliance"] == {"pct": 13, "done": 1, "due": 8}
