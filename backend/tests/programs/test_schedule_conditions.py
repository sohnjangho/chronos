"""일정 목록·저장 전 확인이 저장된 조건을 반영한다 (Task 7 fix round 1 덧붙임)."""

from app.core.model import Relation, Resource
from app.harness.conditions import Condition
from app.store.schedules import to_json
from app.store.tables import ScheduleVersion
from tests.schedules import make, store, task

# 타설 꼬리표를 단 액티비티의 모든 날을 막는다: 그런 액티비티가 생기면 일할 날이 없는 일정이 된다.
ALL_YEAR_POUR = Condition(
    "i1", "input", "blocked_period", {"start_md": [1, 1], "end_md": [12, 31], "tag": "타설"}, "", "프롬프트"
).to_dict()
NO_WORKDAYS = ("schedule_invalid", "일할 수 있는 날이 없는 달력입니다.")


def _versions(client, headers, sid) -> list:
    return client.get(f"/api/schedules/{sid}/versions", headers=headers).json()


def test_list_and_detail_show_the_same_finish(client, admin, session):
    # 저장된 크레인 1대, 조건으로 2대: 조건을 넣으면 A·B 가 같이 일해 준공 03.03(넣지 않으면 03.08).
    crane = Resource("crane", "타워크레인", "대", 1)
    schedule = make([task("A", 3, resources=("crane",)), task("B", 3, resources=("crane",))], resources=[crane])
    two = Condition("i1", "input", "resource_cap", {"resource_id": "crane", "capacity": 2}, "", "프롬프트")
    sid = store(session, schedule, conditions=[two.to_dict()])
    detail = client.get(f"/api/schedules/{sid}", headers=admin).json()["finish"]
    listed = next(i for i in client.get("/api/schedules", headers=admin).json() if i["id"] == sid)["finish"]
    assert detail == listed == "2027-03-03"


def test_write_is_rejected_when_the_conditions_leave_no_workday(client, admin, session):
    sid = store(session, make([task("A", 3), task("B", 2)], [Relation("A", "B")]), conditions=[ALL_YEAR_POUR])
    r = client.patch(f"/api/schedules/{sid}/activities/B", json={"tags": ["타설"], "base_version": 1}, headers=admin)
    assert r.status_code == 422 and (r.json()["code"], r.json()["message"]) == NO_WORKDAYS
    assert len(_versions(client, admin, sid)) == 1
    view = client.get(f"/api/schedules/{sid}", headers=admin)
    assert view.status_code == 200 and view.json()["version"] == 1


def test_restore_is_rejected_when_the_target_conditions_leave_no_workday(client, admin, session):
    sid = store(session, make([task("A", 3), task("B", 2)], [Relation("A", "B")]), conditions=[ALL_YEAR_POUR])
    assert client.patch(f"/api/schedules/{sid}/activities/A", json={"od": 5, "base_version": 1}, headers=admin).status_code == 200
    # 버전 1 의 스냅숏만 바꿔 B 에 타설 꼬리표를 단다: 조건 없이는 계산되지만 버전 1 의 조건을 넣으면 안 된다.
    tagged = make([task("A", 3), task("B", 2, tags=("타설",))], [Relation("A", "B")])
    session.get(ScheduleVersion, (sid, 1)).snapshot_json = to_json(tagged)
    session.commit()
    r = client.post(f"/api/schedules/{sid}/versions/1/restore", json={"base_version": 2}, headers=admin)
    assert r.status_code == 422 and (r.json()["code"], r.json()["message"]) == NO_WORKDAYS
    assert len(_versions(client, admin, sid)) == 2
    view = client.get(f"/api/schedules/{sid}", headers=admin)
    assert view.status_code == 200 and view.json()["version"] == 2
