"""주의할 일정 API: 일정마다 위험·주의·괜찮음을 코드로 가른다."""

from datetime import date

import pytest

import app.programs.attention.service as attention_service
from app.core.model import Constraint, Relation
from app.store.delays import DelayEventRow
from tests.approval_doubles import finish_by
from tests.schedules import make, sample, store, task


@pytest.fixture(autouse=True)
def today_after_the_sample(monkeypatch):
    """시험 일정(2027)은 실제 오늘보다 뒤다 — Data Date 가 없는 일정의 실적은 「오늘」 뒤일 수 없어(리뷰) 오늘을 그 뒤로 둔다."""
    from app.agent import context

    monkeypatch.setattr(context, "today", lambda: date(2027, 12, 31))


def items(client, admin) -> list[dict]:
    r = client.get("/api/attention", headers=admin)
    assert r.status_code == 200, r.json()
    return r.json()["items"]


def item_of(client, admin, sid: int) -> dict:
    return next(i for i in items(client, admin) if i["id"] == sid)


def add_open_delay(session, sid: int, aid: str, days: int) -> None:
    session.add(DelayEventRow(schedule_id=sid, activity_id=aid, start_date=date(2027, 3, 4), days=days, created_by="김하늘"))
    session.commit()


def test_requires_login(client):
    assert client.get("/api/attention").status_code == 401


def test_levels(client, admin, session):
    late = store(session, make([task("A", 3), task("B", 2)], [Relation("A", "B")]), [finish_by("2027-03-04")])
    ok = store(session, sample())
    found = items(client, admin)
    assert [(i["id"], i["level"]) for i in found] == [(late, "danger"), (ok, "ok")]
    assert found[0]["violations"] == 1
    assert found[0]["finish"] == "2027-03-05" and found[0]["open_delays"] == 0


def test_open_delay_is_a_warning(client, admin, session, sid):
    assert item_of(client, admin, sid)["level"] == "ok"
    add_open_delay(session, sid, "B", 1)
    got = item_of(client, admin, sid)
    assert got["level"] == "warning" and got["open_delays"] == 1 and got["violations"] == 0


def test_order_is_danger_warning_ok_then_name(client, admin, session):
    ok = store(session, sample())
    warn = store(session, sample())
    add_open_delay(session, warn, "B", 1)
    danger = store(session, make([task("A", 3)]), [finish_by("2027-03-01")])
    assert [i["id"] for i in items(client, admin)] == [danger, warn, ok]


def test_unreadable_schedule_is_danger(client, admin, session):
    from app.store.tables import ScheduleVersion

    sid = store(session, sample())
    row = session.query(ScheduleVersion).filter_by(schedule_id=sid).one()
    snapshot = dict(row.snapshot_json)
    snapshot["relations"] = [{**snapshot["relations"][0], "succ": "ZZ"}]
    row.snapshot_json = snapshot
    session.commit()
    got = item_of(client, admin, sid)
    assert got["level"] == "danger" and got["violations"] == 1 and got["finish"] is None


def test_late_task_alone_is_a_warning(client, admin, session):
    sid = store(session, make([task("A", 3), task("B", 2)], [Relation("A", "B")]))
    body = {"actual_start": "2027-03-03", "progress": 0.5, "base_version": 1}  # 실적은 Plan(버전 1)을 옮기지 않는다
    assert client.patch(f"/api/schedules/{sid}/activities/A", json=body, headers=admin).status_code == 200
    got = item_of(client, admin, sid)
    assert got["late_count"] > 0 and got["violations"] == 0 and got["negative_float_count"] == 0
    assert got["level"] == "warning" and got["finish_delta"] > 0


def test_negative_float_alone_is_danger(client, admin, session):
    from dataclasses import replace

    capped = replace(task("B", 2), constraint=Constraint("FNLT", date(2027, 3, 4)))
    sid = store(session, make([task("A", 3), capped], [Relation("A", "B")]))
    got = item_of(client, admin, sid)
    assert got["negative_float_count"] > 0 and got["violations"] == 0 and got["level"] == "danger"


def test_one_failing_schedule_does_not_break_the_list(client, admin, session, monkeypatch):
    bad = store(session, sample())
    good = store(session, make([task("A", 3)]))
    real = attention_service.check

    def flaky(schedule, conditions):
        if len(schedule.activities) == 2:
            raise RuntimeError("점검 실패")
        return real(schedule, conditions)

    monkeypatch.setattr(attention_service, "check", flaky)
    found = {i["id"]: i for i in items(client, admin)}
    assert found[bad]["level"] == "danger" and found[bad]["violations"] == 1 and found[bad]["finish"] is None
    assert found[good]["level"] == "ok"
