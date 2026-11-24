"""개발 콘솔 ①(Task 108): 실행 추적의 「연락」 · 시스템 진단의 알림 연결 · 사용량의 문자 수. 읽기만 한다.

사람·회사·번호는 모두 가상이다(번호 010-0000-0199 = SENTINEL_PHONE, 키 SENTINEL_KEY).
"""

import ast
import inspect
import json
from datetime import UTC, datetime, timedelta

import pytest

from app.notify import diagnostics
from app.outreach.harness import events
from app.outreach.harness.types import EVENT_GROUP_KEYS, EVENT_GROUPS, GATE_RULES, Ref
from app.programs.devconsole import outreach_view
from app.security.crypto import encrypt
from app.store.tables_outreach import (
    Contact,
    ContactCompany,
    NotifyConnection,
    OutreachCall,
    OutreachMessage,
)
from tests.outreach_doubles import SENTINEL_DIGITS, SENTINEL_KEY, SENTINEL_PHONE, _leaks

ACCOUNT = "ACCT-SENTINEL-77665544"
BODY = "BODY-SENTINEL 내일 오전 자재 반입 확인 부탁드립니다"
TRANSCRIPT = "TRANSCRIPT-SENTINEL 네 알겠습니다"
PROVIDER_ID = "PROVIDER-ID-SENTINEL-0001"
FREE_TEXT = f"FREE-TEXT-SENTINEL {SENTINEL_KEY}"
NOW = datetime.now(UTC)


# ── 가상 자료 ───────────────────────────────────────────────────────


def _company(session, sid: int, name: str = "한빛전기") -> int:
    row = ContactCompany(schedule_id=sid, name=name, trade="전기")
    session.add(row)
    session.commit()
    return row.id


def _contact(session, sid: int, company_id: int, name: str = "가상 담당") -> int:
    row = Contact(schedule_id=sid, company_id=company_id, name=name, role_title="현장 대리", phone=SENTINEL_DIGITS)
    session.add(row)
    session.commit()
    return row.id


def _message(session, **fields) -> OutreachMessage:
    values = {"direction": "out", "channel": "sms", "origin": "user", "origin_name": "김하늘", "body": BODY,
              "provider_message_id": PROVIDER_ID, "created_at": NOW, **fields}
    row = OutreachMessage(**values)
    session.add(row)
    session.commit()
    return row


def _call(session, **fields) -> OutreachCall:
    values = {"direction": "out", "origin": "user", "origin_name": "김하늘", "purpose": BODY,
              "transcript_json": [{"role": "peer", "text": TRANSCRIPT, "t": 1}], "summary_ko": TRANSCRIPT,
              "provider_call_id": PROVIDER_ID, "created_at": NOW, **fields}
    row = OutreachCall(**values)
    session.add(row)
    session.commit()
    return row


def _record(session, ref: Ref, rule: str, verdict: str, detail: str | None = None) -> None:
    events.record(session, ref, rule, verdict, detail)
    session.commit()


def _connection(session, **fields) -> NotifyConnection:
    values = {"name": "기본 연결", "base_url": "https://kat.invalid", "secret_ciphertext": encrypt(SENTINEL_KEY),
              "secret_last4": "9999", "account_id": ACCOUNT, "sender_number": SENTINEL_DIGITS, "is_default": True,
              "status": "ok", "checked_at": NOW, "allow_numbers_json": [SENTINEL_DIGITS, "01000000200"], **fields}
    row = NotifyConnection(**values)
    session.add(row)
    session.commit()
    return row


@pytest.fixture
def book(session, sid):
    """시험 일정의 협력사 하나·연락처 하나."""
    company = _company(session, sid)
    return sid, company, _contact(session, sid, company)


def _list(client, admin, **params) -> dict:
    r = client.get("/api/devconsole/outreach", params=params, headers=admin)
    assert r.status_code == 200, r.text
    return r.json()


def _detail(client, admin, kind: str, row_id: int) -> dict:
    r = client.get(f"/api/devconsole/outreach/{kind}/{row_id}", headers=admin)
    assert r.status_code == 200, r.text
    return r.json()


def _health(client, admin) -> dict:
    r = client.get("/api/devconsole/health", headers=admin)
    assert r.status_code == 200, r.text
    return r.json()


# ── 지시서 시험 ─────────────────────────────────────────────────────


def test_outreach_list_shows_starter_mode_class_from_rows(client, admin, session, book):
    sid, _company_id, contact = book
    sent = _message(session, schedule_id=sid, contact_id=contact, origin="agent", origin_name="에이전트",
                    send_mode="delegated", status="accepted", caller_class=None, created_at=NOW - timedelta(minutes=3))
    call = _call(session, schedule_id=sid, contact_id=contact, send_mode="approved", approved_by="김하늘",
                 caller_class="outbound", status="completed", created_at=NOW - timedelta(minutes=2))
    inbound = _message(session, direction="in", origin="peer", origin_name="", peer_number=SENTINEL_DIGITS,
                       caller_class="unknown", status="received", created_at=NOW - timedelta(minutes=1))
    _record(session, Ref("message", sent.id), "channel_choice", "allowed", "sms")
    _record(session, Ref("message", sent.id), "delivery", "allowed", "보냄")

    body = _list(client, admin)
    assert body["more"] is False
    rows = body["items"]
    assert [(r["kind"], r["id"]) for r in rows] == [("message", inbound.id), ("call", call.id), ("message", sent.id)]
    peer, phoned, texted = rows
    assert {k: texted[k] for k in (
        "direction", "channel", "origin", "origin_name", "send_mode", "caller_class", "status", "contact_name",
        "company_name", "number_masked", "schedule_name", "events")} == {
        "direction": "out", "channel": "sms", "origin": "agent", "origin_name": "에이전트", "send_mode": "delegated",
        "caller_class": None, "status": "accepted", "contact_name": "가상 담당", "company_name": "한빛전기",
        "number_masked": "010-****-0199", "schedule_name": "시험 일정", "events": 2}
    assert (phoned["channel"], phoned["origin"], phoned["send_mode"], phoned["caller_class"]) == (
        "call", "user", "approved", "outbound")
    assert (peer["contact_name"], peer["company_name"], peer["schedule_name"]) == (None, None, None)
    assert (peer["origin"], peer["caller_class"], peer["number_masked"]) == ("peer", "unknown", "010-****-0199")

    assert [r["kind"] for r in _list(client, admin, kind="call")["items"]] == ["call"]
    capped = _list(client, admin, limit=2)
    assert len(capped["items"]) == 2 and capped["more"] is True


def test_timeline_is_built_only_from_recorded_events(client, admin, session, book):
    sid, _company_id, contact = book
    quiet = _message(session, schedule_id=sid, contact_id=contact, status="draft")
    body = _detail(client, admin, "message", quiet.id)
    assert body["timeline"] == []
    assert body["attempts"] == 0 and body["needs_check"] == 0
    assert body["head"]["fail_reason"] is None and body["head"]["approved_by"] is None
    assert all(g["count"] == 0 for g in body["groups"])


def test_gate_decision_and_tool_calls_appear_in_order(client, admin, session, book):
    sid, _company_id, contact = book
    row = _message(session, schedule_id=sid, contact_id=contact, channel="kakao", status="accepted",
                   send_mode="manual")
    ref = Ref("message", row.id)
    _record(session, ref, "kakao_not_ready", "noted", FREE_TEXT)
    _record(session, ref, "channel_choice", "allowed", "sms")
    _record(session, ref, "delivery", "allowed", FREE_TEXT)
    _record(session, ref, "tool:find_contact", "allowed", FREE_TEXT)
    _record(session, ref, events.tool_rule("made_up_tool"), "blocked", events.tool_detail("made_up_tool"))
    _record(session, ref, "scope_denied", "blocked", events.tool_detail("schedule_fact", FREE_TEXT))

    timeline = _detail(client, admin, "message", row.id)["timeline"]
    marks = [t["harness"] for t in timeline]
    assert [t["seq"] for t in timeline] == [1, 2, 3, 4, 5, 6]
    assert all(t["kind"] == "harness" for t in timeline)
    assert [m["rule"] for m in marks] == [
        "kakao_not_ready", "channel_choice", "delivery", "tool:find_contact", "tool:unknown", "scope_denied"]
    assert [m["group"] for m in marks] == [EVENT_GROUPS[m["rule"]] for m in marks]
    assert [m["verdict"] for m in marks] == ["noted", "allowed", "allowed", "allowed", "blocked", "blocked"]
    gate = marks[1]
    assert gate["order"] == 7 and gate["code"] == "sms"
    assert "문자" in timeline[1]["label"]
    assert marks[3]["code"] == "find_contact" and "find_contact" in timeline[3]["label"]
    assert marks[4]["code"] == "unknown" and marks[5]["code"] == "schedule_fact"
    assert [t["ok"] for t in timeline] == [True, True, True, True, False, False]


def test_unsure_rows_are_shown_as_needs_check_and_counted(client, admin, session, book):
    sid, _company_id, contact = book
    _connection(session)
    row = _message(session, schedule_id=sid, contact_id=contact, status="unconfirmed", send_mode="manual")
    ref = Ref("message", row.id)
    _record(session, ref, "channel_choice", "allowed", "sms")
    _record(session, ref, "delivery", "noted", "보냈는지 확인 필요")
    sure = _message(session, schedule_id=sid, contact_id=contact, status="accepted", send_mode="manual")
    _record(session, Ref("message", sure.id), "delivery", "allowed", "보냄")

    body = _detail(client, admin, "message", row.id)
    delivery = body["timeline"][1]
    assert delivery["harness"]["needs_check"] is True
    assert "확인 필요" in delivery["label"]
    assert delivery["ok"] is True  # 실패가 아니다 — 「확인 필요」
    assert body["needs_check"] == 1
    listed = {r["id"]: r for r in _list(client, admin)["items"]}
    assert listed[row.id]["needs_check"] is True and listed[sure.id]["needs_check"] is False
    assert _health(client, admin)["notify"]["needs_check"] == 1


def _string_constants(module) -> set[str]:
    tree = ast.parse(inspect.getsource(module))
    return {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def test_event_groups_come_from_harness_types():
    named = _string_constants(outreach_view)
    assert not named & (events.KNOWN_RULES | set(GATE_RULES.values())), (
        "콘솔 코드에 사건 이름 글자가 따로 있습니다 — harness.types 의 상수를 읽을 것")
    for rule in events.KNOWN_RULES:
        assert outreach_view.group_of(rule) == EVENT_GROUPS[rule]
    assert outreach_view.group_of("not_a_rule") is None
    assert set(outreach_view.GROUP_LABELS) == set(EVENT_GROUP_KEYS)
    assert set(outreach_view.ORDER_LABELS) == set(GATE_RULES)


def test_attempts_are_shown_in_order(client, admin, session, book):
    sid, _company_id, contact = book
    row = _message(session, schedule_id=sid, contact_id=contact, status="delivered", send_mode="manual")
    ref = Ref("message", row.id)
    _record(session, ref, "working_hours", "blocked", "근무시간 밖")
    _record(session, ref, "reply_within_grace", "noted", "답 유예")
    _record(session, ref, "channel_choice", "allowed", "sms")
    _record(session, ref, "delivery", "allowed", "보냄")
    _record(session, ref, "delivery_update", "noted", "delivered")

    body = _detail(client, admin, "message", row.id)
    assert body["attempts"] == 2
    assert [t["harness"]["attempt"] for t in body["timeline"]] == [1, 2, 2, 2, 2]
    assert [t["harness"]["order"] for t in body["timeline"][:3]] == [3, None, 7]


def _walk(value) -> list[str]:
    """응답 JSON 의 모든 글(열쇠 포함)."""
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in (str(k), *_walk(v))]
    if isinstance(value, list):
        return [s for v in value for s in _walk(v)]
    return [str(value)]


def test_console_outreach_views_have_no_number_or_key(client, admin, session, book):
    sid, _company_id, contact = book
    _connection(session, last_diagnosis_json={"state": "done", "ran_at": NOW.isoformat(), "real": True, "steps": [
        {"id": "P1", "label": "인증", "ok": False, "skipped": False, "detail": f"bad_key {SENTINEL_KEY} {SENTINEL_PHONE}",
         "notes": [ACCOUNT, SENTINEL_PHONE], "code": "bad_key", "maybe_sent": False, "pending": False}]})
    msg = _message(session, schedule_id=sid, contact_id=contact, status="failed", send_mode="manual",
                   fail_reason=f"보내지 못했습니다 {SENTINEL_PHONE}", body_ko=BODY, claimed_at=NOW,
                   harness_json=[{"rule": "delivery", "verdict": "blocked", "detail": FREE_TEXT,
                                  "evidence": f"{SENTINEL_PHONE} {BODY}", "at": NOW.isoformat()},
                                 {"rule": "made_up", "verdict": "blocked", "detail": SENTINEL_PHONE}])
    peer = _message(session, direction="in", origin="peer", origin_name=SENTINEL_PHONE, peer_number=SENTINEL_DIGITS,
                    status="received")
    call = _call(session, schedule_id=sid, contact_id=contact, status="completed", claimed_at=NOW,
                 harness_json=[{"rule": "tool:take_message", "verdict": "allowed", "detail": TRANSCRIPT,
                                "evidence": None, "at": NOW.isoformat()}])

    bodies = [
        _list(client, admin),
        _detail(client, admin, "message", msg.id),
        _detail(client, admin, "message", peer.id),
        _detail(client, admin, "call", call.id),
        _health(client, admin)["notify"],
        client.get("/api/devconsole/usage", headers=admin).json()["outreach"],
    ]
    for body in bodies:
        text = "\n".join(_walk(body))
        assert not _leaks(text, (ACCOUNT, PROVIDER_ID)), _leaks(text, (ACCOUNT, PROVIDER_ID))
        for secret in (SENTINEL_KEY, ACCOUNT, PROVIDER_ID, "BODY-SENTINEL", "TRANSCRIPT-SENTINEL", "FREE-TEXT-SENTINEL",
                       SENTINEL_DIGITS):
            assert secret not in text
    assert "010-****-0199" in json.dumps(bodies[0], ensure_ascii=False)  # 가린 꼴만


def test_health_notify_without_connection(client, admin):
    notify = _health(client, admin)["notify"]
    assert notify["connected"] is False
    assert {k: v for k, v in notify.items() if v not in (None, 0, False)} == {}


def test_health_shows_worker_last_run_times(client, admin, session, monkeypatch):
    worker = pytest.importorskip("app.outreach.worker")  # Task 71 의 일꾼(그 작업이 들기 전의 판에서는 건너뜀)
    _connection(session)
    at = datetime(2026, 11, 24, 1, 2, 3, tzinfo=UTC)
    monkeypatch.setattr(worker, "_state", worker._State(running=True, last_tick_at=at, last_due_at=at,
                                                        last_status_poll_at=at, last_inbound_poll_at=at))
    notify = _health(client, admin)["notify"]
    assert notify["connected"] is True and notify["status"] == "ok" and notify["test_mode"] is True
    assert notify["allow_count"] == 2 and notify["sender_masked"] == "010-****-0199"
    assert notify["inbound_mode"] == "off" and notify["agent"] == {"sms": "approve", "kakao": "approve",
                                                                   "call": "approve"}
    w = notify["worker"]
    assert w["running"] is True
    for key in ("last_tick_at", "last_due_at", "last_status_poll_at", "last_inbound_poll_at"):
        assert datetime.fromisoformat(w[key]) == at
    assert notify["kakao"]["channel"] is None and notify["voice"] is None  # 카카오톡 칸은 test_devconsole_outreach_kakao


def test_health_shows_last_diagnosis_lines_without_rerunning(client, admin, session, monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("콘솔이 진단을 다시 돌렸습니다")

    monkeypatch.setattr(diagnostics, "run_checks", refuse)
    step = {"label": "걸음", "detail": "글", "notes": [], "latency_ms": 12, "maybe_sent": False, "pending": False}
    _connection(session, last_diagnosis_json={"state": "done", "ran_at": "2026-11-24T01:00:00+00:00", "real": False,
                                              "steps": [
        {**step, "id": "P1", "ok": True, "skipped": False, "code": "ok"},
        {**step, "id": "P2", "ok": False, "skipped": False, "code": "timeout", "maybe_sent": True},
        {**step, "id": "P3", "ok": False, "skipped": False, "code": "still_queued", "pending": True},
        {**step, "id": "P4", "ok": False, "skipped": False, "code": "bad_key"},
        "망가진 걸음"]})
    diag = _health(client, admin)["notify"]["last_diagnosis"]
    assert datetime.fromisoformat(diag["ran_at"]) == datetime(2026, 11, 24, 1, 0, tzinfo=UTC)
    assert [(s["id"], s["outcome"]) for s in diag["steps"]] == [
        ("P1", "ok"), ("P2", "check"), ("P3", "check"), ("P4", "failed")]
    assert diag["steps"][3]["code"] == "bad_key"


def test_usage_counts_sms_and_long_and_hides_cost_when_unreported(client, admin, session):
    _message(session, status="accepted", claimed_at=NOW, length_kind="sms")
    _message(session, status="delivered", claimed_at=NOW, length_kind="long")
    _message(session, status="failed", claimed_at=NOW, kind="auto_reply")
    _message(session, channel="kakao", status="accepted", claimed_at=NOW)
    _message(session, status="draft")  # 차지하지 않은 줄은 세지 않는다
    out = client.get("/api/devconsole/usage?days=7", headers=admin).json()["outreach"]
    out.pop("text_models")  # 글 쪽 모델 사용(Task 109 — test_devconsole_outreach_branches 가 본다)
    out.pop("calls")  # 통화 사용량(Task 110 — test_devconsole_outreach_calls 가 본다)
    out.pop("fallback_sms"), out.pop("kakao_not_ready")  # 알림톡 건수(Task 111 — test_devconsole_outreach_kakao 가 본다)
    assert out == {"sms": 3, "long": 1, "kakao": 1, "auto_replies": 1, "provider_cost": None}


def test_admin_only(client, user):
    for url in ("/api/devconsole/outreach", "/api/devconsole/outreach/message/1", "/api/devconsole/outreach/call/1"):
        r = client.get(url, headers=user)
        assert r.status_code == 403 and r.json()["code"] == "admin_only"


# ── 더한 시험(경계) ────────────────────────────────────────────────


def test_missing_row_is_404_and_bad_kind_is_422(client, admin, session, book):
    sid, _company_id, contact = book
    row = _message(session, schedule_id=sid, contact_id=contact)
    assert client.get(f"/api/devconsole/outreach/call/{row.id + 100}", headers=admin).status_code == 404
    assert client.get(f"/api/devconsole/outreach/message/{row.id + 100}", headers=admin).json()["code"] == "not_found"
    assert client.get(f"/api/devconsole/outreach/email/{row.id}", headers=admin).status_code == 422


@pytest.mark.parametrize("stored", [{"rule": "delivery"}, "망가짐", [7, {"rule": "made_up", "verdict": "blocked"},
                                                                        {"rule": "delivery", "verdict": "weird"},
                                                                        {"rule": "admission", "verdict": "allowed",
                                                                         "detail": "not_a_code", "at": "어제"}]])
def test_malformed_events_are_unknown_lines_not_500(client, admin, session, book, stored):
    sid, _company_id, contact = book
    row = _message(session, schedule_id=sid, contact_id=contact)
    session.execute(OutreachMessage.__table__.update().where(OutreachMessage.id == row.id).values(harness_json=stored))
    session.commit()
    body = _detail(client, admin, "message", row.id)
    marks = [t["harness"] for t in body["timeline"]]
    assert marks and all(m["unknown"] for m in marks[:3])
    assert all(t["label"].startswith("알 수 없는 사건") for t, m in zip(body["timeline"], marks) if m["unknown"])
    assert {g["key"]: g["count"] for g in body["groups"]}["unknown"] >= 1
    assert _list(client, admin)["items"][0]["events"] >= 1


def _plant(session, book, stored) -> int:
    sid, _company_id, contact = book
    row = _message(session, schedule_id=sid, contact_id=contact)
    session.execute(OutreachMessage.__table__.update().where(OutreachMessage.id == row.id).values(harness_json=stored))
    session.commit()
    return row.id


@pytest.mark.parametrize("event", [
    {"rule": "channel_choice", "verdict": []},
    {"rule": "channel_choice", "verdict": ["allowed"]},
    {"rule": "channel_choice", "verdict": {"a": 1}},
    {"rule": ["channel_choice"], "verdict": "allowed"},
    {"rule": {"x": 1}, "verdict": "allowed"},
    {"verdict": "allowed"},
    None,
    3.5,
    ["channel_choice", "allowed"],
])
def test_unhashable_or_odd_events_are_unknown_lines_not_500(client, admin, session, book, event):
    body = _detail(client, admin, "message", _plant(session, book, [event]))
    [line] = body["timeline"]
    assert line["harness"]["unknown"] is True and line["label"] == "알 수 없는 사건"


@pytest.mark.parametrize("detail", [{}, ["sms"], {"a": 1}, 7, None])
def test_odd_detail_of_a_known_event_is_shown_without_code(client, admin, session, book, detail):
    stored = [{"rule": "admission", "verdict": "allowed", "detail": detail},
              {"rule": "channel_choice", "verdict": "allowed", "detail": detail},
              {"rule": "delivery_update", "verdict": "noted", "detail": detail},
              {"rule": "scope_denied", "verdict": "blocked", "detail": detail}]
    body = _detail(client, admin, "message", _plant(session, book, stored))
    assert len(body["timeline"]) == 4
    assert all(t["harness"]["code"] is None for t in body["timeline"])


def test_any_failure_building_one_line_makes_only_that_line_unknown(client, admin, session, book, monkeypatch,
                                                                    caplog):
    real = outreach_view._mark

    def broken(event):
        if event.get("rule") == "channel_choice":
            raise RuntimeError(FREE_TEXT)
        return real(event)

    monkeypatch.setattr(outreach_view, "_mark", broken)
    stored = [{"rule": "channel_choice", "verdict": "allowed", "detail": "sms", "at": NOW.isoformat()},
              {"rule": "delivery", "verdict": "allowed", "detail": "보냄", "at": NOW.isoformat()}]
    body = _detail(client, admin, "message", _plant(session, book, stored))
    assert [t["harness"]["unknown"] for t in body["timeline"]] == [True, False]
    assert "FREE-TEXT-SENTINEL" not in caplog.text


def test_omitted_marker_and_event_cap(client, admin, session, book):
    sid, _company_id, contact = book
    stored = [{"rule": events.OMITTED, "verdict": "noted", "detail": "앞선 사건 40개 생략됨", "at": NOW.isoformat()}]
    stored += [{"rule": "channel_choice", "verdict": "allowed", "detail": "sms", "at": NOW.isoformat()}]  # 가장 오래된 것
    stored += [{"rule": "delivery_update", "verdict": "noted", "detail": "delivered", "at": NOW.isoformat()}] * (
        outreach_view.EVENT_CAP + 4)
    row = _message(session, schedule_id=sid, contact_id=contact, harness_json=stored)
    body = _detail(client, admin, "message", row.id)
    assert len(body["timeline"]) == outreach_view.EVENT_CAP
    assert body["omitted"] == 40 + 5  # 표식이 센 40 + 상한 밖으로 밀린 앞 사건 5
    assert {t["harness"]["rule"] for t in body["timeline"]} == {"delivery_update"}  # 최근 것만 남는다

