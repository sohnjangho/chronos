"""하네스 사건 기록(Task 64): 메시지와 통화가 같은 꼴 {rule, verdict, detail, evidence, at} 으로 그 줄의 harness_json 에 남는다.

번호는 모두 가상이다(이름표의 SENTINEL_PHONE).
"""

import json
import re
from datetime import datetime

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.outreach.harness import events
from app.outreach.harness.types import Ref
from app.store.outreach import NotFound
from app.store.tables_outreach import OutreachCall, OutreachMessage
from tests.outreach_doubles import SENTINEL_DIGITS, SENTINEL_PHONE

KEYS = {"rule", "verdict", "detail", "evidence", "at"}


def _message(session: Session) -> Ref:
    row = OutreachMessage(direction="out", channel="sms", origin="agent", body="내일 타설 가능하신가요")
    session.add(row)
    session.flush()
    return Ref("message", row.id)


def _call(session: Session) -> Ref:
    row = OutreachCall(origin="agent", purpose="타설 일정 확인")
    session.add(row)
    session.flush()
    return Ref("call", row.id)


def test_same_event_shape_for_message_and_call(session):
    refs = [_message(session), _call(session)]
    for ref in refs:
        events.record(session, ref, "test_mode", "blocked", "허용 번호가 아니라 보내지 않았습니다", evidence="시험 모드 켜짐")
    session.commit()

    shapes = []
    for ref in refs:
        (event,) = events.of(session, ref)
        assert set(event) == KEYS
        assert datetime.fromisoformat(event["at"]).utcoffset() is not None  # 시간대가 붙은 시각
        shapes.append({key: value for key, value in event.items() if key != "at"})
    assert shapes[0] == shapes[1] == {
        "rule": "test_mode", "verdict": "blocked", "detail": "허용 번호가 아니라 보내지 않았습니다", "evidence": "시험 모드 켜짐",
    }


def test_events_keep_their_order_and_evidence_may_be_empty(session):
    ref = _call(session)
    events.record(session, ref, "tool:find_contact", "allowed", "query=김")
    events.record(session, ref, "scope_denied", "blocked", "범위 밖 작업")
    events.record(session, ref, "kakao_not_ready", "noted", "문자로 보냄")
    session.commit()

    got = events.of(session, ref)
    assert [e["rule"] for e in got] == ["tool:find_contact", "scope_denied", "kakao_not_ready"]
    assert [e["verdict"] for e in got] == ["allowed", "blocked", "noted"]
    assert got[0]["evidence"] is None


def test_event_text_hides_numbers(session):
    ref = _message(session)
    forms = [SENTINEL_PHONE, "+82 10-0000-0199", "공일공 공공공공 공일구구"]
    for form in forms:
        events.record(session, ref, "reply", "noted", f"상대가 {form} 로 다시 달라고 함", evidence=f"「{form}」 로 주세요")
    session.commit()

    raw = session.execute(text("SELECT harness_json FROM outreach_messages WHERE id = :id"), {"id": ref.row_id}).scalar_one()
    stored = json.loads(raw)  # 저장된 글 그대로(읽을 때 지우는 것이 아니다)
    assert len(stored) == len(forms)
    for event in stored:
        for value in (event["detail"], event["evidence"]):
            digits = re.sub(r"[^0-9]", "", value)
            assert SENTINEL_DIGITS not in digits and SENTINEL_DIGITS[1:] not in digits
            assert "공일공" not in value and "[번호]" in value


def test_record_is_part_of_the_callers_transaction(session):
    ref = _message(session)
    session.commit()
    events.record(session, ref, "duplicate", "blocked", "이미 보내는 중")
    assert len(events.of(session, ref)) == 1  # 같은 세션에서는 보인다
    session.rollback()  # commit 은 부른 쪽이 한다
    assert events.of(session, ref) == []


def test_loaded_row_sees_the_new_event(session):
    ref = _message(session)
    row = session.get(OutreachMessage, ref.row_id)
    assert row.harness_json == []
    events.record(session, ref, "hours", "allowed", "근무시간 안")
    assert [e["rule"] for e in row.harness_json] == ["hours"]


def test_events_from_two_sessions_are_both_kept(session):
    ref = _message(session)
    session.commit()
    row = session.get(OutreachMessage, ref.row_id)  # 이 세션이 먼저 읽어 쥐고 있는 줄(문이 줄을 쥔 채 사건을 남기듯)
    assert row.harness_json == []
    other = Session(session.get_bind())
    try:
        events.record(other, ref, "first", "allowed", "다른 세션")
        other.commit()
    finally:
        other.close()
    events.record(session, ref, "second", "allowed", "이 세션")
    session.commit()
    assert [e["rule"] for e in events.of(session, ref)] == ["first", "second"]
    assert [e["rule"] for e in row.harness_json] == ["first", "second"]


def test_record_needs_a_known_verdict(session):
    ref = _call(session)
    with pytest.raises(ValueError):
        events.record(session, ref, "test_mode", "denied", "틀린 판정")
    assert events.of(session, ref) == []


@pytest.mark.parametrize("kind", ["message", "call"])
def test_missing_row_is_not_found(session, kind):
    with pytest.raises(NotFound):
        events.record(session, Ref(kind, 999_999), "test_mode", "blocked", "없는 줄")
    with pytest.raises(NotFound):
        events.of(session, Ref(kind, 999_999))
