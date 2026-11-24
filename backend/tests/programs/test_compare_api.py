"""비교 API: 두 안(현재·Plan·버전·복사본)의 요약과 액티비티별 차이, 여러 안 요약 표."""

from dataclasses import replace
from datetime import date

import pytest

from app.core.model import Relation
from app.core.shorten import Move
from app.programs.scenarios.compare import change_of
from app.store import scenarios
from app.store.schedules import load
from app.store.versions import save_new_version
from app.store.view import plan_changed
from tests.approval_doubles import finish_by
from tests.schedules import make, store, task

A_MOVE = "작업 A 절반 지점에서 작업 B 시작 (FS → SS+3)"


@pytest.fixture
def sid_chain(session) -> int:
    """A 6 → B 4 → C 5, 준공 3/19, 입력 조건 finish_by 2027-03-16."""
    s = make([task("A", 6), task("B", 4), task("C", 5)], [Relation("A", "B"), Relation("B", "C")])
    return store(session, s, [finish_by("2027-03-16")])


def add_scenario(session, sid: int, name: str = "만회안 A · 병행 우선", **more) -> int:
    current, stored, n = load(session, sid)
    parallel = replace(current, relations=(Relation("A", "B", "SS", 3), Relation("B", "C")))
    move = Move("par:A>B", "parallel", ("A", "B"), A_MOVE, relation=Relation("A", "B", "SS", 3))
    row = scenarios.create(session, schedule_id=sid, base_version=n, name=name, source="shorten", schedule=parallel,
                           conditions=stored, moves=[move], created_by="김하늘", **more)
    session.commit()
    return row.id


@pytest.fixture
def scenario_A(session, sid_chain) -> int:
    return add_scenario(session, sid_chain)


def new_version(session, sid: int, schedule, note: str) -> int:
    """표 고치기처럼 계획 칸이 바뀌면 계획 변경(Plan 을 새로 찍음), 실적만이면 물려받는다."""
    before, stored, n = load(session, sid)
    return save_new_version(session, sid, schedule, stored, by_kind="user", by_name="김하늘", note=note, changes=[],
                            base_version=n, plan_change=plan_changed(before, schedule))


def compare(client, admin, sid: int, base: str, other: str):
    return client.get(f"/api/schedules/{sid}/compare?base={base}&other={other}", headers=admin)


def test_compare_rows(client, admin, sid_chain, scenario_A):
    r = compare(client, admin, sid_chain, "current", f"s:{scenario_A}").json()
    rows = {x["activity_id"]: x for x in r["rows"]}
    assert (rows["B"]["start_delta"], rows["B"]["finish_delta"], rows["B"]["change"]) == (-3, -3, "pulled")
    assert rows["A"]["change"] == "same" and r["changed_count"] == 2
    assert r["other"]["finish"] == "2027-03-16" and r["base"]["deadline_float"] == -3


def test_row_shape_and_order(client, admin, sid_chain, scenario_A):
    r = compare(client, admin, sid_chain, "current", f"s:{scenario_A}").json()
    assert [x["activity_id"] for x in r["rows"]] == ["A", "B", "C"]
    assert r["rows"][1] == {
        "activity_id": "B", "name": "작업 B", "wbs": "1",
        "base": {"start": "2027-03-09", "finish": "2027-03-12", "od": 4},
        "other": {"start": "2027-03-04", "finish": "2027-03-09", "od": 4},
        "start_delta": -3, "finish_delta": -3, "change": "pulled",
    }


def test_sides(client, admin, sid_chain, scenario_A):
    r = compare(client, admin, sid_chain, "current", f"s:{scenario_A}").json()
    assert r["base"] == {"ref": "current", "label": "현재 일정 (버전 1)", "version": 1, "finish": "2027-03-19",
                         "plan_delta": 0, "deadline": "2027-03-16", "deadline_float": -3, "critical_count": 3, "violations": 1,
                         "uncheckable": 0, "peak": None, "changes": [], "stale": False, "status": None,
                         "accel": None}
    assert r["other"] == {"ref": f"s:{scenario_A}", "label": "만회안 A · 병행 우선", "version": 1,
                          "finish": "2027-03-16", "plan_delta": -3, "deadline": "2027-03-16", "deadline_float": 0, "critical_count": 3,
                          "violations": 0, "uncheckable": 0, "peak": None, "changes": [A_MOVE], "stale": False,
                          "status": "open", "accel": None}  # 당김 효과 칸 없이 만든 복사본


def test_versions_added_and_removed(client, admin, session, sid_chain):
    current = load(session, sid_chain)[0]
    v2 = replace(current, activities=(*current.activities[:2], task("D", 2)),
                 relations=(Relation("A", "B"), Relation("B", "D")))
    new_version(session, sid_chain, v2, "C 를 D 로")
    r = compare(client, admin, sid_chain, "v:1", "v:2").json()
    assert (r["base"]["label"], r["base"]["changes"], r["other"]["label"], r["other"]["changes"]) == (
        "버전 1", ["처음 만듦"], "버전 2", ["C 를 D 로"])
    rows = {x["activity_id"]: x for x in r["rows"]}
    assert [x["activity_id"] for x in r["rows"]] == ["A", "B", "C", "D"]
    assert (rows["C"]["other"], rows["C"]["start_delta"], rows["C"]["change"]) == (None, None, "removed")
    assert (rows["D"]["base"], rows["D"]["finish_delta"], rows["D"]["change"]) == (None, None, "added")
    assert rows["D"]["other"] == {"start": "2027-03-15", "finish": "2027-03-16", "od": 2}
    assert r["changed_count"] == 2 and r["base"]["stale"] is False


def test_pushed_by_a_longer_duration(client, admin, session, sid_chain):
    current = load(session, sid_chain)[0]
    new_version(session, sid_chain, replace(current, activities=tuple(
        replace(a, od=6) if a.id == "B" else a for a in current.activities)), "B 6일")
    rows = {x["activity_id"]: x for x in compare(client, admin, sid_chain, "v:1", "current").json()["rows"]}
    assert [(rows[i]["start_delta"], rows[i]["finish_delta"], rows[i]["change"]) for i in "ABC"] == [
        (0, 0, "same"), (0, 2, "pushed"), (2, 2, "pushed")]


@pytest.mark.parametrize(("base", "other", "start_delta", "finish_delta", "change"), [
    ({"start": "x", "od": 4}, None, None, None, "removed"),
    (None, {"start": "x", "od": 4}, None, None, "added"),
    ({"od": 4}, {"od": 4}, 0, -1, "pulled"),
    ({"od": 4}, {"od": 4}, 0, 1, "pushed"),
    ({"od": 4}, {"od": 4}, -1, 0, "pulled"),
    ({"od": 4}, {"od": 5}, 0, 0, "duration"),
    ({"od": 4}, {"od": 4}, 0, 0, "same"),
])
def test_change_kinds(base, other, start_delta, finish_delta, change):
    assert change_of(base, other, start_delta, finish_delta) == change


def test_plan_side_is_the_version_that_snapped_the_plan(client, admin, session, sid_chain):
    """PM 결정 11-20 밤(16e): Plan 안 = Plan 을 찍은 버전의 내용 그대로. 실적(버전 2)은 Plan 을 물려받아 버전 1 이고,
    그 뒤 계획 변경(버전 3, C 4일)은 그때의 예측(A 실적 포함)을 찍는다."""
    current = load(session, sid_chain)[0]
    late = replace(current, activities=tuple(
        replace(a, actual_start=date(2027, 3, 1), actual_finish=date(2027, 3, 10)) if a.id == "A" else a
        for a in current.activities))
    new_version(session, sid_chain, late, "A 실적")
    r = compare(client, admin, sid_chain, "plan", "current").json()
    assert (r["base"]["label"], r["base"]["version"], r["base"]["finish"], r["base"]["plan_delta"]) == (
        "Plan (버전 1)", 1, "2027-03-19", 0)
    assert (r["other"]["label"], r["other"]["finish"], r["other"]["plan_delta"]) == (
        "현재 일정 (버전 2)", "2027-03-23", 2)
    a = next(x for x in r["rows"] if x["activity_id"] == "A")
    assert (a["finish_delta"], a["change"]) == (2, "pushed")
    new_version(session, sid_chain, replace(late, activities=tuple(
        replace(a, od=4) if a.id == "C" else a for a in late.activities)), "C 4일")
    r = compare(client, admin, sid_chain, "plan", "current").json()
    assert (r["base"]["label"], r["base"]["finish"], r["other"]["finish"], r["other"]["plan_delta"]) == (
        "Plan (버전 3)", "2027-03-22", "2027-03-22", 0)
    assert r["changed_count"] == 0


def test_stale_scenario(client, admin, session, sid_chain, scenario_A):
    current = load(session, sid_chain)[0]
    new_version(session, sid_chain, replace(current, activities=tuple(
        replace(a, od=6) if a.id == "B" else a for a in current.activities)), "B 6일")
    r = compare(client, admin, sid_chain, "current", f"s:{scenario_A}").json()
    assert (r["other"]["stale"], r["other"]["version"], r["base"]["version"]) == (True, 1, 2)
    assert r["other"]["plan_delta"] == -5  # 지금 Plan(3/23) 대비


def test_compare_summary(client, admin, sid_chain, scenario_A):
    sides = client.get(f"/api/schedules/{sid_chain}/compare/summary", headers=admin).json()["sides"]
    assert [s["ref"] for s in sides] == ["current", "plan", f"s:{scenario_A}"]
    assert sides[1]["label"] == "Plan (버전 1)" and sides[2]["finish"] == "2027-03-16"


def test_summary_lists_open_and_submitted_newest_first(client, admin, session, sid_chain, scenario_A):
    second, gone, sent = (add_scenario(session, sid_chain, name=n) for n in ("둘째", "버림", "냄"))
    client.delete(f"/api/schedules/{sid_chain}/scenarios/{gone}", headers=admin)
    assert client.post(f"/api/schedules/{sid_chain}/scenarios/{sent}/submit", json={}, headers=admin).status_code == 200
    sides = client.get(f"/api/schedules/{sid_chain}/compare/summary", headers=admin).json()["sides"]
    assert [s["ref"] for s in sides] == ["current", "plan", f"s:{sent}", f"s:{second}", f"s:{scenario_A}"]
    assert sides[2]["status"] == "submitted"


@pytest.mark.parametrize("ref", ["s:999", "v:9", "v:0", "x", "s:abc", "current2", ""])
def test_unknown_ref_is_422(client, admin, sid_chain, ref):
    r = compare(client, admin, sid_chain, "current", ref)
    assert (r.status_code, r.json()["code"], r.json()["message"]) == (422, "invalid_ref",
                                                                      f"비교할 안을 찾을 수 없습니다: {ref}")


def test_unknown_ref_message(client, admin, sid_chain):
    assert compare(client, admin, sid_chain, "current", "s:999").json()["message"] == "비교할 안을 찾을 수 없습니다: s:999"


def test_scenario_of_another_schedule_is_unknown(client, admin, session, sid_chain, sid):
    other = add_scenario(session, sid_chain)
    r = compare(client, admin, sid, "current", f"s:{other}")
    assert (r.status_code, r.json()["code"]) == (422, "invalid_ref")


def test_base_defaults_to_current(client, admin, sid_chain, scenario_A):
    r = client.get(f"/api/schedules/{sid_chain}/compare?other=s:{scenario_A}", headers=admin).json()
    assert r["base"]["ref"] == "current"


def test_missing_schedule_and_login(client, admin):
    r = compare(client, admin, 999, "current", "plan")
    assert (r.status_code, r.json()["message"]) == (404, "일정을 찾을 수 없습니다.")
    assert client.get("/api/schedules/999/compare/summary", headers=admin).status_code == 404
    assert client.get("/api/schedules/1/compare?other=plan").status_code == 401


def test_uncomputable_current_is_422(client, admin, session, sid_chain):
    broken = load(session, sid_chain)[0]
    new_version(session, sid_chain, replace(broken, relations=(*broken.relations, Relation("C", "A"))), "고리")
    r = compare(client, admin, sid_chain, "current", "v:1")
    assert (r.status_code, r.json()["code"]) == (422, "schedule_invalid")
    assert r.json()["detail"] == {"activities": ["A", "B", "C"]}  # Fix 1 M5: 어느 액티비티인지
    assert client.get(f"/api/schedules/{sid_chain}/compare/summary", headers=admin).status_code == 422


def test_no_deadline_is_null(client, admin, session):
    sid = store(session, make([task("A", 3)]))
    side = client.get(f"/api/schedules/{sid}/compare/summary", headers=admin).json()["sides"][0]
    assert (side["deadline"], side["deadline_float"]) == (None, None)


def test_uncomputable_plan_only_fails_the_plan_ref(client, admin, session, sid_chain, monkeypatch):  # Fix 1 M2
    """Plan 이 계산되지 않으면 plan_delta 는 null, 요약 표에서 Plan 은 빠지고, plan ref 만 422."""
    from app.programs.scenarios import compare as compare_module

    def broken_plan(session, schedule_id, n):
        schedule, conditions, _ = load(session, schedule_id, n)
        return replace(schedule, relations=(*schedule.relations, Relation("C", "A"))), conditions, n

    monkeypatch.setattr(compare_module, "plan_source", broken_plan)
    r = compare(client, admin, sid_chain, "v:1", "current")
    assert r.status_code == 200 and (r.json()["base"]["plan_delta"], r.json()["other"]["plan_delta"]) == (None, None)
    sides = client.get(f"/api/schedules/{sid_chain}/compare/summary", headers=admin).json()["sides"]
    assert [s["ref"] for s in sides] == ["current"]
    bad = compare(client, admin, sid_chain, "current", "plan")
    assert (bad.status_code, bad.json()["code"]) == (422, "schedule_invalid")
