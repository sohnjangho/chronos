"""개발 콘솔 ①(Task 108): 연락 기록(문자·카카오톡·통화)의 실행 추적 · 시스템 진단의 알림 연결 · 사용량의 문자 수.

읽기만 한다 — 아무것도 바꾸지 않고, 진단·보내기·걸기를 부르지 않는다.

- 사건의 이름과 묶음은 `app.outreach.harness.types` 의 상수(EVENT_GROUPS·GATE_RULES·FIXED_DETAILS …)와
  `events.KNOWN_RULES` 에서만 읽는다. 이 모듈에는 사건 이름 글자를 따로 적지 않는다(시험이 본다) — 한글 이름표는 묶음
  (EVENT_GROUP_KEYS 차례)·문의 차례(GATE_RULES 열쇠)·정해 둔 detail 코드에만 붙인다.
- 내보내지 않는 것: 전화번호(가린 꼴 `010-****-0199` 만), 문자 글·받아쓰기·요약·목적, 키·Account ID, 제공사 id,
  사건의 자유 글(detail·evidence). 사건은 묶음·이름·판정·정해 둔 코드(또는 도구 이름)·차례만 보인다. 사람이 쓴 이름·까닭
  글(origin_name·approved_by·fail_reason)은 번호·비밀을 지운 뒤에 싣는다.
- 상한: 목록은 한 번에 LIST_MAX 줄까지(기본 LIST_DEFAULT, 넘으면 more), 한 줄의 사건은 EVENT_CAP 개까지(넘으면 가장
  최근 것만, 나머지는 omitted 에 센다 — events.MAX_EVENTS 와 같은 값).
- 모양이 틀린 harness_json(목록이 아님·줄이 dict 가 아님·낱말에 없는 이름·판정)은 「알 수 없는 사건」 한 줄이지 500 이 아니다.
- 시도: 한 번의 dispatch 는 「(판정 메모) → 문 판정 하나 → 통로 결과 → 뒤 상태」다. 판정이 이미 있는 시도 뒤에 다시 메모·판정이
  오면 다음 시도다(리뷰 판정 19).
"""

import re
from datetime import datetime
from importlib import import_module
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.outreach import phone, redact
from app.outreach.harness import events
from app.outreach.harness.types import (
    CHANNELS,
    DELIVERY_UPDATES,
    DELIVERY_VERDICT,
    EVENT_GROUP_KEYS,
    EVENT_GROUPS,
    FIXED_DETAILS,
    GATE_NOTES,
    GATE_RULES,
    TOOL_REFUSALS,
)
from app.programs.devconsole import outreach_branches
from app.programs.devconsole.schemas import (
    EventGroupCount,
    HarnessItem,
    HarnessMark,
    NotifyDiagnosisOut,
    NotifyHealthOut,
    NotifyStepOut,
    OutreachDetailOut,
    OutreachHeadOut,
    OutreachListOut,
    OutreachRowOut,
    OutreachUsageOut,
)
from app.security.crypto import SecretUnreadable, decrypt
from app.store import outreach as outreach_store
from app.store import outreach_usage
from app.store.tables import ScheduleRecord
from app.store.tables_outreach import (
    Contact,
    ContactCompany,
    OutreachCall,
    OutreachMessage,
)
from app.store.timeutil import as_utc

LIST_DEFAULT, LIST_MAX = 30, 100
EVENT_CAP = events.MAX_EVENTS
NOT_FOUND_MESSAGE = "연락 기록을 찾을 수 없습니다."
UNKNOWN_KEY = "unknown"  # 모르는 사건의 묶음 열쇠(EVENT_GROUP_KEYS 밖)
UNKNOWN_LABEL = "알 수 없는 사건"
UNCONFIRMED = "unconfirmed"  # 메시지 상태: 보냈는지 확인 필요(이름표)
_ROWS: dict[str, type[OutreachMessage] | type[OutreachCall]] = {"message": OutreachMessage, "call": OutreachCall}
CALL_KIND = "call"  # 통화 줄: kind 도 통로 이름도 call

# ── 낱말 → 한글(묶음·차례·코드에만) ─────────────────────────────────

GROUP_LABELS: dict[str, str] = dict(zip(EVENT_GROUP_KEYS, (
    "나가는 문 판정", "판정 메모", "들어오는 문", "도구", "뒤 확인", "통로 결과", "통화", "문자 답 만들기", "서버 다시 시작",
), strict=True))
ORDER_LABELS: dict[int, str] = dict(zip(sorted(GATE_RULES), (
    "앞 확인", "시험 모드·허용 번호", "차단·수신 거부", "근무시간", "상한", "권한", "중복", "통로 고르기",
), strict=True))
VERDICT_LABELS = {"blocked": "막음", "allowed": "지나감", "noted": "메모"}
DELIVERY_TEXT = {"sent": "보냄", "failed": "보내지 못함", "unsure": "보냈는지 확인 필요"}  # DeliveryState
CODE_TEXT = {  # FIXED_DETAILS 의 코드(통로·받기 까닭·통화 결과·뒤 상태)
    "sms": "문자", "kakao": "카카오톡", "call": "전화",
    "inbound_off": "받는 범위가 「받지 않음」", "outside_test": "시험 모드 — 허용 번호 아님", "blocked_number": "차단 번호",
    "burst_limit": "잦은 연락 상한", "auto_reply_limit": "자동 답 상한", "stop_word": "수신 거부 말",
    "machine_text": "기계가 보낸 문자", "media_attached": "사진이 붙음", "do_not_contact": "수신 거부 연락처",
    "unknown_not_accepted": "모르는 번호 — 받지 않음", "unknown_accepted": "모르는 번호 — 응대", "line_busy": "동시 통화 한도",
    "known_caller": "아는 상대 — 응대",
    "no_answer": "받지 않음", "busy": "통화 중", "failed": "실패", "backend_error": "음성 서버 오류",
    "delivered": "도착", "gave_up": "결과 확인을 그만둠",
}

# 묶음·이름을 상수에서 꺼낸다(글자를 적지 않는다)
GATE_GROUP = EVENT_GROUPS[GATE_RULES[0]]
NOTE_GROUP = EVENT_GROUPS[min(GATE_NOTES)]
UPDATE_RULE = next(rule for rule, codes in FIXED_DETAILS.items() if codes is DELIVERY_UPDATES)
RESULT_GROUP = EVENT_GROUPS[UPDATE_RULE]
DELIVERY_RULE = next(r for r, g in EVENT_GROUPS.items() if g == RESULT_GROUP and r not in FIXED_DETAILS)
TOOL_GROUP = EVENT_GROUPS[min(TOOL_REFUSALS)]
CHOICE_RULE = GATE_RULES[max(GATE_RULES)]
_RULE_ORDER = {name: order for order, name in GATE_RULES.items()}
_DELIVERY_STATE = {verdict: state for state, verdict in DELIVERY_VERDICT.items()}
_OMITTED = re.compile(r"\D*(\d+)\D*")
_TOOL_HEAD = "tool"


def group_of(rule: object) -> str | None:
    """사건 이름의 묶음(EVENT_GROUPS). 낱말에 없으면 None."""
    return EVENT_GROUPS.get(rule) if isinstance(rule, str) and rule in events.KNOWN_RULES else None


def _clean(text: object) -> str | None:
    """사람이 쓴 이름·까닭 글: 번호와 등록된 비밀을 지운다. 지우지 못하면 싣지 않는다."""
    if not isinstance(text, str):
        return None
    try:
        return redact.scrub(text, redact.secrets())
    except Exception:  # noqa: BLE001 — 지우기가 무엇으로 실패하든 원문을 내보내지 않는다
        return events.HIDDEN_TEXT


# ── 사건 → 시간표 줄 ────────────────────────────────────────────────


def _tool_name(rule: str, detail: object) -> str | None:
    """도구 사건의 도구 이름(묶음의 이름이거나 "unknown"). 허용은 이름에서, 거절은 detail 머리 `tool=<이름>` 에서."""
    head, _, name = rule.partition(":")
    if head == _TOOL_HEAD and name:
        return name
    if rule in TOOL_REFUSALS and isinstance(detail, str):
        key, _, value = detail.split(" ", 1)[0].partition("=")
        if key == _TOOL_HEAD and (value in events.TOOL_NAMES or value == UNKNOWN_KEY):
            return value
    return None


def _when(value: object, fallback: datetime) -> datetime:
    try:
        return as_utc(datetime.fromisoformat(value)) if isinstance(value, str) else fallback
    except ValueError:
        return fallback


def _mark(event: dict) -> tuple[HarnessMark, str]:
    """알아볼 수 있는 사건 하나의 표지와 보일 이름."""
    rule, verdict, detail = event["rule"], event["verdict"], event.get("detail")
    group = EVENT_GROUPS[rule]
    code = detail if rule in FIXED_DETAILS and isinstance(detail, str) and detail in FIXED_DETAILS[rule] else None
    order = _RULE_ORDER.get(rule)
    needs_check = rule == DELIVERY_RULE and _DELIVERY_STATE.get(verdict) == "unsure"
    verdict_label = VERDICT_LABELS[verdict]
    label = GROUP_LABELS[group]
    if order is not None:
        label = ORDER_LABELS[order]
    if group == TOOL_GROUP:
        code = _tool_name(rule, detail)
        label = f"{'도구 거절' if verdict == 'blocked' else '도구'} {code or UNKNOWN_KEY}"
    elif rule == DELIVERY_RULE:
        verdict_label = DELIVERY_TEXT[_DELIVERY_STATE[verdict]]
        label = f"{label} — {verdict_label}"
    elif code is not None:
        label = f"{label} — {CODE_TEXT.get(code, code)}"
    mark = HarnessMark(group=group, group_label=GROUP_LABELS[group], rule=rule, verdict=verdict,
                       verdict_label="확인 필요" if needs_check else verdict_label, attempt=None, order=order,
                       code=code, needs_check=needs_check, unknown=False)
    return mark, label


def _unknown() -> tuple[HarnessMark, str]:
    return HarnessMark(group=None, group_label=UNKNOWN_LABEL, rule=None, verdict=None, verdict_label="—", attempt=None,
                       order=None, code=None, needs_check=False, unknown=True), UNKNOWN_LABEL


def _known(event: object) -> bool:
    return (isinstance(event, dict) and group_of(event.get("rule")) is not None
            and isinstance(event.get("verdict"), str) and event.get("verdict") in VERDICT_LABELS)


def _omitted(event: object) -> int | None:
    """저장할 때 남긴 「앞선 사건 N개 생략됨」 표식이면 N, 아니면 None."""
    if not (isinstance(event, dict) and event.get("rule") == events.OMITTED):
        return None
    found = _OMITTED.fullmatch(str(event.get("detail") or ""))
    return int(found.group(1)) if found else 0


def _stored_events(value: object) -> tuple[list[object], int]:
    """harness_json → (보일 사건, 보이지 않는 앞선 사건 수). 목록이 아니면 그 값 하나를 모르는 사건으로."""
    if value is None:
        return [], 0
    items = list(value) if isinstance(value, list) else [value]
    omitted = 0
    shown: list[object] = []
    for item in items:
        count = _omitted(item)
        if count is None:
            shown.append(item)
        else:
            omitted += count
    if len(shown) > EVENT_CAP:
        omitted += len(shown) - EVENT_CAP
        shown = shown[-EVENT_CAP:]
    return shown, omitted


def _attempts(marks: list[HarnessMark]) -> int:
    """판정 메모·문 판정·통로 결과에 시도 차례를 매기고 시도 수를 돌려준다."""
    current, decided = 0, False
    for mark in marks:
        if mark.group in (NOTE_GROUP, GATE_GROUP):
            if current == 0 or decided:
                current, decided = current + 1, False
            decided = decided or mark.group == GATE_GROUP
        if mark.group in (NOTE_GROUP, GATE_GROUP, RESULT_GROUP) and current:
            mark.attempt = current
    return current


def _line(event: object, fallback: datetime) -> tuple[HarnessMark, str, datetime]:
    """저장된 사건 하나 → (표지, 보일 이름, 시각). 어떤 꼴이든 여기서 예외가 나가지 않는다 — 만들다 무엇으로 실패하든 그 사건
    하나만 「알 수 없는 사건」이 된다(사건 내용은 남기지도 찍지도 않는다)."""
    try:
        mark, label = _mark(event) if _known(event) else _unknown()
        return mark, label, _when(event.get("at"), fallback) if isinstance(event, dict) else fallback
    except Exception:  # noqa: BLE001 — 모양이 틀린 사건 하나가 응답 전체를 500 으로 만들지 않게
        mark, label = _unknown()
        return mark, label, fallback


def timeline(value: object, fallback: datetime) -> tuple[list[HarnessItem], int, int]:
    """그 줄의 하네스 사건 → (시간표, 시도 수, 보이지 않는 앞선 사건 수). 남긴 차례 그대로(시각으로 다시 늘어놓지 않음)."""
    shown, omitted = _stored_events(value)
    lines = [_line(e, fallback) for e in shown]
    attempts = _attempts([mark for mark, _label, _at in lines])
    items = []
    for seq, (mark, label, at) in enumerate(lines, 1):
        items.append(HarnessItem(
            seq=seq, kind="harness", label=label, started_at=at, ms=None, model=None, input_tokens=0, output_tokens=0,
            cost=None, ok=mark.verdict != "blocked", error=mark.verdict_label if mark.verdict == "blocked" else None,
            input_text="", output_text="", parallel_group=None, harness=mark,
        ))
    return items, attempts, omitted


# ── 목록 · 머리 줄 ──────────────────────────────────────────────────


def _event_count(value: object) -> int:
    shown, _omitted_count = _stored_events(value)
    return len(shown)


def _names(session: Session, rows: list) -> tuple[dict, dict, dict]:
    contact_ids = {r.contact_id for r in rows if r.contact_id is not None}
    contacts = {c.id: c for c in session.scalars(select(Contact).where(Contact.id.in_(contact_ids)))}
    company_ids = {c.company_id for c in contacts.values()}
    companies = {c.id: c.name for c in session.scalars(select(ContactCompany).where(ContactCompany.id.in_(company_ids)))}
    schedule_ids = {r.schedule_id for r in rows if r.schedule_id is not None}
    schedules = dict(session.execute(select(ScheduleRecord.id, ScheduleRecord.name)
                                     .where(ScheduleRecord.id.in_(schedule_ids))).all())
    return contacts, companies, schedules


def _row_fields(kind: str, row, names: tuple[dict, dict, dict]) -> dict[str, Any]:
    contacts, companies, schedules = names
    contact = contacts.get(row.contact_id) if row.contact_id is not None else None
    if contact is not None and contact.schedule_id != row.schedule_id:
        contact = None  # 다른 일정의 연락처 id 가 적힌 줄 — 그 사람으로 보이지 않는다
    number = contact.phone if contact is not None and contact.phone else row.peer_number
    return {
        "kind": kind, "id": row.id, "at": as_utc(row.created_at), "direction": row.direction,
        "channel": CALL_KIND if kind == CALL_KIND else row.channel, "origin": row.origin,
        "origin_name": _clean(row.origin_name) or "", "send_mode": row.send_mode, "caller_class": row.caller_class,
        "status": row.status,
        "contact_name": _clean(contact.name) if contact is not None else None,
        "company_name": _clean(companies.get(contact.company_id)) if contact is not None else None,
        "number_masked": phone.mask(number), "schedule_name": schedules.get(row.schedule_id),
        "events": _event_count(row.harness_json), "needs_check": row.status == UNCONFIRMED,
    }


def list_rows(session: Session, kind: str | None, limit: int) -> OutreachListOut:
    """연락 기록 새것부터(만든 때). kind 를 주면 그 종류만. limit 줄을 넘으면 more."""
    kinds = [kind] if kind is not None else list(_ROWS)
    found: list[tuple[str, Any]] = []
    for name in kinds:
        model = _ROWS[name]
        found += [(name, r) for r in session.scalars(select(model).order_by(model.id.desc()).limit(limit + 1))]
    found.sort(key=lambda pair: (as_utc(pair[1].created_at), pair[1].id), reverse=True)
    more = len(found) > limit
    found = found[:limit]
    names = _names(session, [r for _k, r in found])
    return OutreachListOut(items=[OutreachRowOut(**_row_fields(k, r, names)) for k, r in found], more=more, limit=limit)


def _groups(items: list[HarnessItem]) -> list[EventGroupCount]:
    counts = {key: 0 for key in (*EVENT_GROUP_KEYS, UNKNOWN_KEY)}
    for item in items:
        counts[item.harness.group or UNKNOWN_KEY] += 1
    return [EventGroupCount(key=key, label=GROUP_LABELS.get(key, UNKNOWN_LABEL), count=n) for key, n in counts.items()]


def detail(session: Session, kind: str, row_id: int) -> OutreachDetailOut:
    """연락 기록 하나의 머리 줄과 하네스 시간표. 없는 줄은 404."""
    row = session.get(_ROWS[kind], row_id)
    if row is None:
        raise ApiError(404, "not_found", NOT_FOUND_MESSAGE)
    fields = _row_fields(kind, row, _names(session, [row]))
    head = OutreachHeadOut(**fields, approved_by=_clean(row.approved_by), fail_reason=_clean(row.fail_reason),
                           reply_to_id=getattr(row, "reply_to_id", None))
    items, attempts, omitted = timeline(row.harness_json, fields["at"])
    return OutreachDetailOut(head=head, timeline=items, groups=_groups(items), attempts=attempts,
                             needs_check=sum(i.harness.needs_check for i in items), omitted=omitted,
                             flow=outreach_branches.flow(items), branches_lit=outreach_branches.branches(session, kind, row))


# ── 시스템 진단 · 사용량 ────────────────────────────────────────────


def _worker_status() -> dict | None:
    """연락 일꾼(Task 71)의 메모리 상태. 일꾼 모듈이 없는 판에서는 None."""
    try:
        worker = import_module("app.outreach.worker")
    except ImportError:
        return None
    return worker.status()


def _conn_secrets(conn) -> list[str]:
    values = [conn.account_id]
    try:
        values.append(decrypt(conn.secret_ciphertext))
    except SecretUnreadable:
        pass
    return values


def _step(raw: object, secrets: list[str]) -> NotifyStepOut | None:
    if not isinstance(raw, dict):
        return None

    def text(key: str) -> str:
        value = raw.get(key)
        return redact.scrub(value, secrets) if isinstance(value, str) else ""

    ok, skipped = raw.get("ok") is True, raw.get("skipped") is True
    maybe_sent, pending = raw.get("maybe_sent") is True, raw.get("pending") is True
    outcome = "skipped" if skipped else "ok" if ok else "check" if (maybe_sent or pending) else "failed"
    return NotifyStepOut(id=text("id")[:10], label=text("label"), ok=ok, skipped=skipped, detail=text("detail"),
                         code=text("code"), maybe_sent=maybe_sent, pending=pending, outcome=outcome)


def _diagnosis(conn) -> NotifyDiagnosisOut | None:
    """저장된 마지막 연결 진단(다시 돌리지 않는다). 걸음 글은 연결의 키·Account ID·번호를 한 번 더 지운다."""
    stored = conn.last_diagnosis_json
    if not isinstance(stored, dict):
        return None
    ran_at = _when(stored.get("ran_at"), None)
    if ran_at is None:
        return None
    secrets = [*redact.secrets(), *_conn_secrets(conn)]
    raw_steps = stored.get("steps") if isinstance(stored.get("steps"), list) else []
    steps = [s for s in (_step(r, secrets) for r in raw_steps) if s is not None]
    state = stored.get("state") if stored.get("state") in ("done", "sending") else "done"
    return NotifyDiagnosisOut(ran_at=ran_at, state=state, steps=steps)


def notify_health(session: Session) -> NotifyHealthOut:
    conn = outreach_store.connection(session)
    if conn is None:
        return NotifyHealthOut(connected=False)
    unsure = session.scalar(select(func.count(OutreachMessage.id)).where(OutreachMessage.status == UNCONFIRMED)) or 0
    allow = conn.allow_numbers_json if isinstance(conn.allow_numbers_json, list) else []
    return NotifyHealthOut(
        connected=True, status=conn.status, checked_at=as_utc(conn.checked_at) if conn.checked_at else None,
        test_mode=conn.test_mode, allow_count=len(allow),
        sender_masked=phone.mask(conn.sender_number) if conn.sender_number else None, inbound_mode=conn.inbound_mode,
        agent=dict(zip(CHANNELS, (conn.agent_sms, conn.agent_kakao, conn.agent_call), strict=True)),
        worker=_worker_status(), needs_check=unsure, last_diagnosis=_diagnosis(conn),
    )


def usage(session: Session, days: int) -> OutreachUsageOut:
    s = outreach_usage.summary(session, days=days)
    return OutreachUsageOut(sms=s.sms, long=s.long, kakao=s.kakao, auto_replies=s.auto_replies,
                            provider_cost=s.provider_cost, text_models=outreach_branches.text_models(s))
