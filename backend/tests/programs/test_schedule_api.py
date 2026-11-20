"""일정 API: 계산 포함 응답, 고치기, 버전·변경 이력."""

from datetime import datetime

import pytest

from app.core.model import BlockedPeriod, CalendarSpec, Relation, Resource
from app.programs.schedule import edits, service
from app.store.schedules import to_json
from app.store.tables import ChangeLog, ScheduleVersion
from app.store.versions import mark_plan, save_new_version
from tests.schedules import make, store, task

# ── 작업 지시서의 시험 ──────────────────────────────────────────────


def test_patch_duration_recomputes(client, admin, sid):
    r = client.patch(f"/api/schedules/{sid}/activities/A", json={"od": 5, "base_version": 1}, headers=admin)
    assert r.status_code == 200 and r.json()["version"] == 2 and r.json()["finish"] > "2027-03-05"
def test_cycle_edit_is_rejected_and_not_saved(client, admin, sid):
    r = client.put(f"/api/schedules/{sid}/activities/A/predecessors", json={"items": [{"pred": "B", "type": "FS", "lag": 0}], "base_version": 1}, headers=admin)
    assert r.status_code == 422 and r.json()["code"] == "schedule_invalid"
    assert client.get(f"/api/schedules/{sid}", headers=admin).json()["version"] == 1
def test_status_late_from_actual(client, admin, sid):
    client.patch(f"/api/schedules/{sid}/activities/A", json={"actual_start": "2027-03-01", "actual_finish": "2027-03-05", "progress": 1, "base_version": 1}, headers=admin)
    a = next(x for x in client.get(f"/api/schedules/{sid}", headers=admin).json()["activities"] if x["id"] == "A")
    assert a["status"] == "done" and a["plan_finish"] == "2027-03-03"


# ── 도우미 ──────────────────────────────────────────────────────────


def _get(client, headers, sid):
    r = client.get(f"/api/schedules/{sid}", headers=headers)
    assert r.status_code == 200, r.json()
    return r.json()


def _act(view, aid):
    return next(x for x in view["activities"] if x["id"] == aid)


def _patch(client, headers, sid, aid, base, **body):
    return client.patch(
        f"/api/schedules/{sid}/activities/{aid}", json={**body, "base_version": base}, headers=headers
    )


def _versions(client, headers, sid):
    return client.get(f"/api/schedules/{sid}/versions", headers=headers).json()


# ── 읽기 ────────────────────────────────────────────────────────────


def test_view_has_computed_values(client, admin, sid):
    v = _get(client, admin, sid)
    assert {k: v[k] for k in ("id", "name", "domain", "level", "version", "data_date", "finish", "plan_finish")} == {
        "id": sid, "name": "시험 일정", "domain": "construction", "level": "L3", "version": 1,
        "data_date": None, "finish": "2027-03-05", "plan_finish": "2027-03-05",
    }
    assert v["wbs"] == [{"code": "1", "name": "골조", "parent": None}]
    assert v["relations"] == [{"pred": "A", "succ": "B", "type": "FS", "lag": 0}]
    assert v["resources"] == [{"id": "crane", "name": "타워크레인", "unit": "대", "capacity": 1}]
    assert v["summary"] == {"critical_count": 2, "negative_float_count": 0, "warning_count": 0}
    assert _act(v, "A") == {
        "id": "A", "name": "작업 A", "kind": "task", "wbs": "1", "od": 3, "rd": None,
        "progress": 0.0, "actual_start": None, "actual_finish": None, "constraint": None,
        "resources": [], "tags": [], "start_floor": None, "es": "2027-03-01", "ef": "2027-03-03",
        "plan_start": "2027-03-01", "plan_finish": "2027-03-03", "tf": 0, "ff": 0,
        "critical": True, "status": "on_plan", "weight": 0.6,
    }
    assert _act(v, "B")["weight"] == 0.4


def test_weight_skips_milestones_and_rounds(client, admin, session):
    acts = [task("A", 1), task("B", 2), task("C", 4), task("M", 0, kind="finish_ms")]
    sid = store(session, make(acts))
    v = _get(client, admin, sid)
    assert [_act(v, i)["weight"] for i in "ABCM"] == [0.1429, 0.2857, 0.5714, 0.0]


def test_list_schedules(client, user, sid):
    r = client.get("/api/schedules", headers=user)
    assert r.status_code == 200
    [row] = r.json()
    assert {k: row[k] for k in ("id", "name", "domain", "level", "version", "finish")} == {
        "id": sid, "name": "시험 일정", "domain": "construction", "level": "L3",
        "version": 1, "finish": "2027-03-05",
    }
    assert row["updated_at"]


def test_routes_require_login(client, sid):
    r = client.get(f"/api/schedules/{sid}")
    assert r.status_code == 401 and r.json()["code"] == "unauthorized"
    assert client.get("/api/schedules").status_code == 401
    assert _patch(client, {}, sid, "A", 1, od=5).status_code == 401


def test_unknown_schedule_activity_or_version_is_404(client, admin, sid):
    for r in (
        client.get(f"/api/schedules/{sid + 1}", headers=admin),
        client.get(f"/api/schedules/{sid + 1}/versions", headers=admin),
        _patch(client, admin, sid, "ZZ", 1, od=5),
        _patch(client, admin, sid + 1, "A", 1, od=5),
        client.delete(f"/api/schedules/{sid}/activities/ZZ?base_version=1", headers=admin),
        client.put(f"/api/schedules/{sid}/activities/ZZ/predecessors", json={"items": [], "base_version": 1}, headers=admin),
        client.post(f"/api/schedules/{sid}/versions/9/restore", json={"base_version": 1}, headers=admin),
    ):
        assert r.status_code == 404 and r.json()["code"] == "not_found", r.json()


# ── 상태·Plan ───────────────────────────────────────────────────────


def test_status_late_early_and_warnings(client, admin, sid):
    v = _patch(client, admin, sid, "A", 1, od=5).json()
    assert (_act(v, "A")["status"], _act(v, "B")["status"]) == ("late +2", "late +2")
    assert v["plan_finish"] == "2027-03-05" and v["finish"] == "2027-03-09"
    assert v["summary"]["warning_count"] == 2
    v = _patch(client, admin, sid, "A", 2, od=2).json()
    assert (_act(v, "A")["status"], _act(v, "B")["status"]) == ("early -1", "early -1")
    assert v["summary"]["warning_count"] == 0


def test_negative_float_is_counted(client, admin, sid):
    v = _patch(client, admin, sid, "B", 1, constraint={"type": "FNLT", "date": "2027-03-04"}).json()
    assert _act(v, "B")["tf"] == -1
    assert v["summary"]["negative_float_count"] == 2


def test_new_activity_status_and_generated_ids(client, admin, sid):
    r = client.post(
        f"/api/schedules/{sid}/activities",
        json={"name": "마감", "kind": "task", "wbs": "1", "od": 2, "after": "B", "base_version": 1},
        headers=admin,
    )
    assert r.status_code == 200, r.json()
    v = r.json()
    new = _act(v, "A1010")
    assert (new["status"], new["plan_start"], new["plan_finish"], new["es"]) == ("new", None, None, "2027-03-08")
    assert {"pred": "B", "succ": "A1010", "type": "FS", "lag": 0} in v["relations"]
    assert [a["id"] for a in v["activities"]] == ["A", "B", "A1010"]
    body = {"name": "x", "kind": "task", "wbs": "1", "od": 1, "base_version": 2}
    assert client.post(f"/api/schedules/{sid}/activities", json=body, headers=admin).json()["activities"][-1]["id"] == "A1020"
    body = {**body, "id": "A1035", "base_version": 3}
    assert _act(client.post(f"/api/schedules/{sid}/activities", json=body, headers=admin).json(), "A1035")
    body = {**body, "base_version": 4}
    del body["id"]
    assert client.post(f"/api/schedules/{sid}/activities", json=body, headers=admin).json()["activities"][-1]["id"] == "A1040"


def test_plan_version_is_the_marked_one(client, admin, session, sid):
    _patch(client, admin, sid, "A", 1, od=5)
    _patch(client, admin, sid, "A", 2, od=6)
    session.get(ScheduleVersion, (sid, 2)).is_plan = True
    session.commit()
    v = _get(client, admin, sid)
    assert (v["plan_finish"], _act(v, "A")["plan_finish"], _act(v, "A")["status"]) == ("2027-03-09", "2027-03-05", "late +1")


def test_leveled_dates_appear_in_view(client, admin, session):
    s = make(
        [task("X", 2, resources=("crane",)), task("Y", 2, resources=("crane",))],
        resources=[Resource("crane", "타워크레인", "대", 1)],
    )
    v = _get(client, admin, store(session, s))
    assert (_act(v, "X")["es"], _act(v, "X")["ef"]) == ("2027-03-01", "2027-03-02")
    assert (_act(v, "Y")["es"], _act(v, "Y")["ef"]) == ("2027-03-03", "2027-03-04")
    assert v["finish"] == v["plan_finish"] == "2027-03-04"
    assert _act(v, "Y")["status"] == "on_plan"


# ── 고치기 ──────────────────────────────────────────────────────────


def test_write_records_version_note_and_change_log(client, user, session, sid):
    assert _patch(client, user, sid, "A", 1, od=5).status_code == 200
    [v2, v1] = _versions(client, user, sid)
    assert (v2["n"], v2["note"], v2["by_kind"], v2["by_name"], v2["is_plan"]) == (2, "A 기간 3 → 5", "user", "일반 사용자", False)
    assert (v1["n"], v1["by_kind"], v1["by_name"]) == (1, "agent", "에이전트")
    assert v2["created_at"]
    session.expire_all()
    log = session.query(ChangeLog).filter_by(schedule_id=sid).one()
    assert (log.version_n, log.by_kind, log.by_name, log.summary) == (2, "user", "일반 사용자", "A 기간 3 → 5")
    assert log.changes_json == [{"id": "A", "field": "od", "from": 3, "to": 5}]


def test_patch_many_fields_and_explicit_null_clears(client, admin, session, sid):
    v = _patch(
        client, admin, sid, "A", 1, name="기초", constraint={"type": "SNET", "date": "2027-03-08"},
        tags=["타설"], resources=["crane"], rd=2,
    ).json()
    a = _act(v, "A")
    assert (a["name"], a["constraint"], a["tags"], a["resources"], a["rd"], a["es"]) == (
        "기초", {"type": "SNET", "date": "2027-03-08"}, ["타설"], ["crane"], 2, "2027-03-08"
    )
    session.expire_all()
    log = session.query(ChangeLog).filter_by(schedule_id=sid).one()
    assert {c["field"]: (c["from"], c["to"]) for c in log.changes_json} == {
        "name": ("작업 A", "기초"), "constraint": (None, {"type": "SNET", "date": "2027-03-08"}),
        "tags": ([], ["타설"]), "resources": ([], ["crane"]), "rd": (None, 2),
    }
    a = _act(_patch(client, admin, sid, "A", 2, constraint=None, rd=None).json(), "A")
    assert (a["constraint"], a["rd"], a["es"]) == (None, None, "2027-03-01")


def test_null_on_required_field_is_invalid_request(client, admin, sid):
    for field in ("name", "od", "kind", "wbs", "progress", "tags", "resources"):
        r = _patch(client, admin, sid, "A", 1, **{field: None})
        assert r.status_code == 422 and r.json()["code"] == "invalid_request", field
    r = client.patch(f"/api/schedules/{sid}/activities/A", json={"od": 5}, headers=admin)
    assert r.status_code == 422 and r.json()["code"] == "invalid_request"


def test_delete_removes_activity_and_its_relations(client, admin, session, sid):
    r = client.delete(f"/api/schedules/{sid}/activities/A?base_version=1", headers=admin)
    assert r.status_code == 200, r.json()
    v = r.json()
    assert [a["id"] for a in v["activities"]] == ["B"] and v["relations"] == []
    assert (v["version"], _versions(client, admin, sid)[0]["note"]) == (2, "A 삭제")


def test_put_predecessors_replaces_only_that_activity(client, admin, session):
    sid = store(session, make([task("A", 1), task("B", 1), task("C", 1)], [Relation("A", "C"), Relation("A", "B")]))
    r = client.put(
        f"/api/schedules/{sid}/activities/C/predecessors",
        json={"items": [{"pred": "B", "type": "SS", "lag": 1}], "base_version": 1},
        headers=admin,
    )
    assert r.status_code == 200, r.json()
    assert r.json()["relations"] == [
        {"pred": "A", "succ": "B", "type": "FS", "lag": 0},
        {"pred": "B", "succ": "C", "type": "SS", "lag": 1},
    ]
    assert _versions(client, admin, sid)[0]["note"] == "C 선행 A(FS) → B(SS+1)"


def test_noop_write_creates_no_version(client, admin, session, sid):
    r = _patch(client, admin, sid, "A", 1, od=3, name="작업 A")
    assert r.status_code == 200 and r.json()["version"] == 1
    r = client.put(
        f"/api/schedules/{sid}/activities/B/predecessors",
        json={"items": [{"pred": "A"}], "base_version": 1},
        headers=admin,
    )
    assert r.status_code == 200 and r.json()["version"] == 1
    assert len(_versions(client, admin, sid)) == 1
    session.expire_all()
    assert session.query(ChangeLog).filter_by(schedule_id=sid).count() == 0


# ── 계산이 깨지는 고침 ──────────────────────────────────────────────

BLOCKED_ALL_YEAR = CalendarSpec(5, blocked=(BlockedPeriod((1, 1), (12, 31), "동절기"),))


def _one_task(session):
    return store(session, make([task("A", 2)]))


def _blocked_cal(session):
    return store(session, make([task("A", 2)], cal=BLOCKED_ALL_YEAR))


def _new(**k):
    return {"name": "x", "kind": "task", "wbs": "1", "od": 1, "base_version": 1, **k}


ERROR_CASES = {
    "cycle": (None, "put", "A/predecessors", {"items": [{"pred": "B"}]}, "선후 관계가 고리를 이룹니다."),
    "dangling_ref": (None, "post", "", _new(after="ZZ"), "없는 액티비티를 가리키는 관계가 있습니다."),
    "bad_duration": (None, "patch", "A", {"kind": "start_ms"}, "기간이 올바르지 않습니다."),
    "empty": (_one_task, "delete", "A?base_version=1", None, "액티비티가 없습니다."),
    "no_workdays": (_blocked_cal, "patch", "A", {"tags": ["동절기"]}, "일할 수 있는 날이 없는 달력입니다."),
    "duplicate_id": (None, "post", "", _new(id="A"), "같은 ID의 액티비티가 있습니다."),
}


@pytest.mark.parametrize("code", ERROR_CASES)
def test_schedule_error_is_422_and_nothing_saved(client, admin, session, sid, code):
    setup, method, path, body, message = ERROR_CASES[code]
    target = setup(session) if setup else sid
    if body is not None and "base_version" not in body:
        body = {**body, "base_version": 1}
    kw = {"json": body} if body is not None else {}
    r = client.request(method.upper(), f"/api/schedules/{target}/activities/{path}".rstrip("/"), headers=admin, **kw)
    assert r.status_code == 422
    assert (r.json()["code"], r.json()["message"]) == ("schedule_invalid", message)
    assert isinstance(r.json()["detail"], dict)
    assert _get(client, admin, target)["version"] == 1
    assert len(_versions(client, admin, target)) == 1
    session.expire_all()
    assert session.query(ChangeLog).filter_by(schedule_id=target).count() == 0


def test_cycle_detail_names_activities(client, admin, sid):
    r = client.put(f"/api/schedules/{sid}/activities/A/predecessors", json={"items": [{"pred": "B"}], "base_version": 1}, headers=admin)
    assert r.json()["detail"] == {"activities": ["A", "B"]}


# ── 버전 충돌·되돌리기 ──────────────────────────────────────────────

WRITES = {
    "patch": ("patch", "activities/A", {"od": 4}),
    "post": ("post", "activities", _new()),
    "delete": ("delete", "activities/B?base_version=1", None),
    "put": ("put", "activities/B/predecessors", {"items": []}),
    "restore": ("post", "versions/1/restore", {}),
}


@pytest.mark.parametrize("route", WRITES)
def test_stale_base_version_is_409_on_every_write(client, admin, sid, route):
    assert _patch(client, admin, sid, "A", 1, od=5).json()["version"] == 2
    method, path, body = WRITES[route]
    kw = {"json": {**body, "base_version": 1}} if body is not None else {}
    r = client.request(method.upper(), f"/api/schedules/{sid}/{path}", headers=admin, **kw)
    assert r.status_code == 409
    assert r.json() == {
        "code": "version_conflict",
        "message": "그 사이 일정이 바뀌었습니다. 다시 불러와 주세요.",
        "detail": {"current": 2},
    }
    assert len(_versions(client, admin, sid)) == 2


def test_restore_returns_view_and_keeps_history(client, admin, sid):
    _patch(client, admin, sid, "A", 1, od=5)
    r = client.post(f"/api/schedules/{sid}/versions/1/restore", json={"base_version": 2}, headers=admin)
    assert r.status_code == 200, r.json()
    v = r.json()
    assert (v["version"], _act(v, "A")["od"], v["finish"]) == (3, 3, "2027-03-05")
    versions = _versions(client, admin, sid)
    assert [x["n"] for x in versions] == [3, 2, 1]
    assert (versions[0]["note"], versions[0]["by_kind"], versions[0]["by_name"]) == ("1번 버전으로 되돌림", "user", "관리자")


# ── 고침 1차 ────────────────────────────────────────────────────────

CYCLE = make([task("A", 1), task("B", 1)], [Relation("A", "B"), Relation("B", "A")])


def _corrupt_v1_after_valid_edit(client, admin, session, sid):
    """버전 2(올바름)를 만든 뒤 Plan 인 버전 1 을 계산이 안 되는 일정으로 바꿔 쓴다."""
    assert _patch(client, admin, sid, "A", 1, od=5).status_code == 200
    session.get(ScheduleVersion, (sid, 1)).snapshot_json = to_json(CYCLE)
    session.commit()


def test_invalid_plan_snapshot_gives_null_plan_fields(client, admin, session, sid):
    _corrupt_v1_after_valid_edit(client, admin, session, sid)
    for v in (_get(client, admin, sid), _patch(client, admin, sid, "B", 2, od=3).json()):
        assert v["plan_finish"] is None and v["finish"] is not None
        assert {(a["plan_start"], a["plan_finish"], a["status"]) for a in v["activities"]} == {(None, None, "new")}
    assert _get(client, admin, sid)["version"] == 3


def test_restore_of_invalid_version_is_422_and_saves_nothing(client, admin, session, sid):
    _corrupt_v1_after_valid_edit(client, admin, session, sid)
    r = client.post(f"/api/schedules/{sid}/versions/1/restore", json={"base_version": 2}, headers=admin)
    assert r.status_code == 422
    assert (r.json()["code"], r.json()["message"]) == ("schedule_invalid", "선후 관계가 고리를 이룹니다.")
    assert len(_versions(client, admin, sid)) == 2
    session.expire_all()
    assert session.query(ChangeLog).filter_by(schedule_id=sid).count() == 1


def test_marked_plan_feeds_plan_fields(client, admin, session, sid):
    _patch(client, admin, sid, "A", 1, od=5)
    _patch(client, admin, sid, "A", 2, od=6)
    mark_plan(session, sid, 2)
    v = _get(client, admin, sid)
    assert (v["plan_finish"], _act(v, "A")["plan_finish"]) == ("2027-03-09", "2027-03-05")
    assert [x["is_plan"] for x in _versions(client, admin, sid)] == [False, True, False]


@pytest.mark.parametrize(
    "body",
    [{"progress": 1.5}, {"progress": -0.1}, {"od": -1}, {"od": 2.5}, {"rd": -1}, {"rd": 1.5}, {"color": "red"}],
)
def test_patch_shape_errors_are_invalid_request(client, admin, sid, body):
    r = _patch(client, admin, sid, "A", 1, **body)
    assert r.status_code == 422 and r.json()["code"] == "invalid_request", body
    assert _get(client, admin, sid)["version"] == 1


def test_other_request_models_reject_unknown_fields(client, admin, sid):
    for r in (
        client.post(f"/api/schedules/{sid}/activities", json=_new(color="red"), headers=admin),
        client.post(f"/api/schedules/{sid}/activities", json=_new(od=-1), headers=admin),
        client.put(f"/api/schedules/{sid}/activities/B/predecessors", json={"items": [{"pred": "A", "x": 1}], "base_version": 1}, headers=admin),
        client.put(f"/api/schedules/{sid}/activities/B/predecessors", json={"items": [], "base_version": 1, "x": 1}, headers=admin),
        client.post(f"/api/schedules/{sid}/versions/1/restore", json={"base_version": 1, "x": 1}, headers=admin),
        _patch(client, admin, sid, "A", 1, constraint={"type": "SNET", "date": "2027-03-08", "x": 1}),
    ):
        assert r.status_code == 422 and r.json()["code"] == "invalid_request", r.json()


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"actual_start": "2027-03-05", "actual_finish": "2027-03-04"}, "실제 종료일이 실제 시작일보다 앞설 수 없습니다."),
        ({"wbs": "9"}, "없는 WBS 코드입니다: 9"),
        ({"resources": ["crane", "pump"]}, "없는 자원입니다: pump"),
    ],
)
def test_patch_semantic_errors_are_invalid_activity(client, admin, sid, body, message):
    r = _patch(client, admin, sid, "A", 1, **body)
    assert r.status_code == 422
    assert (r.json()["code"], r.json()["message"]) == ("invalid_activity", message)
    assert _get(client, admin, sid)["version"] == 1


def test_finish_before_existing_start_is_rejected(client, admin, sid):
    assert _patch(client, admin, sid, "A", 1, actual_start="2027-03-02").status_code == 200
    r = _patch(client, admin, sid, "A", 2, actual_finish="2027-03-01")
    assert r.status_code == 422 and r.json()["code"] == "invalid_activity"


def test_post_with_unknown_wbs_is_invalid_activity(client, admin, sid):
    r = client.post(f"/api/schedules/{sid}/activities", json=_new(wbs="9"), headers=admin)
    assert r.status_code == 422
    assert (r.json()["code"], r.json()["message"]) == ("invalid_activity", "없는 WBS 코드입니다: 9")


def test_next_id_goes_past_four_digits():
    assert edits.next_id(make([task("A9990", 1)])) == "A10000"
    assert edits.next_id(make([task("A10000", 1), task("A1035", 1)])) == "A10010"
    assert edits.next_id(make([task("A1035", 1)])) == "A1040"


def _aware(s: str) -> bool:
    return datetime.fromisoformat(s).tzinfo is not None


def test_timestamps_carry_utc_offset(client, admin, sid):
    _patch(client, admin, sid, "A", 1, od=5)
    assert all(_aware(row["updated_at"]) for row in client.get("/api/schedules", headers=admin).json())
    assert all(_aware(v["created_at"]) for v in _versions(client, admin, sid))


def test_weight_is_zero_when_there_is_no_duration(client, admin, session):
    sid = store(session, make([task("S", 0, kind="start_ms"), task("F", 0, kind="finish_ms")], [Relation("S", "F")]))
    assert [a["weight"] for a in _get(client, admin, sid)["activities"]] == [0.0, 0.0]


def test_explicit_null_clears_actual_dates(client, admin, sid):
    _patch(client, admin, sid, "A", 1, actual_start="2027-03-01", actual_finish="2027-03-03")
    a = _act(_patch(client, admin, sid, "A", 2, actual_start=None, actual_finish=None).json(), "A")
    assert (a["actual_start"], a["actual_finish"], a["status"]) == (None, None, "on_plan")


def _last_changes(session, sid):
    session.expire_all()
    return session.query(ChangeLog).filter_by(schedule_id=sid).order_by(ChangeLog.id.desc()).first().changes_json


def test_changes_json_for_post_delete_and_put(client, admin, session, sid):
    client.post(f"/api/schedules/{sid}/activities", json=_new(name="마감", after="B"), headers=admin)
    added = {
        "id": "A1010", "name": "마감", "kind": "task", "wbs": "1", "od": 1, "rd": None, "progress": 0.0,
        "actual_start": None, "actual_finish": None, "constraint": None, "resources": [], "tags": [],
        "start_floor": None,
    }
    assert _last_changes(session, sid) == [
        {"id": "A1010", "field": "activity", "from": None, "to": added},
        {"id": "A1010", "field": "predecessors", "from": [], "to": [{"pred": "B", "type": "FS", "lag": 0}]},
    ]
    client.put(f"/api/schedules/{sid}/activities/A1010/predecessors", json={"items": [{"pred": "A", "lag": 2}], "base_version": 2}, headers=admin)
    assert _last_changes(session, sid) == [
        {"id": "A1010", "field": "predecessors", "from": [{"pred": "B", "type": "FS", "lag": 0}],
         "to": [{"pred": "A", "type": "FS", "lag": 2}]},
    ]
    client.delete(f"/api/schedules/{sid}/activities/A1010?base_version=3", headers=admin)
    assert _last_changes(session, sid) == [
        {"id": "A1010", "field": "activity", "from": added, "to": None},
        {"id": "A1010", "field": "relation", "from": {"succ": "A1010", "pred": "A", "type": "FS", "lag": 2}, "to": None},
    ]


def test_conflict_at_save_time_is_409(client, admin, session, sid, sample_schedule, monkeypatch):
    """확인을 지난 뒤 저장 직전에 다른 요청이 먼저 저장하면 409, 고침은 남지 않는다."""
    real_run = service.run

    def run_after_someone_saves(schedule, conditions=None):
        save_new_version(session, sid, sample_schedule, [], by_kind="agent", by_name="에이전트", note="먼저", changes=[], base_version=1)
        return real_run(schedule, conditions)

    monkeypatch.setattr(service, "run", run_after_someone_saves)
    r = _patch(client, admin, sid, "A", 1, od=5)
    assert r.status_code == 409 and r.json()["detail"] == {"current": 2}
    assert [(x["n"], x["by_name"]) for x in _versions(client, admin, sid)] == [(2, "에이전트"), (1, "에이전트")]


def test_write_reuses_the_checked_computation(client, admin, sid, monkeypatch):
    """쓰기 뒤 화면은 지금 일정을 다시 계산하지 않는다(Plan 버전 1 만 계산)."""
    from app.store import view

    calls = []
    real_run = view.run
    monkeypatch.setattr(view, "run", lambda s: calls.append(s) or real_run(s))
    v = _patch(client, admin, sid, "A", 1, od=5).json()
    assert v["finish"] == "2027-03-09" and v["plan_finish"] == "2027-03-05"
    assert len(calls) == 1 and calls[0].activities[0].od == 3  # 버전 1(Plan) 의 A
