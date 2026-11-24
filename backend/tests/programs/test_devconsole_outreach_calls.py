"""개발 콘솔 ③(Task 110): 통화 — 실행 추적의 통화 줄 · call_placed 가지 · 시스템 진단의 AI 전화 · 통화 사용량. 읽기만 한다.

콘솔은 통화 뒤 확인(after.finish)·음성 진단을 다시 돌리지 않는다. 받아쓰기 글·번호·키(끝 4자리도)는 어떤 응답에도 없다.
사람·회사·번호는 모두 가상이다(번호 010-0000-0199 = SENTINEL_PHONE).
"""

import json
from datetime import UTC, datetime

import pytest

from app.notify import diagnostics_voice
from app.outreach.harness import events
from app.outreach.harness.types import Ref
from app.outreach.voice import after, runner
from app.programs.devconsole import outreach_branches, outreach_view
from app.security.crypto import encrypt
from app.store.tables_outreach import (
    Contact,
    ContactCompany,
    NotifyConnection,
    OutreachCall,
    OutreachUsage,
    VoiceSettings,
)
from tests.outreach_doubles import SENTINEL_DIGITS, SENTINEL_KEY, SENTINEL_PHONE, _leaks
from tests.programs.test_devconsole_api import get_turn, out, signal_turn

NOW = datetime.now(UTC)
VOICE_KEY = "voice-test-key-QQQQ4321"
TRANSCRIPT = "TRANSCRIPT-SENTINEL 내일 오전에 자재가 들어옵니다"
SPOKEN_NUMBER = f"제 번호는 {SENTINEL_PHONE} 입니다"
SUMMARY = "SUMMARY-SENTINEL 자재 반입 확인"


def _contact(session, sid: int) -> int:
    company = ContactCompany(schedule_id=sid, name="한빛전기", trade="전기")
    session.add(company)
    session.commit()
    row = Contact(schedule_id=sid, company_id=company.id, name="가상 담당", role_title="현장 대리", phone=SENTINEL_DIGITS)
    session.add(row)
    session.commit()
    return row.id


@pytest.fixture
def who(session, sid):
    return sid, _contact(session, sid)


def _call(session, **fields) -> OutreachCall:
    values = {"direction": "out", "origin": "agent", "origin_name": "에이전트", "send_mode": "delegated",
              "caller_class": "outbound", "purpose": "가상 목적", "created_at": NOW, **fields}
    row = OutreachCall(**values)
    session.add(row)
    session.commit()
    return row


def _record(session, call_id: int, rule: str, verdict: str, detail: str | None = None) -> None:
    events.record(session, Ref("call", call_id), rule, verdict, detail)
    session.commit()


def _detail(client, admin, call_id: int) -> dict:
    r = client.get(f"/api/devconsole/outreach/call/{call_id}", headers=admin)
    assert r.status_code == 200, r.text
    return r.json()


def _connection(session) -> NotifyConnection:
    row = NotifyConnection(name="기본 연결", base_url="https://kat.invalid", secret_ciphertext=encrypt(SENTINEL_KEY),
                           secret_last4="9999", account_id="ACCT-0000", sender_number=SENTINEL_DIGITS, is_default=True,
                           status="ok", checked_at=NOW)
    session.add(row)
    session.commit()
    return row


def _no_rerun(monkeypatch) -> None:
    """콘솔이 통화 뒤 확인이나 음성 진단을 다시 돌리면 시험이 실패한다."""
    def refuse(*_a, **_k):
        raise AssertionError("콘솔이 통화 뒤 확인·음성 진단을 다시 돌렸습니다")

    monkeypatch.setattr(after, "finish", refuse)
    monkeypatch.setattr(diagnostics_voice, "run_voice_checks", refuse)


def _walk(value) -> list[str]:
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in (str(k), *_walk(v))]
    if isinstance(value, list):
        return [s for v in value for s in _walk(v)]
    return [str(value)]


# ── 실행 추적 ───────────────────────────────────────────────────────


def test_call_trace_shows_gate_recheck_tools_and_harness_events(client, admin, session, who, monkeypatch):
    _no_rerun(monkeypatch)
    sid, contact = who
    call = _call(session, schedule_id=sid, contact_id=contact, status="completed", duration_s=95, claimed_at=NOW,
                 transcript_json=[{"role": "agent", "text": "안녕하세요", "t": 0}, {"role": "peer", "text": TRANSCRIPT, "t": 3},
                                  {"role": "agent", "text": "감사합니다", "t": 9}])
    for rule, verdict, detail in (
        ("channel_choice", "allowed", "call"),  # 문 판정
        ("delivery", "allowed", "줄에 넣음"),
        ("recheck_before_dial", "allowed", "ok"),  # 걸기 직전 재확인
        ("tool:find_contact", "allowed", "q"),
        ("scope_denied", "blocked", events.tool_detail("schedule_fact", "범위 밖")),
        ("silence", "noted", "침묵 확인 1"),
        ("time_limit", "noted", "정리 안내"),
        ("unsupported_date", "noted", "도구 결과에 없는 날짜"),  # 뒤 확인 깃발
    ):
        _record(session, call.id, rule, verdict, detail)

    body = _detail(client, admin, call.id)
    head = body["head"]
    assert (head["kind"], head["channel"], head["origin"], head["send_mode"], head["caller_class"], head["status"]) == (
        "call", "call", "agent", "delegated", "outbound", "completed")
    assert head["duration_s"] == 95 and head["transcript_lines"] == 3
    marks = [t["harness"] for t in body["timeline"]]
    assert [m["rule"] for m in marks] == ["channel_choice", "delivery", "recheck_before_dial", "tool:find_contact",
                                          "scope_denied", "silence", "time_limit", "unsupported_date"]
    labels = [t["label"] for t in body["timeline"]]
    assert labels[2] == "걸기 직전 재확인" and marks[2]["code"] is None
    assert "find_contact" in labels[3] and marks[4]["code"] == "schedule_fact"
    assert labels[5] == "침묵 확인" and labels[6] == "최대 시간"
    assert labels[7] == "도구 결과에 없는 날짜" and marks[7]["group"] == "post_check"
    assert [t["ok"] for t in body["timeline"]] == [True, True, True, True, False, True, True, True]
    assert (labels[1], marks[1]["verdict_label"]) == ("통로 결과 — 줄에 넣음", "줄에 넣음")  # 통화 말(「보냄」 아님)

    stopped = _call(session, schedule_id=sid, contact_id=contact, status="blocked_test")
    _record(session, stopped.id, "channel_choice", "allowed", "call")
    _record(session, stopped.id, "recheck_before_dial", "blocked", "test_mode")
    line = _detail(client, admin, stopped.id)["timeline"][1]
    assert line["harness"]["code"] == "test_mode" and line["label"] == "걸기 직전 재확인 — 시험 모드·허용 번호"
    assert line["ok"] is False


def test_unknown_outcome_call_is_needs_check_never_failed(client, admin, session, who):
    sid, contact = who
    call = _call(session, schedule_id=sid, contact_id=contact, status="failed", claimed_at=NOW,
                 fail_reason="걸렸는지 확인 필요")
    _record(session, call.id, "recheck_before_dial", "allowed", "ok")
    _record(session, call.id, "call_result", "blocked", "backend_error")
    _record(session, call.id, "hangup_by_person", "noted", "사람이 끊음")  # 사이에 다른 사건이 끼어도 줄 기준으로 가린다
    _record(session, call.id, "delivery", "noted", "결과 모름")
    plain = _call(session, schedule_id=sid, contact_id=contact, status="failed", claimed_at=NOW)
    _record(session, plain.id, "call_result", "blocked", "backend_error")

    body = _detail(client, admin, call.id)
    result, delivery = body["timeline"][1], body["timeline"][3]
    assert result["ok"] is True and result["harness"]["verdict_label"] == "확인 필요"  # 막음·실패로 보이지 않는다
    assert result["error"] is None  # 펼쳐도 빨간 오류 줄이 없다
    assert delivery["harness"]["needs_check"] is True and delivery["ok"] is True and delivery["error"] is None
    assert delivery["label"] == "통로 결과 — 걸렸는지 확인 필요"
    assert body["needs_check"] == 1 and body["head"]["needs_check"] is True
    assert body["branches_lit"] == ["call_placed"]
    rows = {r["id"]: r for r in client.get("/api/devconsole/outreach?kind=call", headers=admin).json()["items"]}
    assert rows[call.id]["needs_check"] is True and rows[plain.id]["needs_check"] is False
    failed = _detail(client, admin, plain.id)["timeline"][0]
    assert (failed["ok"], failed["harness"]["verdict_label"], failed["error"]) == (False, "실패", "실패")  # 분명한 실패


def test_call_and_review_event_labels_are_pinned():
    """사건 이름 글자는 콘솔 모듈에 없다(이름 차례로 짝지음) — 그 짝을 여기서 이름으로 못 박는다."""
    assert outreach_branches.RECHECK_RULE == "recheck_before_dial"
    assert outreach_view.RULE_LABELS == {
        "call_result": "통화 결과", "hangup_by_person": "사람이 끊음", "no_answer_retry": "받지 않아 다시 걸기 예약",
        "recheck_before_dial": "걸기 직전 재확인", "silence": "침묵 확인", "time_limit": "최대 시간",
        "disclosed_to_unknown": "모르는 사람에게 현장 이름을 말함", "money_said": "금액·계약을 말함",
        "out_of_scope_said": "범위 밖 작업을 말함", "unsupported_answer": "답의 근거가 상대 말에 없음",
        "unsupported_date": "도구 결과에 없는 날짜",
    }


# ── 구조·흐름도의 call_placed ───────────────────────────────────────


def _flags(body: dict) -> list[list[str]]:
    keep = {"outreach_delegated", "outreach_blocked", "call_placed"}
    return [[f for f in (t.get("signals") or []) if f in keep] for t in body["timeline"] if t["kind"] == "tool"]


def test_call_placed_lights_only_after_dialing(client, admin, session, who):
    sid, contact = who
    placed = _call(session, schedule_id=sid, contact_id=contact, status="completed", claimed_at=NOW)
    _record(session, placed.id, "channel_choice", "allowed", "call")
    _record(session, placed.id, "recheck_before_dial", "allowed", "ok")
    waiting = _call(session, schedule_id=sid, contact_id=contact, status="queued", claimed_at=NOW)
    _record(session, waiting.id, "channel_choice", "allowed", "call")
    stopped = _call(session, schedule_id=sid, contact_id=contact, status="blocked_test")
    _record(session, stopped.id, "channel_choice", "allowed", "call")
    _record(session, stopped.id, "recheck_before_dial", "blocked", "test_mode")
    prep = _call(session, schedule_id=sid, contact_id=contact, status="failed")  # 차지한 뒤 준비 오류 — 걸지 않음
    _record(session, prep.id, "recheck_before_dial", "allowed", "ok")
    _record(session, prep.id, "recheck_before_dial", "blocked", "local_error")

    assert _detail(client, admin, placed.id)["branches_lit"] == ["call_placed"]
    for row in (waiting, stopped, prep):
        assert _detail(client, admin, row.id)["branches_lit"] == []

    queued = out(outcome="queued", message="줄에 넣었습니다", scheduled_at=None)
    body = get_turn(client, admin, signal_turn(session, [
        {"tool": "notify.place_call", "input_json": out(call_id=placed.id), "output_json": queued},
        {"tool": "notify.place_call", "input_json": out(call_id=waiting.id), "output_json": queued},
        {"tool": "notify.place_call", "input_json": out(call_id=stopped.id), "output_json": queued},
        {"tool": "notify.place_call", "input_json": out(call_id=99999), "output_json": queued},
    ]))
    assert _flags(body) == [["outreach_delegated", "call_placed"], ["outreach_delegated"], ["outreach_blocked"],
                            ["outreach_delegated"]]
    lit = set(body["structure"]["edges_lit"])
    assert {"call_placed", "outreach_delegated", "outreach_blocked"} <= lit

    only_stopped = get_turn(client, admin, signal_turn(session, [
        {"tool": "notify.place_call", "input_json": out(call_id=stopped.id), "output_json": queued}]))
    assert _flags(only_stopped) == [["outreach_blocked"]]
    assert "outreach_delegated" not in only_stopped["structure"]["edges_lit"]
    assert "call_placed" not in only_stopped["structure"]["edges_lit"]


# ── 시스템 진단의 AI 전화 ───────────────────────────────────────────


def test_health_voice_reports_model_and_worker_without_key(client, admin, session, monkeypatch):
    _no_rerun(monkeypatch)
    conn = _connection(session)
    step = {"label": "걸음", "notes": [VOICE_KEY], "data": {}, "ran_at": NOW.isoformat(), "pending": False,
            "maybe_sent": False}
    session.add(VoiceSettings(
        connection_id=conn.id, provider="google", model="", secret_ciphertext=encrypt(VOICE_KEY), secret_last4="4321",
        agent_number=SENTINEL_DIGITS, status="ok", checked_at=NOW,
        last_diagnosis_json={"state": "done", "part": "call", "ran_at": NOW.isoformat(), "by": "김하늘", "real": True,
                             "calls": [{"at": NOW.isoformat(), "by": "김하늘", "outcome": "unknown"}], "steps": [
            {**step, "id": "P5", "ok": True, "skipped": False, "code": "ok", "detail": f"연결됨 {VOICE_KEY}"},
            {**step, "id": "P6", "ok": False, "skipped": False, "code": "cut_unconfirmed", "maybe_sent": True,
             "detail": f"끊김 확인 안 됨 {SENTINEL_PHONE}"},
            {**step, "id": "P11", "ok": False, "skipped": False, "code": "key_refused", "detail": "구글이 거절"},
            {**step, "id": "P12", "ok": False, "skipped": True, "code": "skipped", "detail": ""}]}))
    session.commit()
    at = datetime(2026, 11, 24, 2, 3, 4, tzinfo=UTC)
    monkeypatch.setattr(runner, "_state", runner._State(running=True, last_call_at=at, last_error_kind="TimeoutError",
                                                        live={7: object()}))
    monkeypatch.setattr(runner, "_backend_state", lambda: "ok")

    voice = client.get("/api/devconsole/health", headers=admin).json()["notify"]["voice"]
    assert (voice["provider"], voice["model"], voice["status"]) == ("google", "gemini-3.8-live", "ok")
    assert voice["checked_at"] is not None
    assert isinstance(voice["sdk_installed"], bool)
    diag = voice["last_diagnosis"]
    assert [(s["id"], s["outcome"]) for s in diag["steps"]] == [
        ("P5", "ok"), ("P6", "check"), ("P11", "failed"), ("P12", "skipped")]
    assert diag["steps"][2]["code"] == "key_refused"
    w = voice["worker"]
    assert (w["running"], w["live"], w["backend"], w["last_error_kind"]) == (True, 1, "ok", "TimeoutError")
    assert datetime.fromisoformat(w["last_call_at"]) == at
    text = "\n".join(_walk(voice))
    assert not _leaks(text, (VOICE_KEY,)), _leaks(text, (VOICE_KEY,))
    assert VOICE_KEY not in text and "4321" not in text and "last4" not in text and "김하늘" not in text


# ── 사용량 ──────────────────────────────────────────────────────────


def test_usage_call_minutes_and_model_usage_cost_only_if_reported(client, admin, session):
    _call(session, status="completed", claimed_at=NOW, duration_s=120)
    unsure = _call(session, status="failed", claimed_at=NOW, duration_s=30)
    _record(session, unsure.id, "delivery", "noted", "결과 모름")
    _call(session, status="draft")  # 차지하지 않은 줄은 세지 않는다
    session.add_all([
        OutreachUsage(at=NOW, kind="voice_model", model="gemini-3.8-live", seconds=120),
        OutreachUsage(at=NOW, kind="summary", model="m", input_tokens=200, output_tokens=50, cost=0.001),
        OutreachUsage(at=NOW, kind="summary", model="m", input_tokens=100, output_tokens=20, cost=None),
    ])
    session.commit()

    def calls() -> dict:
        return client.get("/api/devconsole/usage?days=7", headers=admin).json()["outreach"]["calls"]

    body = calls()
    assert (body["call_seconds"], body["calls_placed"]) == (150, 2)  # 결과를 모르는 통화도 건 통화로 센다 — 실패 셈은 없다
    assert set(body) == {"call_seconds", "calls_placed", "models"}
    assert body["models"] == [
        {"kind": "voice_model", "count": 1, "seconds": 120, "input_tokens": 0, "output_tokens": 0, "cost": None},
        {"kind": "summary", "count": 2, "seconds": 0, "input_tokens": 300, "output_tokens": 70, "cost": 0.001},
    ]  # 받아쓰기는 기록이 없어 줄이 없다 · 요금은 알려 준 것만
    session.add(OutreachUsage(at=NOW, kind="transcription", seconds=40))
    session.commit()
    assert [m["kind"] for m in calls()["models"]] == ["voice_model", "transcription", "summary"]


# ── 받아쓰기 글·번호·키 ─────────────────────────────────────────────


def test_transcript_text_is_not_in_console_response(client, admin, session, who, monkeypatch):
    _no_rerun(monkeypatch)
    sid, contact = who
    conn = _connection(session)
    session.add(VoiceSettings(connection_id=conn.id, provider="google", secret_ciphertext=encrypt(VOICE_KEY),
                              secret_last4="4321", agent_number=SENTINEL_DIGITS))
    session.commit()
    call = _call(session, schedule_id=sid, contact_id=contact, status="completed", claimed_at=NOW, duration_s=60,
                 peer_number=SENTINEL_DIGITS, summary_ko=SUMMARY, result_proposed=SUMMARY,
                 answers_json=[{"question": "q", "answer": TRANSCRIPT, "quote": TRANSCRIPT, "quote_found": True}],
                 transcript_json=[{"role": "peer", "text": TRANSCRIPT, "t": 1}, {"role": "peer", "text": SPOKEN_NUMBER, "t": 2}])
    _record(session, call.id, "recheck_before_dial", "allowed", "ok")
    _record(session, call.id, "tool:take_message", "allowed", TRANSCRIPT)
    session.add(OutreachUsage(at=NOW, kind="voice_model", ref_kind="call", ref_id=call.id, seconds=60))
    session.commit()
    turn = signal_turn(session, [{"tool": "notify.place_call", "input_json": out(call_id=call.id),
                                  "output_json": out(outcome="queued", message="줄에 넣었습니다", scheduled_at=None)}])

    bodies = [
        client.get("/api/devconsole/outreach?kind=call", headers=admin).json(),
        _detail(client, admin, call.id),
        client.get("/api/devconsole/health", headers=admin).json()["notify"],
        client.get("/api/devconsole/usage?days=7", headers=admin).json()["outreach"],
    ]
    assert bodies[1]["head"]["transcript_lines"] == 2
    for body in bodies:
        text = "\n".join(_walk(body))
        assert not _leaks(text, (VOICE_KEY,)), _leaks(text, (VOICE_KEY,))
        for secret in ("TRANSCRIPT-SENTINEL", "SUMMARY-SENTINEL", "제 번호는", VOICE_KEY, "4321", SENTINEL_DIGITS):
            assert secret not in text
    turn_text = json.dumps(get_turn(client, admin, turn), ensure_ascii=False)
    assert "TRANSCRIPT-SENTINEL" not in turn_text and "제 번호는" not in turn_text
