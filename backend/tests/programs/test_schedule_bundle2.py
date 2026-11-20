"""일정 API 의 묶음 2 칸(Task 21): 늦은 날짜·가중치 방식·Data Date 고치기·작업 금지 기간 날짜."""

from sqlalchemy import select

from app.store.tables import ChangeLog
from tests.schedules import make, store, task


def act(view: dict, aid: str) -> dict:
    return next(x for x in view["activities"] if x["id"] == aid)


def view(client, headers, sid: int) -> dict:
    r = client.get(f"/api/schedules/{sid}", headers=headers)
    assert r.status_code == 200, r.json()
    return r.json()


def blocked(cid: str, start_md: list[int], end_md: list[int], tag: str) -> dict:
    return {"id": cid, "layer": "input", "kind": "blocked_period",
            "params": {"start_md": start_md, "end_md": end_md, "tag": tag}, "text": f"{tag} 금지 기간",
            "source": "프롬프트", "enabled": True}


# ── 작업 지시서의 시험 ──────────────────────────────────────────────


def test_view_has_late_dates_and_manual_weight(client, admin, sid):
    a = act(client.get(f"/api/schedules/{sid}", headers=admin).json(), "A")
    assert (a["ls"], a["lf"], a["manual_weight"]) == ("2027-03-01", "2027-03-03", None)
def test_duration_mode_is_default(client, admin, sid):
    v = client.get(f"/api/schedules/{sid}", headers=admin).json()
    assert v["weight_mode"] == "duration" and act(v, "A")["weight"] == 0.6 and v["summary"]["weight_missing"] == 0
def test_manual_weight_mode(client, admin, sid):
    assert client.put(f"/api/schedules/{sid}/weight-mode", json={"mode": "manual"}, headers=admin).json() == {"mode": "manual"}
    v = client.patch(f"/api/schedules/{sid}/activities/A", json={"manual_weight": 3, "base_version": 1}, headers=admin).json()
    assert v["weight_mode"] == "manual" and act(v, "A")["weight"] == 1.0 and act(v, "B")["weight"] == 0.0 and v["summary"]["weight_missing"] == 1
def test_data_date_patch_makes_a_version(client, admin, sid):
    v = client.patch(f"/api/schedules/{sid}", json={"data_date": "2027-03-03", "base_version": 1}, headers=admin).json()
    assert v["version"] == 2 and v["data_date"] == "2027-03-03"
    assert client.get(f"/api/schedules/{sid}/versions", headers=admin).json()[0]["note"] == "Data Date 2027-03-03"
def test_data_date_patch_stale_and_range(client, admin, sid):
    assert client.patch(f"/api/schedules/{sid}", json={"data_date": "2027-03-03", "base_version": 0}, headers=admin).status_code == 409
    assert client.patch(f"/api/schedules/{sid}", json={"data_date": "1899-12-31", "base_version": 1}, headers=admin).json()["code"] == "invalid_request"
def test_blocked_periods_are_dated(client, admin, session):
    sid = store(session, make([task("A", 200)]), [blocked("in.blocked_period.프레스", [7, 29], [8, 4], "프레스")])
    assert view(client, admin, sid)["calendar"]["blocked"] == [{"tag": "프레스", "start": "2027-07-29", "finish": "2027-08-04"}]
def test_wrapping_period_ends_next_year(client, admin, session):
    sid = store(session, make([task("A", 260)]), [blocked("in.blocked_period.타설", [12, 1], [2, 28], "타설")])
    v = view(client, admin, sid)
    assert v["finish"] == "2028-02-25"
    assert v["calendar"]["blocked"] == [{"tag": "타설", "start": "2027-12-01", "finish": "2028-02-28"}]


# ── 더 본 것 ────────────────────────────────────────────────────────


def test_view_calendar_days_per_week(client, admin, sid):
    assert view(client, admin, sid)["calendar"] == {"days_per_week": 5, "blocked": []}


def test_manual_weight_note_and_clear(client, admin, sid):
    client.put(f"/api/schedules/{sid}/weight-mode", json={"mode": "manual"}, headers=admin)
    client.patch(f"/api/schedules/{sid}/activities/A", json={"manual_weight": 3, "base_version": 1}, headers=admin)
    v = client.patch(f"/api/schedules/{sid}/activities/A", json={"manual_weight": None, "base_version": 2}, headers=admin).json()
    assert act(v, "A")["manual_weight"] is None and v["summary"]["weight_missing"] == 2
    assert [x["note"] for x in client.get(f"/api/schedules/{sid}/versions", headers=admin).json()[:2]] == [
        "A 가중치 3 → 없음", "A 가중치 없음 → 3"
    ]


def test_manual_weights_split_by_their_sum(client, admin, session):
    sid = store(session, make([task("A", 1), task("B", 1), task("C", 1), task("D", 1)]))
    client.put(f"/api/schedules/{sid}/weight-mode", json={"mode": "manual"}, headers=admin)
    for n, (aid, w) in enumerate([("A", 1), ("B", 2), ("C", 0)], start=1):
        client.patch(f"/api/schedules/{sid}/activities/{aid}", json={"manual_weight": w, "base_version": n}, headers=admin)
    v = view(client, admin, sid)
    assert [act(v, i)["weight"] for i in "ABCD"] == [0.3333, 0.6667, 0.0, 0.0]
    assert v["summary"]["weight_missing"] == 1  # D 만(0 은 넣은 것)
    assert v["version"] == 4  # 방식 바꾸기는 버전을 만들지 않는다


def test_manual_weight_must_be_zero_or_more(client, admin, sid):
    for bad in (-1, True, "3"):
        r = client.patch(f"/api/schedules/{sid}/activities/A", json={"manual_weight": bad, "base_version": 1}, headers=admin)
        assert r.status_code == 422 and r.json()["code"] == "invalid_request", bad


def test_weight_mode_rejects_unknown_and_missing_schedule(client, admin, sid):
    assert client.put(f"/api/schedules/{sid}/weight-mode", json={"mode": "cost"}, headers=admin).json()["code"] == "invalid_request"
    assert client.put("/api/schedules/999/weight-mode", json={"mode": "manual"}, headers=admin).status_code == 404


def test_weight_mode_any_logged_in_user(client, user, sid):
    assert client.put(f"/api/schedules/{sid}/weight-mode", json={"mode": "manual"}, headers=user).json() == {"mode": "manual"}
    assert client.put(f"/api/schedules/{sid}/weight-mode", json={"mode": "manual"}).status_code == 401


def test_data_date_clear_and_history(client, admin, sid, session):
    client.patch(f"/api/schedules/{sid}", json={"data_date": "2027-03-03", "base_version": 1}, headers=admin)
    v = client.patch(f"/api/schedules/{sid}", json={"data_date": None, "base_version": 2}, headers=admin).json()
    assert v["version"] == 3 and v["data_date"] is None
    assert client.get(f"/api/schedules/{sid}/versions", headers=admin).json()[0]["note"] == "Data Date 지움"
    logs = session.scalars(select(ChangeLog).where(ChangeLog.schedule_id == sid).order_by(ChangeLog.id)).all()
    assert [(c.version_n, c.by_kind, c.changes_json) for c in logs] == [
        (2, "user", [{"id": None, "field": "data_date", "from": None, "to": "2027-03-03"}]),
        (3, "user", [{"id": None, "field": "data_date", "from": "2027-03-03", "to": None}]),
    ]


def test_data_date_same_value_makes_no_version(client, admin, sid):
    v = client.patch(f"/api/schedules/{sid}", json={"data_date": None, "base_version": 1}, headers=admin)
    assert v.status_code == 200 and v.json()["version"] == 1


def test_data_date_patch_rejects_unknown_fields_and_missing_schedule(client, admin, sid):
    r = client.patch(f"/api/schedules/{sid}", json={"data_date": "2027-03-03", "name": "x", "base_version": 1}, headers=admin)
    assert r.status_code == 422 and r.json()["code"] == "invalid_request"
    assert client.patch(f"/api/schedules/{sid}", json={"data_date": "2200-01-01", "base_version": 1}, headers=admin).status_code == 422
    assert client.patch("/api/schedules/999", json={"data_date": None, "base_version": 1}, headers=admin).status_code == 404


def test_period_outside_the_schedule_is_left_out(client, admin, session):
    # 2027-03-01 ~ 2027-03-05 일정: 7~8월 기간은 겹치지 않는다
    sid = store(session, make([task("A", 5)]), [blocked("in.blocked_period.프레스", [7, 29], [8, 4], "프레스")])
    assert view(client, admin, sid)["calendar"]["blocked"] == []


def test_leap_day_end_falls_back_in_common_years(client, admin, session):
    # 2027-03-01 ~ 2029-01-xx: 2027-12-01~2028-02-29(윤년), 2028-12-01~2029-02-28
    sid = store(session, make([task("A", 480)]), [blocked("in.blocked_period.타설", [12, 1], [2, 29], "타설")])
    v = view(client, admin, sid)
    assert v["finish"] >= "2028-12-01"
    assert v["calendar"]["blocked"] == [
        {"tag": "타설", "start": "2027-12-01", "finish": "2028-02-29"},
        {"tag": "타설", "start": "2028-12-01", "finish": "2029-02-28"},
    ]
