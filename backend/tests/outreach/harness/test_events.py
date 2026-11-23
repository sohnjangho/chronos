"""하네스 사건 기록(Task 64): 메시지와 통화가 같은 꼴 {rule, verdict, detail, evidence, at} 으로 그 줄의 harness_json 에 남는다.

번호·키는 모두 가상이다(이름표의 SENTINEL_PHONE·SENTINEL_KEY).
"""

import json
import re
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.info.generic import key_survives
from app.outreach import redact
from app.outreach.harness import events
from app.outreach.harness.types import (
    EVENT_RULES,
    GATE_RULES,
    SHARED_TOOLS,
    VOICE_ONLY_TOOLS,
    Ref,
)
from app.store.outreach import NotFound
from app.store.tables_outreach import OutreachCall, OutreachMessage
from tests.outreach_doubles import SENTINEL_DIGITS, SENTINEL_KEY, SENTINEL_PHONE

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


def _stored(session: Session, ref: Ref) -> list[dict]:
    """저장된 글 그대로(읽을 때 지우는 것이 아니다)."""
    table = {"message": "outreach_messages", "call": "outreach_calls"}[ref.kind]
    raw = session.execute(text(f"SELECT harness_json FROM {table} WHERE id = :id"), {"id": ref.row_id}).scalar_one()
    return json.loads(raw)


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
    events.record(session, ref, "scope_denied", "blocked", events.tool_detail("schedule_fact", "범위 밖 작업"))
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
        events.record(session, ref, "reply_failed", "noted", f"상대가 {form} 로 다시 달라고 함", evidence=f"「{form}」 로 주세요")
    session.commit()

    stored = _stored(session, ref)
    assert len(stored) == len(forms)
    for event in stored:
        for value in (event["detail"], event["evidence"]):
            digits = re.sub(r"[^0-9]", "", value)
            assert SENTINEL_DIGITS not in digits and SENTINEL_DIGITS[1:] not in digits
            assert "공일공" not in value and "[번호]" in value


def test_event_text_scrubs_registered_secrets(session):
    redact.add_secrets(SENTINEL_KEY)  # 알림 연결이 등록한 키(가상) — tests/outreach_doubles 가 시험마다 비운다
    ref = _message(session)
    events.record(session, ref, "delivery", "blocked", f"제공사 거절: Bearer {SENTINEL_KEY}",
                  evidence=f"key={SENTINEL_KEY.lower()} to={SENTINEL_PHONE}")
    session.commit()
    (event,) = _stored(session, ref)
    for value in (event["detail"], event["evidence"]):
        assert not key_survives(value, SENTINEL_KEY)
    assert "[번호]" in event["evidence"]


def test_event_text_is_hidden_when_the_secret_list_cannot_be_read(session, monkeypatch):
    def broken() -> list[str]:
        raise RuntimeError("비밀 목록을 못 읽음")

    monkeypatch.setattr(redact, "secrets", broken)  # 공개 읽기 함수가 실패(install 원천이 못 읽음)
    ref = _message(session)
    events.record(session, ref, "delivery", "blocked", f"Bearer {SENTINEL_KEY}", evidence="근거")
    (event,) = _stored(session, ref)
    assert event["detail"] == event["evidence"] == events.HIDDEN_TEXT


@pytest.mark.parametrize("rule", [
    "tool:010-0000-0199",  # 번호가 든 이름
    SENTINEL_PHONE,
    "tool:delete_schedule",  # 모델이 지어낸 도구 이름
    "Test_Mode",
    "test_mode ",
    "made_up_rule",  # 꼴은 맞지만 정해 둔 이름이 아님
    "",
])
def test_rule_must_be_a_code_chosen_name(session, rule):
    ref = _message(session)
    with pytest.raises(ValueError) as caught:
        events.record(session, ref, rule, "noted", "틀린 이름")
    assert "0199" not in str(caught.value)  # 오류 글에 받은 값을 되돌려 싣지 않는다
    assert events.of(session, ref) == []


def test_every_known_rule_has_the_code_shape():
    known = events.KNOWN_RULES
    assert set(GATE_RULES.values()) | EVENT_RULES <= known
    assert {f"tool:{t}" for t in SHARED_TOOLS + VOICE_ONLY_TOOLS} | {"tool:unknown"} <= known
    assert all(events.RULE_PATTERN.fullmatch(rule) for rule in known)


def test_tool_rule_never_carries_a_model_supplied_name(session):
    assert events.tool_rule("find_contact") == "tool:find_contact"
    assert events.tool_rule("end_call") == "tool:end_call"
    assert events.tool_rule("delete_schedule") == "tool:unknown"
    assert events.tool_rule(SENTINEL_PHONE) == "tool:unknown"
    ref = _call(session)
    events.record(session, ref, events.tool_rule("approve_all"), "blocked", events.tool_detail("approve_all"))
    assert events.of(session, ref)[0]["rule"] == "tool:unknown"
    assert events.of(session, ref)[0]["detail"] == "tool=unknown"


def test_long_text_is_cut(session):
    ref = _message(session)
    events.record(session, ref, "delivery", "noted", "가" * 5_000, evidence="나" * 100_000)
    (event,) = _stored(session, ref)
    assert len(event["detail"]) == events.DETAIL_MAX and event["detail"].endswith("…")
    assert len(event["evidence"]) == events.EVIDENCE_MAX and event["evidence"].endswith("…")
    events.record(session, ref, "delivery", "noted", "짧은 글", evidence="짧은 근거")
    assert _stored(session, ref)[1]["detail"] == "짧은 글"


def test_events_per_row_are_capped_with_one_omitted_marker(session):
    ref = _message(session)
    total = events.MAX_EVENTS + 50
    for n in range(total):
        events.record(session, ref, "delivery", "noted", f"사건 {n}")
    session.commit()
    got = events.of(session, ref)
    assert len(got) == events.MAX_EVENTS
    marker, kept = got[0], got[1:]
    assert marker["rule"] == events.OMITTED and marker["verdict"] == "noted"
    assert marker["detail"] == f"앞선 사건 {total - len(kept)}개 생략됨"
    assert set(marker) == KEYS
    assert [e["detail"] for e in kept] == [f"사건 {n}" for n in range(total - len(kept), total)]  # 최근 것은 그대로
    assert sum(e["rule"] == events.OMITTED for e in got) == 1  # 표식은 늘 하나


def test_record_takes_a_fixed_time(session):
    ref = _call(session)
    events.record(session, ref, "silence", "noted", "침묵 15초", now=datetime(2026, 11, 24, 9, 30))  # 시간대 없음 = UTC
    events.record(session, ref, "time_limit", "noted", "최대 시간", now=datetime(2026, 11, 24, 18, 31, tzinfo=UTC))
    got = events.of(session, ref)
    assert got[0]["at"] == "2026-11-24T09:30:00.000+00:00"
    assert got[1]["at"] == "2026-11-24T18:31:00.000+00:00"


@pytest.mark.parametrize("stored", ["null", "{}", '{"a": 1}'])
def test_non_list_harness_json_is_refused(session, stored):
    ref = _message(session)
    session.commit()
    session.execute(text("UPDATE outreach_messages SET harness_json = :v WHERE id = :id"), {"v": stored, "id": ref.row_id})
    session.commit()
    with pytest.raises(ValueError):
        events.record(session, ref, "delivery", "noted", "목록이 아닌 칸")
    session.rollback()
    assert _raw(session, ref) == stored  # 아무것도 바꾸지 않았다
    if stored == "null":
        assert events.of(session, ref) == []
    else:
        with pytest.raises(ValueError):
            events.of(session, ref)


def _raw(session: Session, ref: Ref) -> str:
    return session.execute(text("SELECT harness_json FROM outreach_messages WHERE id = :id"), {"id": ref.row_id}).scalar_one()


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
    events.record(session, ref, "working_hours", "allowed", "근무시간 안")
    assert [e["rule"] for e in row.harness_json] == ["working_hours"]


def test_events_from_two_sessions_are_both_kept(session):
    ref = _message(session)
    session.commit()
    row = session.get(OutreachMessage, ref.row_id)  # 이 세션이 먼저 읽어 쥐고 있는 줄(문이 줄을 쥔 채 사건을 남기듯)
    assert row.harness_json == []
    other = Session(session.get_bind())
    try:
        events.record(other, ref, "site_pinned", "allowed", "다른 세션")
        other.commit()
    finally:
        other.close()
    events.record(session, ref, "delivery", "allowed", "이 세션")
    session.commit()
    assert [e["rule"] for e in events.of(session, ref)] == ["site_pinned", "delivery"]
    assert [e["rule"] for e in row.harness_json] == ["site_pinned", "delivery"]


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


def test_events_reads_redact_only_through_public_names():
    """redact 의 밑줄 이름(_FILTER 등)에 기대지 않는다 — 비밀은 redact.secrets()·redact.scrub 로만."""
    import ast
    from pathlib import Path

    source = Path(events.__file__).read_text(encoding="utf-8")
    private = {node.attr for node in ast.walk(ast.parse(source))
               if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "redact"
               and node.attr.startswith("_")}
    assert private == set()


@pytest.mark.parametrize(("rule", "good", "bad"), [
    ("admission", "stop_word", "상대가 그만이라고 함"),
    ("call_result", "no_answer", "받지 않음"),
    ("delivery_update", "gave_up", "72시간"),
    ("channel_choice", "sms", "문자"),
])
def test_fixed_code_rules_take_only_their_codes(session, rule, good, bad):
    ref = _call(session)
    events.record(session, ref, rule, "noted", good)
    assert events.of(session, ref)[0]["detail"] == good
    with pytest.raises(ValueError) as caught:
        events.record(session, ref, rule, "noted", bad)
    assert bad not in str(caught.value)
    assert len(events.of(session, ref)) == 1


def test_tool_refusals_name_the_tool_in_a_fixed_form(session):
    assert events.tool_detail("schedule_fact") == "tool=schedule_fact"
    assert events.tool_detail("schedule_fact", "범위 밖 작업") == "tool=schedule_fact 범위 밖 작업"
    assert events.tool_detail("approve_everything") == "tool=unknown"  # 모델이 지어낸 이름은 적지 않는다
    assert events.tool_detail(SENTINEL_PHONE, "x") == "tool=unknown x"
    ref = _call(session)
    for rule in ("scope_denied", "tool_not_allowed", "tool_bad_args", "tool:unknown"):
        events.record(session, ref, rule, "blocked", events.tool_detail("schedule_fact", "거절"))
    for bad in ("schedule_fact 거절", "tool=delete_schedule", "범위 밖"):
        with pytest.raises(ValueError):
            events.record(session, ref, "scope_denied", "blocked", bad)
    assert [e["detail"] for e in events.of(session, ref)] == ["tool=schedule_fact 거절"] * 4


def test_text_trouble_never_drops_the_event(session, monkeypatch):
    ref = _message(session)
    events.record(session, ref, "delivery", "noted", None, evidence=123)  # 글이 아닌 값
    monkeypatch.setattr(redact, "scrub", lambda *_a, **_k: 1 / 0)  # 지우는 함수가 터짐
    events.record(session, ref, "test_mode", "blocked", f"Bearer {SENTINEL_KEY}", evidence="근거")
    got = events.of(session, ref)
    assert [(e["rule"], e["verdict"]) for e in got] == [("delivery", "noted"), ("test_mode", "blocked")]  # 이름·판정은 남는다
    assert got[0]["detail"] == got[0]["evidence"] == events.HIDDEN_TEXT
    assert got[1]["detail"] == got[1]["evidence"] == events.HIDDEN_TEXT
