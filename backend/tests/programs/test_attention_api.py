"""주의할 일정 API: 일정마다 위험·주의·괜찮음을 코드로 가른다."""

from datetime import date

from app.core.model import Relation
from app.store.delays import DelayEventRow
from tests.approval_doubles import finish_by
from tests.schedules import make, sample, store, task


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
