"""탐색기 API: 일정 목록(tree)·관리자만 일정 지우기."""

from sqlalchemy import func, select

from app.core.model import Relation
from app.store.tables import Approval, ChangeLog, ScheduleRecord, ScheduleVersion
from app.store.versions import save_new_version
from tests import schedules


def test_tree_lists_schedules(client, admin, sid):
    assert client.get("/api/explorer/tree", headers=admin).json()["schedules"][0]["id"] == sid


def test_user_cannot_delete_schedule(client, user, sid):
    assert client.delete(f"/api/schedules/{sid}", headers=user).status_code == 403


def test_tree_item_shape_and_values(client, user, sid, session, sample_schedule):
    save_new_version(session, sid, sample_schedule, [], by_kind="user", by_name="김하늘", note="고침",
                     changes=[], base_version=1)
    body = client.get("/api/explorer/tree", headers=user).json()
    assert set(body) == {"schedules"}
    [item] = body["schedules"]
    assert set(item) == {"id", "name", "domain", "level", "version", "finish", "updated_at"}
    assert (item["id"], item["name"], item["domain"], item["level"], item["version"], item["finish"]) == (
        sid, "시험 일정", "construction", "L3", 2, "2027-03-05",
    )
    assert item["updated_at"].endswith("Z")


def test_tree_needs_login(client, sid):
    res = client.get("/api/explorer/tree")
    assert res.status_code == 401 and res.json()["code"] == "unauthorized"


def test_tree_lists_every_schedule_in_id_order_and_a_broken_one_has_no_finish(client, user, session, sample_schedule):
    first = schedules.store(session, sample_schedule)
    second = schedules.store(session, sample_schedule)
    row = session.get(ScheduleVersion, (second, 1))
    row.snapshot_json = {**row.snapshot_json, "relations": [*row.snapshot_json["relations"],
                                                            {"pred": "B", "succ": "A", "type": "FS", "lag": 0}]}
    session.commit()
    items = client.get("/api/explorer/tree", headers=user).json()["schedules"]
    assert [(i["id"], i["finish"]) for i in items] == [(first, "2027-03-05"), (second, None)]


def test_tree_finish_uses_the_saved_conditions(client, user, session):
    two = schedules.make([schedules.task("A", 3), schedules.task("B", 2)], [Relation("A", "B")])
    sid = schedules.store(session, two, [{"id": "in.start", "layer": "input", "kind": "start_after",
                                         "params": {"date": "2027-03-08"}, "text": "3월 8일 이후 착공",
                                         "source": "프롬프트"}])
    [item] = client.get("/api/explorer/tree", headers=user).json()["schedules"]
    assert item["id"] == sid and item["finish"] == "2027-03-12"


def test_admin_deletes_a_schedule_with_its_versions_and_history(client, admin, sid, session, sample_schedule):
    other = schedules.store(session, sample_schedule)
    save_new_version(session, sid, sample_schedule, [], by_kind="user", by_name="김하늘", note="고침",
                     changes=[{"id": "A", "field": "od", "from": 3, "to": 3}], base_version=1)
    res = client.delete(f"/api/schedules/{sid}", headers=admin)
    assert res.status_code == 200 and res.json() == {"deleted": sid}
    session.expire_all()
    assert session.get(ScheduleRecord, sid) is None
    assert session.scalar(select(func.count()).select_from(ScheduleVersion).where(ScheduleVersion.schedule_id == sid)) == 0
    assert session.scalar(select(func.count()).select_from(ChangeLog).where(ChangeLog.schedule_id == sid)) == 0
    assert [i["id"] for i in client.get("/api/explorer/tree", headers=admin).json()["schedules"]] == [other]
    assert client.get(f"/api/schedules/{sid}", headers=admin).status_code == 404
    assert client.get(f"/api/schedules/{other}", headers=admin).status_code == 200


def test_deleting_a_missing_schedule_is_404(client, admin):
    res = client.delete("/api/schedules/999", headers=admin)
    assert res.status_code == 404
    assert res.json() == {"code": "not_found", "message": "일정을 찾을 수 없습니다.", "detail": None}


def test_user_delete_is_refused_with_admin_only_and_nothing_changes(client, user, sid, session):
    res = client.delete(f"/api/schedules/{sid}", headers=user)
    assert res.json() == {"code": "admin_only", "message": "관리자만 할 수 있습니다.", "detail": None}
    session.expire_all()
    assert session.get(ScheduleRecord, sid) is not None


def test_delete_needs_login(client, sid):
    assert client.delete(f"/api/schedules/{sid}").status_code == 401


def _approval(session, schedule_id: int | None, status: str) -> int:
    row = Approval(schedule_id=schedule_id, kind="change", title="B 기간 4일", base_version=1, summary_json={},
                   snapshot_json={}, requested_by="김하늘", status=status)
    session.add(row)
    session.commit()
    return row.id


def test_pending_approvals_of_a_deleted_schedule_are_closed_as_conflict(client, admin, sid, session, sample_schedule):
    other = schedules.store(session, sample_schedule)
    pending = _approval(session, sid, "pending")
    auto = _approval(session, sid, "auto")
    elsewhere = _approval(session, other, "pending")
    assert client.delete(f"/api/schedules/{sid}", headers=admin).status_code == 200
    session.expire_all()
    closed = session.get(Approval, pending)
    assert (closed.status, closed.decided_by, closed.note) == ("conflict", "관리자", "일정을 지웠습니다.")
    assert closed.decided_at is not None
    assert session.get(Approval, auto).status == "auto"
    assert session.get(Approval, elsewhere).status == "pending"
    assert client.get("/api/approvals/count", headers=admin).json() == {"pending": 1}
