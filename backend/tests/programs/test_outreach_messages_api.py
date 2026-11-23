"""메시지 API(계획 4 Task 73): 대화 읽기 · 초안 쓰기 · 보내기·예약 · 취소 · 다시 보내기.

보내기는 모두 나가는 문(gate.dispatch)을 지난다 — 이 API 는 통로를 부르지 않는다. 결과 셋(접수·실패·확인 필요)은 늘 200 이고
판정 코드·글은 문이 준 그대로. 격리: 다른 일정의 줄·연락처는 없는 것과 같은 404 이고 그때 문을 부르지 않는다.
번호는 응답·오류·로그 어디에도 없다(연락처는 가린 꼴). 시각은 service._now 를 고정해 근무시간 안·밖을 정한다.
"""

import json
import logging
import unicodedata
from datetime import datetime

import pytest
from sqlalchemy import func, select

from app.outreach import hours
from app.outreach.harness import events, gate
from app.outreach.harness.types import Delivered, Outcome, Ref
from app.programs.outreach import service
from app.security.passwords import hash_password
from app.security.tokens import issue_token
from app.store import outreach
from app.store.tables import ChatSession, FieldItem, User
from app.store.tables_outreach import (
    Contact,
    ContactCompany,
    NotifyConnection,
    OutreachCall,
    OutreachMessage,
)
from tests import schedules
from tests.helpers import auth
from tests.outreach_doubles import SENTINEL_DIGITS, SENTINEL_PHONE, assert_clean

KST = hours.KST
WORK = datetime(2026, 11, 27, 10, 0, tzinfo=KST)  # 금요일 10시 — 근무 중
OFF = datetime(2026, 11, 27, 19, 0, tzinfo=KST)  # 금요일 19시 — 근무 밖
MONDAY = datetime(2026, 11, 30, 8, 0, tzinfo=KST)  # 그 뒤 첫 근무 시작
BODY = "내일 3층 타설 가능하신가요?"
USER_NAME = "일반 사용자"  # conftest 의 user1
FIELD_NO = ("field_no_contacts", "현장 관리자는 연락처를 열 수 없습니다.")
PERSON_404 = ("not_found", "연락처를 찾을 수 없습니다.")
MESSAGE_404 = ("not_found", "메시지를 찾을 수 없습니다.")
NOT_DRAFT = ("not_draft", "초안만 고치거나 지울 수 있습니다.")
MESSAGE_KEYS = {"id", "direction", "channel", "kind", "body", "body_ko", "has_media", "origin", "origin_name", "send_mode",
                "approved_by", "status", "fail_reason", "fallback_sms", "template_id", "reply_to_id", "activity",
                "field_item_id", "approval_id", "chat", "batch", "events", "scheduled_at", "sent_at", "delivered_at",
                "created_at"}
BRIEF_KEYS = {"id", "name", "role_title", "company_id", "phone_masked", "has_phone", "phone_kind", "channels", "unread",
              "do_not_contact", "phone_invalid", "last_line", "hidden"}


@pytest.fixture(autouse=True)
def at_work(monkeypatch):
    monkeypatch.setattr(service, "_now", lambda: WORK)


@pytest.fixture
def field_user(session) -> dict[str, str]:
    row = User(login_id="site1", name="박현장", role="field", password_hash=hash_password("field-pass"))
    session.add(row)
    session.commit()
    return auth(issue_token(row.id))


@pytest.fixture
def sid2(session) -> int:
    return schedules.store(session, schedules.sample())


@pytest.fixture
def conn(session) -> NotifyConnection:
    """기본 알림 연결: 상태 ok, 시험 모드 끔, 모두 「승인 받기」."""
    row = NotifyConnection(name="시험 연결", base_url="https://kat.invalid", secret_ciphertext="x", secret_last4="9999",
                           account_id="acct-test", sender_number="07000000000", is_default=True, status="ok",
                           test_mode=False)
    session.add(row)
    session.commit()
    return row


def _person(session, sid: int, phone: str | None = SENTINEL_DIGITS, **over) -> int:
    company = ContactCompany(schedule_id=sid, name="가람철근", trade="철근")
    session.add(company)
    session.flush()
    who = Contact(**{"schedule_id": sid, "company_id": company.id, "name": "김공정", "role_title": "공무",
                     "phone": phone, **over})
    session.add(who)
    session.commit()
    return who.id


def _row(session, sid: int, contact_id: int, **over) -> OutreachMessage:
    values = {"schedule_id": sid, "contact_id": contact_id, "direction": "out", "channel": "sms", "origin": "user",
              "origin_name": USER_NAME, "body": BODY, **over}
    row = OutreachMessage(**values)
    session.add(row)
    session.commit()
    return row


def _url(sid: int, rest: str = "") -> str:
    return f"/api/schedules/{sid}/outreach{rest}"


def _create(client, headers, sid, contact_id, **kw):
    return client.post(_url(sid, "/messages"), json={"contact_id": contact_id, "channel": "sms", "body": BODY, **kw},
                       headers=headers)


def _reread(session, row_id: int) -> OutreachMessage:
    session.expire_all()
    return session.get(OutreachMessage, row_id)


def _count(session) -> int:
    session.expire_all()
    return session.scalar(select(func.count()).select_from(OutreachMessage))


# ── 보내기는 문을 지난다 ────────────────────────────────────────────────────


def test_send_goes_through_gate_and_returns_outcome(client, user, session, sid, conn, fake_channel):
    pid = _person(session, sid)

    r = _create(client, user, sid, pid, send=True)

    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["outcome"] == {"code": "accepted", "message": body["outcome"]["message"], "scheduled_at": None}
    message = body["message"]
    assert set(message) == MESSAGE_KEYS
    assert (message["status"], message["origin"], message["origin_name"]) == ("accepted", "user", USER_NAME)
    assert (message["send_mode"], message["approved_by"], message["kind"]) == ("manual", None, "normal")
    assert message["sent_at"] is not None and message["body"] == BODY
    assert [e["rule"] for e in message["events"]] == ["channel_choice", "delivery"]
    assert set(message["events"][0]) == {"rule", "verdict", "detail"}
    assert [(d.channel, d.row_id) for d in fake_channel.delivered] == [("sms", message["id"])]
    row = _reread(session, message["id"])
    assert row.idempotency_key and row.status == "accepted"


def test_draft_is_saved_without_sending_and_sent_later(client, user, session, sid, conn, fake_channel):
    pid = _person(session, sid)

    r = _create(client, user, sid, pid)

    assert r.status_code == 200, r.json()
    assert r.json()["outcome"] is None
    draft = r.json()["message"]
    assert (draft["status"], draft["events"], fake_channel.delivered) == ("draft", [], [])

    sent = client.post(_url(sid, f"/messages/{draft['id']}/send"), headers=user)

    assert sent.status_code == 200, sent.json()
    assert (sent.json()["outcome"]["code"], sent.json()["message"]["status"]) == ("accepted", "accepted")
    assert len(fake_channel.delivered) == 1


def test_each_draft_gets_its_own_idempotency_key(client, user, session, sid, conn):
    pid = _person(session, sid)
    ids = [_create(client, user, sid, pid).json()["message"]["id"] for _ in range(2)]

    keys = {_reread(session, i).idempotency_key for i in ids}

    assert len(keys) == 2


def test_blocked_send_is_200_with_reason(client, user, session, sid, conn, fake_channel):
    conn.test_mode = True
    session.commit()
    pid = _person(session, sid)

    r = _create(client, user, sid, pid, send=True)

    assert r.status_code == 200, r.json()
    assert r.json()["outcome"] == {"code": "blocked_test", "message": "시험 모드라 허용한 번호에만 연락합니다",
                                   "scheduled_at": None}
    assert r.json()["message"]["status"] == "blocked_test"
    assert fake_channel.delivered == []


def test_do_not_contact_send_is_200_and_row_stays_a_draft_with_reason(client, user, session, sid, conn, fake_channel):
    pid = _person(session, sid, do_not_contact=True)

    r = _create(client, user, sid, pid, send=True)

    assert r.status_code == 200
    assert r.json()["outcome"]["code"] == "do_not_contact"
    assert (r.json()["message"]["status"], r.json()["message"]["fail_reason"]) == ("draft", "수신 거부한 번호입니다")
    assert fake_channel.delivered == []


def test_off_hours_send_is_scheduled_and_cancel_returns_it_to_a_draft(client, user, session, sid, conn, fake_channel,
                                                                      monkeypatch):
    monkeypatch.setattr(service, "_now", lambda: OFF)
    pid = _person(session, sid)

    r = _create(client, user, sid, pid, send=True)

    outcome, message = r.json()["outcome"], r.json()["message"]
    assert outcome["code"] == "scheduled"
    assert datetime.fromisoformat(outcome["scheduled_at"]) == MONDAY
    assert message["status"] == "scheduled" and datetime.fromisoformat(message["scheduled_at"]) == MONDAY
    assert fake_channel.delivered == []

    cancelled = client.post(_url(sid, f"/messages/{message['id']}/cancel"), headers=user)

    assert cancelled.status_code == 200, cancelled.json()
    assert (cancelled.json()["status"], cancelled.json()["scheduled_at"]) == ("draft", None)
    again = client.post(_url(sid, f"/messages/{message['id']}/cancel"), headers=user)
    assert again.status_code == 409
    assert (again.json()["code"], again.json()["message"]) == ("not_scheduled", "예약된 메시지가 아닙니다.")
    monkeypatch.setattr(service, "_now", lambda: WORK)  # 취소한 초안은 다시 누르면 처음부터 문을 지난다
    sent = client.post(_url(sid, f"/messages/{message['id']}/send"), headers=user)
    assert (sent.json()["outcome"]["code"], sent.json()["message"]["send_mode"]) == ("accepted", "manual")
    assert len(fake_channel.delivered) == 1


def test_send_twice_delivers_once(client, user, session, sid, conn, fake_channel):
    pid = _person(session, sid)
    first = _create(client, user, sid, pid, send=True).json()["message"]

    again = client.post(_url(sid, f"/messages/{first['id']}/send"), headers=user)

    assert again.status_code == 409
    assert again.json()["code"] == "not_sendable"
    # 같은 글을 새 줄로 두 번 눌러도 두 번째는 문이 막는다(같은 번호·같은 채널·같은 글)
    twin = _create(client, user, sid, pid, send=True)
    assert twin.status_code == 200
    assert twin.json()["outcome"]["code"] == "duplicate"
    assert twin.json()["message"]["status"] == "draft"
    assert len(fake_channel.delivered) == 1


def test_busy_row_is_passed_through_as_try_again_not_already_sent(client, user, session, sid, conn, fake_channel):
    pid = _person(session, sid)
    row = _row(session, sid, pid, status="sending")

    r = client.post(_url(sid, f"/messages/{row.id}/send"), headers=user)

    assert r.status_code == 200
    assert r.json()["outcome"] == {"code": "duplicate", "message": gate.BUSY, "scheduled_at": None}
    assert fake_channel.delivered == []


def test_unsure_send_shows_needs_check_and_is_not_resent(client, user, session, sid, conn, fake_channel):
    pid = _person(session, sid)
    fake_channel.result = Delivered("unsure")

    r = _create(client, user, sid, pid, send=True)

    assert r.status_code == 200
    assert r.json()["outcome"] == {"code": "unsure", "message": "보냈는지 확인 필요", "scheduled_at": None}
    message = r.json()["message"]
    assert message["status"] == "unconfirmed"
    fake_channel.result = None
    again = client.post(_url(sid, f"/messages/{message['id']}/send"), headers=user)
    assert again.status_code == 409
    assert again.json() == {"code": "not_sendable", "message": "이미 처리된 메시지입니다. 다시 보내려면 [다시 보내기]를 눌러 주세요.",
                            "detail": None}
    assert len(fake_channel.delivered) == 1
    assert _reread(session, message["id"]).status == "unconfirmed"


def test_failed_send_returns_the_gates_fixed_reason(client, user, session, sid, conn, fake_channel):
    pid = _person(session, sid)
    fake_channel.result = Delivered("failed", fail_code="network", fail_text=f"socket {SENTINEL_PHONE}")

    r = _create(client, user, sid, pid, send=True)

    assert r.json()["outcome"] == {"code": "failed", "message": gate.FAIL_TEXT["network"], "scheduled_at": None}
    assert (r.json()["message"]["status"], r.json()["message"]["fail_reason"]) == ("failed", gate.FAIL_TEXT["network"])
    assert SENTINEL_DIGITS not in r.text and "socket" not in r.text


# ── 다시 보내기는 새 줄 ──────────────────────────────────────────────────


def test_resend_makes_a_new_draft_row_and_keeps_the_old_one(client, user, session, sid, conn, fake_channel):
    pid = _person(session, sid)
    fake_channel.result = Delivered("failed", fail_code="server")
    failed = _create(client, user, sid, pid, send=True, activity_id="A").json()["message"]
    fake_channel.result = None

    r = client.post(_url(sid, f"/messages/{failed['id']}/resend"), headers=user)

    assert r.status_code == 200, r.json()
    assert r.json()["warning"] is None
    new = r.json()["message"]
    assert new["id"] != failed["id"]
    assert (new["status"], new["body"], new["channel"], new["origin"], new["kind"]) == ("draft", BODY, "sms", "user",
                                                                                        "normal")
    assert new["activity"]["id"] == "A"
    assert _reread(session, new["id"]).contact_id == pid
    assert _reread(session, failed["id"]).status == "failed"
    sent = client.post(_url(sid, f"/messages/{new['id']}/send"), headers=user)
    assert sent.json()["outcome"]["code"] == "accepted"  # 실패한 줄은 「같은 글」로 막지 않는다
    assert [d.row_id for d in fake_channel.delivered] == [failed["id"], new["id"]]


def test_resend_of_unconfirmed_warns_and_the_gate_refuses_it_inside_the_window(client, user, session, sid, conn,
                                                                               fake_channel):
    pid = _person(session, sid)
    fake_channel.result = Delivered("unsure")
    unsure = _create(client, user, sid, pid, send=True).json()["message"]
    fake_channel.result = None

    r = client.post(_url(sid, f"/messages/{unsure['id']}/resend"), headers=user)

    assert r.status_code == 200
    assert r.json()["warning"] == "이미 나갔을 수 있습니다"
    new = r.json()["message"]
    assert (new["status"], new["body"]) == ("draft", BODY)
    sent = client.post(_url(sid, f"/messages/{new['id']}/send"), headers=user)
    assert sent.status_code == 200
    assert sent.json()["outcome"] == {"code": "duplicate", "message": "같은 글이 방금 나갔거나 나가는 중입니다",
                                      "scheduled_at": None}
    assert _reread(session, unsure["id"]).status == "unconfirmed"
    assert len(fake_channel.delivered) == 1


@pytest.mark.parametrize("status", ["draft", "scheduled", "accepted", "delivered", "blocked_test", "received"])
def test_only_failed_or_unconfirmed_rows_can_be_resent(client, user, session, sid, status):
    pid = _person(session, sid)
    row = _row(session, sid, pid, status=status)
    before = _count(session)

    r = client.post(_url(sid, f"/messages/{row.id}/resend"), headers=user)

    assert r.status_code == 409
    assert (r.json()["code"], r.json()["message"]) == (
        "not_resendable", "실패했거나 확인이 필요한 메시지만 다시 보낼 수 있습니다.")
    assert _count(session) == before


# ── 초안만 고치고 지운다 ─────────────────────────────────────────────────


def test_only_drafts_can_be_edited_or_deleted(client, user, session, sid, conn):
    pid = _person(session, sid)
    draft = _row(session, sid, pid)

    patched = client.patch(_url(sid, f"/messages/{draft.id}"), json={"body": "고친 글\n둘째 줄", "channel": "kakao",
                                                                       "activity_id": "B"}, headers=user)

    assert patched.status_code == 200, patched.json()
    assert (patched.json()["body"], patched.json()["channel"], patched.json()["activity"]["id"]) == (
        "고친 글\n둘째 줄", "kakao", "B")
    cleared = client.patch(_url(sid, f"/messages/{draft.id}"), json={"activity_id": None}, headers=user)
    assert cleared.json()["activity"] is None
    assert client.delete(_url(sid, f"/messages/{draft.id}"), headers=user).status_code == 204
    assert _reread(session, draft.id) is None

    for status in ("scheduled", "sending", "accepted", "failed", "unconfirmed", "received"):
        row = _row(session, sid, pid, status=status, body=f"{status} 글")
        edit = client.patch(_url(sid, f"/messages/{row.id}"), json={"body": "바꿈"}, headers=user)
        gone = client.delete(_url(sid, f"/messages/{row.id}"), headers=user)
        assert (edit.status_code, gone.status_code) == (409, 409), status
        assert (edit.json()["code"], edit.json()["message"]) == NOT_DRAFT
        assert (gone.json()["code"], gone.json()["message"]) == NOT_DRAFT
        kept = _reread(session, row.id)
        assert (kept.status, kept.body) == (status, f"{status} 글")


def test_patch_cannot_null_body_or_channel_and_refuses_unknown_fields(client, user, session, sid):
    pid = _person(session, sid)
    draft = _row(session, sid, pid)

    for payload in ({"body": None}, {"channel": None}, {"status": "accepted"}, {"origin": "agent"}):
        r = client.patch(_url(sid, f"/messages/{draft.id}"), json=payload, headers=user)
        assert r.status_code == 422, payload
    kept = _reread(session, draft.id)
    assert (kept.body, kept.status, kept.origin) == (BODY, "draft", "user")


# ── 본문 검사 ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("body", ["", "   ", "가" * 1001])
def test_body_must_be_1_to_1000_characters(client, user, session, sid, body):
    pid = _person(session, sid)

    r = _create(client, user, sid, pid, body=body)

    assert r.status_code == 422
    assert _count(session) == 0


def test_body_of_1000_characters_and_newlines_and_tabs_are_kept(client, user, session, sid):
    pid = _person(session, sid)

    long = _create(client, user, sid, pid, body="가" * 1000)
    lines = _create(client, user, sid, pid, body="첫 줄\n\t둘째 줄")

    assert long.status_code == 200 and len(long.json()["message"]["body"]) == 1000
    assert lines.json()["message"]["body"] == "첫 줄\n\t둘째 줄"


@pytest.mark.parametrize("bad", ["\x00", "\r", "\x1b", "\u202e", "\u2066", "\u200f", "\u2028", "\u200b"])
def test_body_rejects_hidden_control_characters_without_echo(client, user, session, sid, bad):
    pid = _person(session, sid)
    draft = _row(session, sid, pid)
    text = f"비밀글QZ9 {bad}{SENTINEL_PHONE} 끝"

    created = _create(client, user, sid, pid, body=text)
    patched = client.patch(_url(sid, f"/messages/{draft.id}"), json={"body": text}, headers=user)

    for r in (created, patched):
        assert r.status_code == 422
        assert (r.json()["code"], r.json()["message"]) == (
            "invalid_text", "문자 글에는 보이지 않는 제어 글자나 글 방향을 바꾸는 글자를 쓸 수 없습니다.")
        assert "QZ9" not in r.text and SENTINEL_DIGITS not in r.text and "0000-0199" not in r.text
    assert _count(session) == 1 and _reread(session, draft.id).body == BODY


def test_too_long_body_error_does_not_echo_it(client, user, session, sid):
    pid = _person(session, sid)

    r = _create(client, user, sid, pid, body="QZ9" + SENTINEL_PHONE + "가" * 1000)

    assert r.status_code == 422
    assert "QZ9" not in r.text and SENTINEL_DIGITS not in r.text and "0000-0199" not in r.text


def test_body_is_stored_as_nfc(client, user, session, sid):
    pid = _person(session, sid)

    r = _create(client, user, sid, pid, body=unicodedata.normalize("NFD", "타설 가능"))

    assert r.json()["message"]["body"] == "타설 가능"
    assert len(r.json()["message"]["body"]) == 5


def test_kakao_is_accepted_and_the_gate_sends_it_as_sms(client, user, session, sid, conn, fake_channel):
    pid = _person(session, sid)

    r = _create(client, user, sid, pid, channel="kakao", send=True)

    assert r.json()["outcome"]["code"] == "accepted"
    message = r.json()["message"]
    assert (message["channel"], message["fallback_sms"]) == ("sms", True)
    assert [d.channel for d in fake_channel.delivered] == ["sms"]


def test_unknown_channel_is_422(client, user, session, sid):
    pid = _person(session, sid)

    for channel in ("call", "mms", ""):
        assert _create(client, user, sid, pid, channel=channel).status_code == 422
    assert _count(session) == 0


# ── 격리 ─────────────────────────────────────────────────────────────────


def test_thread_is_project_scoped(client, user, session, sid, sid2):
    mine = _person(session, sid)
    theirs = _person(session, sid2)
    kept = _row(session, sid, mine, body="내 일정의 글")
    _row(session, sid2, theirs, body="다른 일정의 글")
    _row(session, sid2, mine, body="잘못 적힌 다른 일정 줄")  # 같은 연락처 id 라도 다른 일정의 줄은 보이지 않는다

    r = client.get(_url(sid, f"/threads/{mine}"), headers=user)

    assert r.status_code == 200, r.json()
    assert [m["id"] for m in r.json()["messages"]] == [kept.id]
    other = client.get(_url(sid, f"/threads/{theirs}"), headers=user)
    missing = client.get(_url(sid, "/threads/99999"), headers=user)
    assert (other.status_code, missing.status_code) == (404, 404)
    assert (other.json()["code"], other.json()["message"]) == PERSON_404
    assert other.json() == missing.json()


def test_thread_shape_and_paging(client, user, session, sid):
    pid = _person(session, sid)
    rows = [_row(session, sid, pid, body=f"글 {n}") for n in range(5)]
    inbound = _row(session, sid, pid, direction="in", origin="peer", origin_name="", status="received", body="답")

    first = client.get(_url(sid, f"/threads/{pid}?limit=3"), headers=user).json()

    assert set(first) == {"contact", "messages", "has_more"}
    assert set(first["contact"]) == BRIEF_KEYS
    assert (first["contact"]["phone_masked"], first["contact"]["unread"], first["contact"]["last_line"]) == (
        "010-****-0199", 1, "답")
    assert [m["id"] for m in first["messages"]] == [rows[3].id, rows[4].id, inbound.id]
    assert first["has_more"] is True
    older = client.get(_url(sid, f"/threads/{pid}?limit=3&before={rows[3].id}"), headers=user).json()
    assert [m["id"] for m in older["messages"]] == [rows[0].id, rows[1].id, rows[2].id]
    assert older["has_more"] is False
    outreach.mark_do_not_contact(session, SENTINEL_DIGITS, reason="다른 프로젝트에서 거부")
    session.commit()
    refused = client.get(_url(sid, f"/threads/{pid}"), headers=user).json()["contact"]
    assert refused["do_not_contact"] is True  # 번호 기준 수신 거부도(주소록 API 와 같은 값)
    for bad in ("limit=0", "limit=101", "before=0"):
        assert client.get(_url(sid, f"/threads/{pid}?{bad}"), headers=user).status_code == 422


def test_send_of_other_project_message_is_404_and_gate_is_not_called(client, user, session, sid, sid2, conn,
                                                                     monkeypatch):
    theirs = _person(session, sid2)
    row = _row(session, sid2, theirs)
    scheduled = _row(session, sid2, theirs, status="scheduled", body="예약 글")
    failed = _row(session, sid2, theirs, status="failed", body="실패 글")
    calls = []

    async def spy(*args, **kwargs):
        calls.append(args)
        return Outcome("accepted", "보냄")

    monkeypatch.setattr(gate, "dispatch", spy)
    before = _count(session)

    responses = [
        client.post(_url(sid, f"/messages/{row.id}/send"), headers=user),
        client.patch(_url(sid, f"/messages/{row.id}"), json={"body": "바꿈"}, headers=user),
        client.delete(_url(sid, f"/messages/{row.id}"), headers=user),
        client.post(_url(sid, f"/messages/{scheduled.id}/cancel"), headers=user),
        client.post(_url(sid, f"/messages/{failed.id}/resend"), headers=user),
        client.post(_url(sid, "/messages/99999/send"), headers=user),
    ]

    assert [r.status_code for r in responses] == [404] * 6
    assert all((r.json()["code"], r.json()["message"]) == MESSAGE_404 for r in responses)
    assert calls == []
    assert _count(session) == before
    assert [_reread(session, r.id).status for r in (row, scheduled, failed)] == ["draft", "scheduled", "failed"]
    assert _reread(session, row.id).body == BODY


def test_creating_for_another_projects_contact_is_404_and_nothing_is_made(client, user, session, sid, sid2, monkeypatch):
    theirs = _person(session, sid2)
    calls = []

    async def spy(*args, **kwargs):
        calls.append(args)
        return Outcome("accepted", "보냄")

    monkeypatch.setattr(gate, "dispatch", spy)

    r = _create(client, user, sid, theirs, send=True)

    assert r.status_code == 404
    assert (r.json()["code"], r.json()["message"]) == PERSON_404
    assert (calls, _count(session)) == ([], 0)


def test_links_must_belong_to_the_schedule(client, user, session, sid, sid2):
    pid = _person(session, sid)
    theirs = FieldItem(schedule_id=sid2, kind="checkin", activity_id="A", activity_name="A", trade="철근", title="체크인")
    session.add(theirs)
    session.commit()

    cases = [({"activity_id": "없는작업"}, "작업을 찾을 수 없습니다."),
             ({"field_item_id": theirs.id}, "현장 항목을 찾을 수 없습니다."),
             ({"approval_id": 99999}, "승인 건을 찾을 수 없습니다."),
             ({"template_id": 99999}, "알림톡 문안을 찾을 수 없습니다.")]
    for extra, message in cases:
        r = _create(client, user, sid, pid, **extra)
        assert r.status_code == 404, extra
        assert (r.json()["code"], r.json()["message"]) == ("not_found", message)
    assert _count(session) == 0


def test_deleting_a_schedule_purges_its_outreach_rows(client, admin, session, sid, sid2):
    pid = _person(session, sid)
    other = _person(session, sid2)
    _row(session, sid, pid)
    kept = _row(session, sid2, other)
    session.add(OutreachCall(schedule_id=sid, contact_id=pid, direction="out", origin="user"))
    session.commit()

    r = client.delete(f"/api/schedules/{sid}", headers=admin)

    assert r.status_code == 200
    session.expire_all()
    assert session.scalars(select(OutreachMessage.id)).all() == [kept.id]
    assert session.scalar(select(func.count()).select_from(OutreachCall)) == 0
    assert session.get(Contact, pid) is None


# ── 에이전트 초안을 사람이 보냄 ──────────────────────────────────────────


def test_agent_draft_sent_by_user_shows_approver(client, user, session, sid, conn, fake_channel):
    pid = _person(session, sid)
    draft = _row(session, sid, pid, origin="agent", origin_name="에이전트", kind="auto_reply", body="자동 답 초안")

    r = client.post(_url(sid, f"/messages/{draft.id}/send"), headers=user)

    assert r.status_code == 200
    assert r.json()["outcome"]["code"] == "accepted"
    message = r.json()["message"]
    assert (message["origin"], message["origin_name"]) == ("agent", "에이전트")
    assert (message["send_mode"], message["approved_by"], message["kind"]) == ("approved", USER_NAME, "normal")
    assert len(fake_channel.delivered) == 1


def test_editing_an_agent_draft_makes_it_a_normal_message_and_keeps_its_origin(client, user, session, sid):
    pid = _person(session, sid)
    draft = _row(session, sid, pid, origin="agent", origin_name="에이전트", kind="notice", body="안내 초안")

    r = client.patch(_url(sid, f"/messages/{draft.id}"), json={"body": "사람이 고친 글"}, headers=user)

    assert r.status_code == 200
    assert (r.json()["kind"], r.json()["origin"], r.json()["origin_name"], r.json()["approved_by"]) == (
        "normal", "agent", "에이전트", None)


# ── 번호가 새지 않는다 ────────────────────────────────────────────────────


def test_events_are_listed_without_numbers(client, user, session, sid, conn, fake_channel, caplog):
    caplog.set_level(logging.DEBUG)
    pid = _person(session, sid)
    conn.test_mode = True
    session.commit()
    sent = _create(client, user, sid, pid, send=True).json()["message"]
    events.record(session, Ref("message", sent["id"]), "delivery", "noted", f"전화 {SENTINEL_PHONE} 로 확인 요청")
    session.commit()
    _row(session, sid, pid, direction="in", origin="peer", origin_name="", status="received",
         body=f"제 번호는 {SENTINEL_PHONE} 입니다", body_ko=f"번호 {SENTINEL_DIGITS}")

    r = client.get(_url(sid, f"/threads/{pid}"), headers=user)

    assert r.status_code == 200
    messages = r.json()["messages"]
    assert [e["rule"] for e in messages[0]["events"]] == ["test_mode", "delivery"]
    assert messages[0]["events"][0] == {"rule": "test_mode", "verdict": "blocked",
                                        "detail": "시험 모드라 허용한 번호에만 연락합니다"}
    assert messages[1]["body"] == "제 번호는 [번호] 입니다"
    dumped = json.dumps(r.json(), ensure_ascii=False)
    assert SENTINEL_DIGITS not in dumped.replace("-", "") and SENTINEL_PHONE not in dumped
    assert "0199" in dumped  # 가린 꼴(010-****-0199)은 있다
    assert_clean(caplog)


def test_person_written_body_is_returned_as_written(client, user, session, sid):
    pid = _person(session, sid)

    r = _create(client, user, sid, pid, body="현장 사무실 번호는 02-2000-0199 입니다")

    assert r.json()["message"]["body"] == "현장 사무실 번호는 02-2000-0199 입니다"


def test_chat_title_is_shown_only_to_its_owner(client, user, admin, session, sid):
    pid = _person(session, sid)
    owner = session.scalars(select(User).where(User.login_id == "user1")).one()
    chat = ChatSession(user_id=owner.id, title="타설 일정 묻기", schedule_id=sid)
    session.add(chat)
    session.commit()
    _row(session, sid, pid, origin="agent", origin_name="에이전트", chat_session_id=chat.id)

    mine = client.get(_url(sid, f"/threads/{pid}"), headers=user).json()["messages"][0]["chat"]
    theirs = client.get(_url(sid, f"/threads/{pid}"), headers=admin).json()["messages"][0]["chat"]

    assert mine == {"id": chat.id, "title": "타설 일정 묻기"}
    assert theirs == {"id": chat.id, "title": ""}


def test_batch_counts_people_who_replied(client, user, session, sid):
    a, b = _person(session, sid), _person(session, sid)
    first = _row(session, sid, a, batch_id=7, status="accepted")
    _row(session, sid, b, batch_id=7, status="accepted", body="둘째")
    _row(session, sid, a, direction="in", origin="peer", origin_name="", status="received", body="네",
         reply_to_id=first.id, batch_id=7)

    messages = client.get(_url(sid, f"/threads/{a}"), headers=user).json()["messages"]

    assert messages[0]["batch"] == {"id": 7, "total": 2, "replied": 1}


# ── 역할 ─────────────────────────────────────────────────────────────────


def test_field_role_403(client, field_user, session, sid):
    pid = _person(session, sid)
    row = _row(session, sid, pid)
    requests = [
        client.get(_url(sid, f"/threads/{pid}"), headers=field_user),
        _create(client, field_user, sid, pid, send=True),
        client.patch(_url(sid, f"/messages/{row.id}"), json={"body": "바꿈"}, headers=field_user),
        client.delete(_url(sid, f"/messages/{row.id}"), headers=field_user),
        client.post(_url(sid, f"/messages/{row.id}/send"), headers=field_user),
        client.post(_url(sid, f"/messages/{row.id}/cancel"), headers=field_user),
        client.post(_url(sid, f"/messages/{row.id}/resend"), headers=field_user),
        client.post(_url(sid, "/messages/99999/send"), headers=field_user),
    ]

    assert [r.status_code for r in requests] == [403] * 8
    assert all((r.json()["code"], r.json()["message"]) == FIELD_NO for r in requests)
    assert _count(session) == 1 and _reread(session, row.id).body == BODY


def test_needs_login(client, sid):
    assert client.get(_url(sid, "/threads/1")).status_code == 401
    assert client.post(_url(sid, "/messages/1/send")).status_code == 401
