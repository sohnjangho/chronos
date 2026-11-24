"""현장 항목의 회신 후보(계획 4 Task 104): GET /api/schedules/{sid}/outreach/replies?field_item_id=.

- 그 현장 항목에 이어진 **받은** 문자만(받은 줄의 field_item_id, 또는 그 항목으로 보낸 우리 요청에 reply_to_id 로 이어진 줄).
  다른 항목·이어지지 않은 답·보낸 줄은 없다. 새것부터.
- 일정과 항목 둘 다로 좁힌다: 다른 일정의 항목·없는 항목·다른 일정 길로 물은 항목은 404(없는 것과 같은 글).
- 글은 hide_phones 를 거친다(응답에 전체 번호 없음). 현장 관리자 403, 로그인 없음 401.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.security.passwords import hash_password
from app.security.tokens import issue_token
from app.store.tables import FieldItem, User
from app.store.tables_outreach import Contact, ContactCompany, OutreachMessage
from tests import schedules
from tests.helpers import auth
from tests.outreach_doubles import SENTINEL_DIGITS, SENTINEL_PHONE

NOW = datetime(2026, 11, 27, 0, 0, tzinfo=UTC)
ITEM_404 = {"code": "not_found", "message": "현장 항목을 찾을 수 없습니다."}
KEYS = {"message_id", "contact", "text", "at", "answers", "request"}


def url(sid: int, item: int) -> str:
    return f"/api/schedules/{sid}/outreach/replies?field_item_id={item}"


@pytest.fixture
def sid2(session) -> int:
    return schedules.store(session, schedules.sample())


@pytest.fixture
def field_user(session) -> dict[str, str]:
    row = User(login_id="site1", name="박현장", role="field", password_hash=hash_password("field-pass"))
    session.add(row)
    session.commit()
    return auth(issue_token(row.id))


def _item(session, sid: int, title: str = "[체크인 요청] A 기초") -> int:
    row = FieldItem(schedule_id=sid, kind="checkin", activity_id="A", activity_name="A", trade="철근", title=title)
    session.add(row)
    session.commit()
    return row.id


def _person(session, sid: int, name: str = "박현장", role_title: str = "공무") -> int:
    company = ContactCompany(schedule_id=sid, name="가람철근", trade="철근")
    session.add(company)
    session.commit()
    who = Contact(schedule_id=sid, company_id=company.id, name=name, role_title=role_title, phone="01000000301")
    session.add(who)
    session.commit()
    return who.id


def _msg(session, sid: int, contact_id: int | None, *, direction: str = "in", minutes: int = 0, **over) -> int:
    values = {"schedule_id": sid, "contact_id": contact_id, "peer_number": "01000000301", "direction": direction,
              "channel": "sms", "origin": "peer" if direction == "in" else "user",
              "status": "received" if direction == "in" else "accepted", "body": "정상 진행 중입니다.",
              "created_at": NOW + timedelta(minutes=minutes), "sent_at": NOW + timedelta(minutes=minutes), **over}
    row = OutreachMessage(**values)
    session.add(row)
    session.commit()
    return row.id


def test_replies_are_scoped_to_project_and_item(client, user, session, sid, sid2):
    mine, other_item, theirs = _item(session, sid), _item(session, sid, "[체크인 요청] B"), _item(session, sid2)
    who = _person(session, sid)
    asked = _msg(session, sid, who, direction="out", field_item_id=mine, body="체크인 부탁드립니다")
    direct = _msg(session, sid, who, minutes=5, field_item_id=mine, reply_to_id=asked, body="정상 진행 중입니다. 오후에 철근 반입 예정.")
    chained = _msg(session, sid, who, minutes=9, reply_to_id=asked, body="인원 6명입니다")  # 항목 칸은 없고 요청에만 이어짐
    _msg(session, sid, who, minutes=7, field_item_id=other_item, body="다른 항목의 답")
    _msg(session, sid, who, minutes=8, body="이어지지 않은 답")
    _msg(session, sid2, _person(session, sid2), minutes=6, field_item_id=theirs, body="다른 프로젝트의 답")
    _msg(session, sid, who, direction="out", minutes=10, field_item_id=mine, body="우리가 보낸 두 번째 글")

    got = client.get(url(sid, mine), headers=user)

    assert got.status_code == 200, got.text
    rows = got.json()
    assert [r["message_id"] for r in rows] == [chained, direct]  # 새것부터, 받은 줄만
    assert set(rows[1]) == KEYS
    assert rows[1]["contact"] == {"name": "박현장", "role_title": "공무"}
    assert rows[1]["text"] == "정상 진행 중입니다. 오후에 철근 반입 예정."
    assert rows[1]["answers"] == []
    assert rows[1]["at"].startswith("2026-11-27T00:05")
    # 어느 요청의 답인지: reply_to_id 로 이어진 우리 줄(id·보낸 때·묶음)
    assert rows[1]["request"]["message_id"] == asked
    assert rows[1]["request"]["at"].startswith("2026-11-27T00:00")
    assert rows[1]["request"]["batch_id"] is None

    # 다른 일정의 항목을 이 일정 길로 · 이 일정의 항목을 다른 일정 길로 · 없는 항목 → 모두 같은 404
    for sid_, item in ((sid, theirs), (sid2, mine), (sid, 99999)):
        res = client.get(url(sid_, item), headers=user)
        assert res.status_code == 404, (sid_, item)
        assert {k: res.json()[k] for k in ("code", "message")} == ITEM_404


def test_reply_text_hides_phone_numbers(client, user, session, sid):
    item = _item(session, sid)
    who = _person(session, sid)
    _msg(session, sid, who, field_item_id=item, body=f"제 번호는 {SENTINEL_PHONE} 이고 {SENTINEL_DIGITS} 로도 됩니다")

    got = client.get(url(sid, item), headers=user)

    assert got.status_code == 200
    for bad in (SENTINEL_PHONE, SENTINEL_DIGITS, "0000-0199", "00000199"):
        assert bad not in got.text, bad


def test_reply_from_a_deleted_contact_still_shows_without_a_number(client, user, session, sid):
    item = _item(session, sid)
    _msg(session, sid, None, field_item_id=item, body="누구인지 모르는 답")

    got = client.get(url(sid, item), headers=user).json()

    assert got[0]["contact"] == {"name": "지워진 연락처", "role_title": ""}
    assert "01000000301" not in str(got)


def test_no_replies_is_an_empty_list(client, user, session, sid):
    assert client.get(url(sid, _item(session, sid)), headers=user).json() == []


def test_field_manager_is_403_and_no_login_is_401(client, field_user, session, sid):
    item = _item(session, sid)
    assert client.get(url(sid, item), headers=field_user).status_code == 403
    assert client.get(url(sid, item)).status_code == 401


def test_field_item_id_is_required(client, user, sid):
    assert client.get(f"/api/schedules/{sid}/outreach/replies", headers=user).status_code == 422


def test_request_of_a_reply_is_only_from_this_project(client, user, session, sid, sid2):
    """reply_to_id 가 다른 일정의 줄을 가리키면(있을 수 없는 자료라도) 그 요청은 보이지 않는다. 묶음이면 batch_id."""
    item = _item(session, sid)
    who = _person(session, sid)
    theirs = _msg(session, sid2, None, direction="out", body="다른 일정의 요청")
    batch = _msg(session, sid, who, direction="out", minutes=1, field_item_id=item, body="묶음 요청")
    session.get(OutreachMessage, batch).batch_id = batch
    session.commit()
    _msg(session, sid, who, minutes=3, field_item_id=item, reply_to_id=theirs, body="엉뚱한 연결")
    _msg(session, sid, who, minutes=4, field_item_id=item, reply_to_id=batch, body="묶음의 답")
    _msg(session, sid, who, minutes=5, field_item_id=item, body="요청 없이 이어진 답")

    rows = client.get(url(sid, item), headers=user).json()

    assert [r["text"] for r in rows] == ["요청 없이 이어진 답", "묶음의 답", "엉뚱한 연결"]
    assert rows[0]["request"] is None
    assert rows[1]["request"]["message_id"] == batch and rows[1]["request"]["batch_id"] == batch
    assert rows[2]["request"] is None
