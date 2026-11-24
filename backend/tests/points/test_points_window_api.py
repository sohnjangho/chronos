"""「관리 포인트」 창(계획 5 Task 11)이 쓰는 읽기 API 둘과 보드 칸.

- GET /points/history: 보드 칸(window — Data Date·주 칸, 화면은 날짜를 계산하지 않는다), 버전마다 들어옴·빠짐(까닭)·여유 줄어듦, 가정(미리 보기) 줄, 고른 작업의 버전별 여유.
- POST /points/{activity_id}/accel {days}: points.accel_check 와 같은 계산(읽기 — 버전·카드를 만들지 않는다).
권한: 로그인한 누구나 읽는다(현장 관리자 포함). 담당자 연락은 그대로 현장 403. 바깥 호출 없음.
"""

from dataclasses import replace
from datetime import date

import pytest
from sqlalchemy import select

from app.core.model import Relation
from app.points import card
from app.security.passwords import hash_password
from app.security.tokens import issue_token
from app.store.schedules import list_records, load
from app.store.tables import User
from app.store.versions import save_new_version
from app.tools import registry
from app.tools.context import ToolContext
from app.tools.registry import call
from tests.helpers import auth
from tests.schedules import make, store, task


def _base():
    """A(3) → B(2) 크리티컬, C(1) 홀로(여유 4 — 포인트 아님). 3/1(월) 시작, 주 5일."""
    return make([task("A", 3), task("B", 2), task("C", 1)], [Relation("A", "B")])


def _od(schedule, **ods):
    return replace(schedule, activities=tuple(replace(a, od=ods.get(a.id, a.od)) for a in schedule.activities))


def _save(session, sid, schedule, base: int, note: str = "고침") -> int:
    return save_new_version(session, sid, schedule, [], by_kind="user", by_name="손장호", note=note, changes=[],
                            base_version=base, plan_change=False)


def _url(sid: int, rest: str = "") -> str:
    return f"/api/schedules/{sid}/points{rest}"


@pytest.fixture
def field_user(session) -> dict[str, str]:
    row = User(login_id="site1", name="박현장", role="field", password_hash=hash_password("field-pass"))
    session.add(row)
    session.commit()
    return auth(issue_token(row.id))


# ── 보드 칸(window) ──────────────────────────────────────────────────


def test_history_gives_the_week_columns_from_the_data_date(client, admin, session):
    sid = store(session, _base())
    got = client.get(_url(sid, "/history"), headers=admin).json()
    # Data Date 가 없으면 일정 시작(3/1). 마지막 칸 끝 = 시작 + w 주(포인트 계산의 창 끝과 같다, 그날 시작도 포인트)
    assert got["window"] == {"data_date": "2027-03-01", "weeks": [
        {"start": "2027-03-01", "end": "2027-03-07"},
        {"start": "2027-03-08", "end": "2027-03-14"},
        {"start": "2027-03-15", "end": "2027-03-22"},
    ]}


def test_window_follows_the_data_date_and_the_week_setting(client, admin, session):
    from app.store.tables import Setting

    sid = store(session, replace(_base(), data_date=date(2027, 3, 3)))
    session.add(Setting(key="points_window_weeks", value="2"))
    session.commit()
    got = client.get(_url(sid, "/history"), headers=admin).json()
    assert got["basis"] == {"tf_days": 3, "window_weeks": 2}
    assert got["window"] == {"data_date": "2027-03-03", "weeks": [
        {"start": "2027-03-03", "end": "2027-03-09"}, {"start": "2027-03-10", "end": "2027-03-17"}]}


# ── 바뀜 기록 ────────────────────────────────────────────────────────


def test_history_lists_versions_newest_first_with_what_came_and_went(client, admin, session):
    sid = store(session, _base())
    _save(session, sid, _od(_base(), C=4), 1, note="C 늘림")  # v2: C 여유 4 → 1, 새 포인트
    _save(session, sid, _base(), 2, note="C 되돌림")  # v3: C 여유 1 → 4, 빠짐(여유가 늘어남)
    got = client.get(_url(sid, "/history"), headers=admin).json()
    assert got["schedule_id"] == sid and got["version"] == 3 and got["preview"] is None and got["float"] is None
    v3, v2, v1 = got["versions"]
    assert (v3["version"], v3["note"], v3["recorded"], v3["count"], v3["critical"]) == (3, "C 되돌림", True, 2, 2)
    assert v3["new"] == [] and v3["tightened"] == []
    assert [(r["activity_id"], r["reason"], r["label"], r["before_tf"], r["tf"]) for r in v3["removed"]] == [
        ("C", "relief", "여유가 늘어남", 1, 4)]
    assert [(p["activity_id"], p["name"], p["before_tf"], p["tf"]) for p in v2["new"]] == [("C", "작업 C", 4, 1)]
    assert v2["removed"] == [] and v2["count"] == 3
    assert (v1["version"], v1["recorded"], v1["new"], v1["removed"]) == (1, False, [], [])  # 처음 계산 — 앞이 없다
    assert v1["saved_at"] and v1["count"] == 2


def test_history_float_of_one_activity_by_version(client, admin, session):
    sid = store(session, _base())
    _save(session, sid, _od(_base(), C=4), 1)
    got = client.get(_url(sid, "/history?activity=C"), headers=admin).json()
    # v1 에서 C 는 포인트가 아니었다 — 그 버전 일정을 계산한 여유(4)를 그대로
    assert got["float"] == [{"version": 1, "tf": 4, "critical": False, "point": False},
                            {"version": 2, "tf": 1, "critical": False, "point": True}]
    gone = client.get(_url(sid, "/history?activity=ZZ"), headers=admin).json()["float"]
    assert gone == [{"version": 1, "tf": None, "critical": None, "point": False},
                    {"version": 2, "tf": None, "critical": None, "point": False}]


def test_history_has_the_what_if_preview_while_delays_are_open(client, admin, session):
    sid = store(session, make([task("A", 3), task("B", 2), task("C", 3)], [Relation("A", "B")]))  # C 여유 2
    body = {"activity_id": "C", "start_date": "2027-03-01", "days": 3, "cause": "자재 늦음"}
    assert client.post(f"/api/schedules/{sid}/delays", json=body, headers=admin).status_code == 200
    pv = client.get(_url(sid, "/history"), headers=admin).json()["preview"]
    assert pv["what_if"] is True and pv["version"] == 1 and pv["recorded"] is True
    assert [(p["activity_id"], p["became_critical"], p["tf"]) for p in pv["new"]] == [("C", True, 0)]
    eid = client.get(f"/api/schedules/{sid}/delays", headers=admin).json()["events"][0]["id"]
    assert client.get(_url(sid, "/history"), headers=admin).json()["open_delays"] == 1
    assert client.delete(f"/api/schedules/{sid}/delays/{eid}", headers=admin).status_code in (200, 204)
    got = client.get(_url(sid, "/history"), headers=admin).json()
    assert (got["open_delays"], got["preview"]) == (0, None)  # 열린 지연이 없으면 가정 줄을 내지 않는다(남은 줄이 있어도)


def test_history_of_a_missing_schedule_is_404(client, admin):
    r = client.get(_url(999, "/history"), headers=admin)
    assert (r.status_code, r.json()["code"]) == (404, "not_found")


def test_history_reads_only(client, admin, session):
    sid = store(session, _base())
    _save(session, sid, _od(_base(), C=4), 1)
    before = card.launched[:]
    for _ in range(2):
        assert client.get(_url(sid, "/history?activity=C"), headers=admin).status_code == 200
    assert card.launched == before and load(session, sid)[2] == 2


# ── 당김 효과(읽기) ──────────────────────────────────────────────────


def _named(i: str, od: int):
    return task(i, od, name=f"{i} 작업")


def _side():
    """A 6 → B 4 → D 2 와 나란한 X 9 → D. X 의 여유 1."""
    return make([_named("A", 6), _named("B", 4), _named("X", 9), _named("D", 2)],
                [Relation("A", "B"), Relation("B", "D"), Relation("X", "D")])


async def test_accel_api_gives_the_same_result_as_the_tool(client, admin, session):
    registry.load_all()
    sid = store(session, _side())
    r = client.post(_url(sid, "/B/accel"), json={"days": 3}, headers=admin)
    assert r.status_code == 200
    got = r.json()
    me = session.scalars(select(User).where(User.login_id == "admin")).one()
    ctx = ToolContext(session=session, user=me, schedule_id=sid, emit=lambda e: None)
    tool = await call("points.accel_check", {"activity_id": "B", "days": 3}, ctx)
    assert tool.ok is True and got == tool.output
    assert (got["pulled_days"], got["reached_days"], got["warn"]) == (3, 1, True)
    assert got["warn_line"] == "당긴 3일 중 1일만 준공에 반영됩니다"
    assert [c["activity_id"] for c in got["next_chain"]] == ["X", "D"] and got["next_chain"][0]["point"] is True


def test_accel_api_writes_nothing(client, admin, session):
    sid = store(session, _side())
    versions = load(session, sid)[2]
    before = card.launched[:]
    assert client.post(_url(sid, "/A/accel"), json={"days": 2}, headers=admin).status_code == 200
    session.expire_all()
    assert load(session, sid)[2] == versions and card.launched == before and len(list_records(session)) == 1


def test_accel_api_refusals_and_bad_input(client, admin, session):
    done = replace(_side(), activities=tuple(
        replace(a, actual_start=date(2027, 3, 1)) if a.id == "A" else a for a in _side().activities),
        data_date=date(2027, 3, 2))
    sid = store(session, done)
    r = client.post(_url(sid, "/A/accel"), json={"days": 1}, headers=admin)
    assert (r.status_code, r.json()["code"]) == (409, "has_actuals") and "실적" in r.json()["message"]
    r = client.post(_url(sid, "/NOPE<b>/accel"), json={"days": 1}, headers=admin)
    assert (r.status_code, r.json()["code"]) == (404, "not_found") and "NOPE" not in r.text  # 받은 id 를 되풀이하지 않는다
    assert client.post(_url(sid, f"/{'X' * 65}/accel"), json={"days": 1}, headers=admin).status_code == 422
    one_day = replace(_side(), activities=(*_side().activities, task("M", 1, name="M 작업")))
    r = client.post(_url(store(session, one_day), "/M/accel"), json={"days": 1}, headers=admin)
    assert (r.status_code, r.json()["code"]) == (422, "accel_refused")  # 1일짜리 — 더 줄일 기간 없음
    for bad in ({"days": 0}, {"days": 366}, {"days": 2, "x": 1}, {}):
        assert client.post(_url(sid, "/B/accel"), json=bad, headers=admin).status_code == 422
    r = client.post(_url(999, "/B/accel"), json={"days": 1}, headers=admin)
    assert (r.status_code, r.json()["code"]) == (404, "not_found")


# ── 권한 ─────────────────────────────────────────────────────────────


def test_everyone_signed_in_reads_history_and_accel_but_field_cannot_contact(client, admin, user, field_user, session):
    sid = store(session, _side())
    for who in (admin, user, field_user):
        assert client.get(_url(sid, "/history?activity=B"), headers=who).status_code == 200
        assert client.post(_url(sid, "/B/accel"), json={"days": 1}, headers=who).status_code == 200
    assert client.get(_url(sid, "/history")).status_code == 401
    assert client.post(_url(sid, "/B/accel"), json={"days": 1}).status_code == 401
    r = client.get(_url(sid, "/B/contact"), headers=field_user)
    assert (r.status_code, r.json()["code"]) == (403, "field_no_contacts")
    r = client.post(_url(sid, "/B/contact"), json={"contact_id": 1, "channel": "sms", "preview": True}, headers=field_user)
    assert (r.status_code, r.json()["code"]) == (403, "field_no_contacts")
