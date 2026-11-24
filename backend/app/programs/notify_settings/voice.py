"""음성 설정 API와 음성 진단 길(계획 4 Task 90). 계약: .superpowers/sdd/2026-11-23-chronos-plan-4-contacts/task-90-contract.md.

- 음성 모델 키는 암호문과 끝 4자리만 저장하고, 저장한 뒤와 진단에서 풀어 쓰기 전에 로그 거르개에 올린다. 키를 바꾸거나 지우면
  옛 키는 다른 음성 설정·알림 연결이 쓰지 않을 때만 내린다. AI 전화 번호는 정리한 꼴로 저장하고 가린 꼴로만 내보낸다.
- 진단은 Task 60 의 `diagnostics_voice.run_voice_checks` 를 **저장된** 값으로 부른다(모듈 속성으로 — 시험이 바꿔 끼운다).
  한 요청은 한 종류만: 연결(P5·P9·P11) / 통화(P6~P8·P10) / 받는 통화(P12~P14). 통화·받는 통화는 P5·P11 을 같은 연결에서 함께 돌린다.
- **실제 전화는** `call` 이 진짜 참일 때만, 이 연결의 첫 허용 번호로만(요청에 번호 칸이 없다), 그 번호가 걸 수 있고 확인한 목록 판이
  지금 목록과 같을 때만 건다. 걸기 전에 `last_diagnosis_json` 에 「거는 중」 기록(state "calling")과 통화 기록(`calls`, 최근 20개,
  번호 없음)을 남기고 끝나면 결과로 바꾼다. 마지막 통화의 결과를 모르고 10분이 안 됐으면 `confirm_recall` 없이는 다시 걸지 않는다.
- 연결마다 진단 하나 — 연결 진단(P1~P4)과도 겹치지 않게 같은 표시(`diagnose._RUNNING`)를 쓴다. 표시는 끝·실패·끊김 모두에서 지운다.
- 걸음은 덩어리마다 따로 부르고 덩어리마다 시간 상한(`_ceiling` — 진단 모듈의 상한을 더한 값)을 건다. 상한에 걸려도 **끝난 덩어리**의
  걸음은 실제 결과로 남는다. 상한에 걸린 덩어리의 걸음은 실패가 아니라 「확인하지 못함」(`pending`)이고 상태(`status`)를 바꾸지 않는다.
  건 통화의 끝이 확인되지 않았으면 「모름」으로 남긴다. 다시 걸어 보지 않는다.
- 「마지막 시험 전화의 결과를 모름」(`call_unknown`)은 저장하지 않고 통화 기록의 마지막 줄에서만 읽는다(`_unknown`) — 화면의 경고와 409 가
  어긋나지 않게. 끝나지 못하고 남은 「거는 중」은 `_closed` 한 곳에서 「모름」으로 닫는다(읽을 때·다음 진단이 저장할 때·요청이 끊겼을 때).
- SDK 를 부르는 동안 DB 트랜잭션을 쥐지 않는다(부르기 전에 끝내고, 부른 뒤 줄을 다시 읽어 쓴다). DB 일은 스레드에서 한다.
- 결과 글은 한 번 더 지운다(키·Account ID·번호). 아무것도 설치하지 않는다 — SDK 가 없으면 진단 모듈의 P5 가 그 까닭을 낸다.
"""

import asyncio
import importlib.util
import re
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.db import get_session
from app.errors import ApiError
from app.notify import diagnostics, diagnostics_voice, live_models, voice_names
from app.outreach import phone, provider, redact
from app.outreach.voice import inbound, numbers, runner, voices
from app.programs.notify_settings import diagnose, service
from app.programs.notify_settings.voice_schemas import (
    SLOT_FIELDS,
    WAIT_DEFAULT,
    WAIT_MIN,
    CallRecord,
    KeyNotice,
    VoiceDiagnoseIn,
    VoiceDiagnosisOut,
    VoiceModelsOut,
    VoiceOut,
    VoiceStepOut,
    VoiceUpdate,
    _checked,
    _too_long,
)
from app.security import crypto
from app.security.deps import require_admin
from app.store.tables import User
from app.store.tables_outreach import NotifyConnection, VoiceSettings

router = APIRouter(prefix="/api/notify", tags=["notify"])
SessionDep = Annotated[Session, Depends(get_session)]
AdminOnly = Depends(require_admin)

PARTS = {"connection": frozenset({5, 9, 11}), "call": frozenset({6, 7, 8, 10}), "inbound": frozenset({12, 13, 14})}
DEFAULT_STEPS = {"connection": (5, 9, 11), "call": (6, 7, 8), "inbound": (12, 13, 14)}
FIRST_CHUNK = {"call": frozenset({6, 7, 8}), "inbound": frozenset({12, 13})}  # 나머지(P10 · P14)는 둘째 덩어리
LINK = frozenset({5, 11})  # 통화·받는 통화 요청의 첫 덩어리에 함께 도는 걸음
RANG = frozenset(code for code, _ in diagnostics_voice.REASONS.values())  # 걸렸고 끝난 통화(받지 않음·통화 중 …)
HALTED = ("cut_unconfirmed", "accepted_not_started")  # 앞 통화의 끝이 확인되지 않음 — 다음 덩어리를 돌리지 않는다
RECALL_WINDOW = timedelta(minutes=10)
CALLS_KEPT = 20
MARGIN_S = 10
# 음성 칸의 이름표(화면과 같은 말) — 진단 결과에는 음성 이름이 아니라 이 이름표가 실린다(Task 99 고침 1)
SLOT_LABELS = {"voice_male_contact": "남성 연락처에게 걸 때", "voice_female_contact": "여성 연락처에게 걸 때",
               "voice_unknown": "성별 모름"}
LANGUAGE_NAMES = {"ko": "한국어", "en": "영어", "zh": "중국어", "vi": "베트남어"}
SDK_TOP = diagnostics_voice.SDK_MODULE.split(".")[0]
FREE_TIER_NOTICE = ("무료 등급 키로 한 통화의 내용은 구글의 제품 개선에 쓰일 수 있습니다. 실제 협력사와 통화하기 전에 유료 등급 키로 "
                    "바꿔 주세요.")
RUNNING = "이 연결의 진단이 이미 돌고 있습니다. 끝난 뒤 다시 해 주세요."
RECALL = ("앞서 건 시험 전화가 걸렸는지·끊겼는지 아직 모릅니다. 휴대전화를 먼저 확인해 주세요(통화 중이면 끊어 주세요). "
          "확인한 뒤에도 다시 걸려면 다시 걸기를 골라 주세요.")
VERSION_NEEDED = "시험 전화와 받는 통화 확인에는 허용 번호 목록 판(allow_numbers_version)을 함께 보내 주세요."
TIMED_OUT = "시간 안에 끝나지 않아 결과를 확인하지 못했습니다."
MODEL_UNUSABLE = "AI 음성 모델 〈{model}〉을 이 키로 쓸 수 없습니다 — 모델을 다시 골라 주세요"
NOT_FINISHED = ("전화가 걸렸는지·끊겼는지 알 수 없음 — 요청이 끝나지 않은 채 남았습니다. 휴대전화를 확인해 주세요"
                "(통화 중이면 끊어 주세요).")
_WORD = re.compile(r"[a-z_]{1,40}")
_VOICE_RUNNING: dict[int, dict] = {}  # 음성 진단이 도는 연결 id → {part, at, by}(이 프로세스)


@dataclass(frozen=True)
class _Prep:
    """진단 한 번에 쓸 값(평문 키·번호는 이 요청 동안만 — repr 에는 싣지 않는다)."""

    part: str
    chunks: tuple[tuple[int, ...], ...]
    wait: int
    conn: diagnostics.DiagnosticConn
    voice: diagnostics_voice.VoiceDiag
    agent_number: str | None = field(repr=False)
    call_to: str | None = field(repr=False)


# ── 고리 둘: SDK 가 있는가 · 일꾼이 붙어 있는가 ──────────────────────


def sdk_installed() -> bool:
    """음성 SDK 가 설치돼 있는가. 불러오지 않고 꼭대기 이름만 찾는다(SDK 는 불러올 때 준비 표시 파일을 건드린다)."""
    try:
        return importlib.util.find_spec(SDK_TOP) is not None
    except (ImportError, ValueError):
        return False


def worker_connected(agent_number: str | None) -> bool:
    """음성 일꾼이 이 번호로 플랫폼에 붙어 있는가(control 연결은 번호당 하나 — 붙어 있으면 진단이 연결하지 않는다).
    거는 통화 일꾼(Task 88)이 걸기 직전부터 통화가 끝날 때까지 쥔 것을 닫힌 쪽(번호와 상관없이)으로 답한다. 반대로 일꾼은
    이 모듈의 _VOICE_RUNNING(진단이 도는 동안)을 보고 걸지 않는다. 같은 프로세스 안에서만 보인다."""
    return runner.holds_line(agent_number)


def _ceiling(steps: tuple[int, ...], wait: int) -> float:
    """덩어리 하나의 시간 상한(초): 진단 모듈이 스스로 지키는 상한(연결·통화·기다림·끊기·닫기)을 더한 값 + 여유."""
    # 끊기(SDK 는 5초까지 소리를 마저 보낸다) · 끝 사건 · 그래도 끝이 확인되지 않으면 REST 로 끝내기
    cut = diagnostics_voice.SDK_HANGUP_S + diagnostics_voice.END_GRACE_S + diagnostics_voice.REST_END_S
    total = diagnostics.RESOLVE_TIMEOUT_S + diagnostics_voice.CONNECT_TIMEOUT_S  # 이름 풀이 + 연결
    total += cut + diagnostics_voice.HANGUP_TIMEOUT_S + MARGIN_S  # 닫기(살아 있는 통화 끊기 + 연결 끊기) + 여유
    wanted = set(steps)
    if wanted & PARTS["call"]:
        total += diagnostics_voice.CALL_CUT_S + cut
    if wanted & FIRST_CHUNK["inbound"]:
        total += wait + diagnostics_voice.INBOUND_START_S + diagnostics_voice.INBOUND_HOLD_S + cut
    if 14 in wanted:
        total += wait + diagnostics_voice.REJECT_GRACE_S + cut
    if 9 in wanted:
        total += voice_names.BUDGET_S  # 설정한 음성을 하나씩 열고 닫는다(전화 없음)
    return total


STALE_CALL_S = 2 * _ceiling((6,), WAIT_DEFAULT) + 60  # 끝나지 않은 「거는 중」 기록을 「모름」으로 읽기까지(통화 두 통의 상한 + 여유)
CALL_LIMITS = {"calls_per_request": 2, "ring_seconds": diagnostics_voice.RING_TIMEOUT_S,
               "call_seconds": diagnostics_voice.CALL_CUT_S, "inbound_wait_default": WAIT_DEFAULT,
               "inbound_wait_min": WAIT_MIN, "inbound_wait_max": diagnostics_voice.MAX_WAIT_INBOUND_S}


# ── 설정: 검사·저장·보이기 ───────────────────────────────────────────


def _plain(ciphertext: str | None) -> str | None:
    try:
        return crypto.decrypt(ciphertext) if ciphertext else None
    except crypto.SecretUnreadable:
        return None


def _apply(row: VoiceSettings, values: dict, old_key: str | None) -> None:
    """검사한 값을 줄에 적는다. 공급자·키·모델·AI 전화 번호가 실제로 바뀌면 상태와 진단 걸음 줄을 비운다(통화 기록은 남긴다)."""
    target, new_key, reset = values.get("provider", row.provider), values.get("secret"), False
    if target != row.provider:
        if new_key is None and target != "dashboard":
            raise ApiError(422, "secret_required", "공급자를 바꾸면 음성 모델 키를 다시 넣어 주세요.")
        row.provider, reset = target, True
        if new_key is None:
            row.secret_ciphertext, row.secret_last4 = None, ""
    if new_key is not None and new_key != old_key:
        row.secret_ciphertext, row.secret_last4, reset = crypto.encrypt(new_key), new_key[-4:], True
    for name in ("model", "agent_number"):
        if name in values and values[name] != getattr(row, name):
            setattr(row, name, values[name])
            reset = True
    for slot in SLOT_FIELDS:
        if slot in values:
            setattr(row, slot, values[slot])
    if "voices_by_language" in values:
        row.voices_by_language_json = values["voices_by_language"]
    if reset:
        row.status, row.checked_at = "unknown", None
        if isinstance(row.last_diagnosis_json, dict):
            row.last_diagnosis_json = {**row.last_diagnosis_json, "steps": []}


def _drop_unused(session: Session, old: str | None) -> None:
    """옛 음성 키를 로그 거르개에서 내린다 — 다른 음성 설정·알림 연결이 같은 값을 쓰지 않을 때만."""
    if not old:
        return
    in_use = {_plain(row.secret_ciphertext) for row in session.scalars(select(VoiceSettings))}
    for conn in session.scalars(select(NotifyConnection)):
        in_use |= {conn.account_id, _plain(conn.secret_ciphertext)}
    session.rollback()
    if old not in in_use:
        redact.drop_secrets(old)


def save(session: Session, conn_id: int, data: VoiceUpdate) -> VoiceOut:
    """보낸 칸만 고친다(처음이면 줄을 만든다). 읽고-고치고-쓰기는 쓰기 트랜잭션 하나, 진단이 도는 동안은 받지 않는다."""
    service.get(session, conn_id)
    values = _checked(data)
    service.begin_write(session)
    try:
        conn = service.get(session, conn_id, fresh=True)
        if conn_id in diagnose._RUNNING:
            raise ApiError(409, "diagnosis_running", RUNNING)
        row = session.get(VoiceSettings, conn_id, populate_existing=True)
        if row is None:
            row = VoiceSettings(connection_id=conn_id, provider="google", secret_last4="", model="",
                                voices_by_language_json={}, status="unknown")
            session.add(row)
        old_key = _plain(row.secret_ciphertext)
        _apply(row, values, old_key)
    except ApiError:
        session.rollback()
        raise
    session.commit()
    new_key = _plain(row.secret_ciphertext)
    redact.add_secrets(new_key)
    shown = _out(conn, row)
    if new_key != old_key:
        _drop_unused(session, old_key)
    return shown


def _out(conn: NotifyConnection, row: VoiceSettings | None) -> VoiceOut:
    number = row.agent_number if row is not None else None
    effective = numbers.effective_agent_number(conn, row)
    allow = list(conn.allow_numbers_json or [])
    name = row.provider if row is not None else "google"
    by_language = row.voices_by_language_json if row is not None else None
    return VoiceOut(
        connection_id=conn.id, provider=name, has_secret=bool(row is not None and row.secret_ciphertext),
        secret_last4=row.secret_last4 if row is not None and row.secret_ciphertext else "",
        model=row.model if row is not None else "",
        agent_number_masked=phone.mask(number) if number else None,
        agent_number_kind=(phone.kind(number) or "") if number else "",
        **{slot: getattr(row, slot) if row is not None else None for slot in SLOT_FIELDS},
        voices_by_language={lang: {s: v for s, v in slots.items() if isinstance(v, str)}
                            for lang, slots in (by_language if isinstance(by_language, dict) else {}).items()
                            if isinstance(slots, dict)},
        status=row.status if row is not None else "unknown", checked_at=row.checked_at if row is not None else None,
        sdk_installed=sdk_installed(), test_call_index=0 if allow and phone.can_call(allow[0]) and effective else None,
        key_notice=KeyNotice(code="google_free_tier", message=FREE_TIER_NOTICE) if name == "google" else None,
        call_limits=CALL_LIMITS, saved=row is not None,
        model_effective=numbers.effective_model(name, row.model if row is not None else "") or "",
        agent_number_effective_masked=phone.mask(effective) if effective else None,
        agent_number_source=numbers.agent_number_source(conn, row),
    )


def remove(session: Session, conn_id: int) -> None:
    """음성 설정 줄과 그 키를 지운다(없으면 그대로). 진단이 도는 동안은 받지 않는다. 키는 다른 곳이 쓰지 않을 때만 거르개에서 내린다."""
    service.get(session, conn_id)
    service.begin_write(session)
    if conn_id in diagnose._RUNNING:
        session.rollback()
        raise ApiError(409, "diagnosis_running", RUNNING)
    row = session.get(VoiceSettings, conn_id, populate_existing=True)
    old_key = _plain(row.secret_ciphertext) if row is not None else None
    if row is not None:
        session.delete(row)
    session.commit()
    _drop_unused(session, old_key)


def models(session: Session, conn_id: int) -> VoiceModelsOut:
    """저장된 구글 키로 쓸 수 있는 Live 모델(요청 한 번). 구글 키가 없거나 읽지 못하면 고정 목록과 까닭. DB 는 부르기 전에 놓는다."""
    service.get(session, conn_id)
    row = session.get(VoiceSettings, conn_id)
    key = _plain(row.secret_ciphertext) if row is not None and row.provider == "google" else None
    session.rollback()
    found = live_models.list_live_models(key)
    return VoiceModelsOut(models=list(found.models), default=numbers.DEFAULT_LIVE_MODEL, fallback=found.fallback,
                          refused=found.refused, no_live=found.no_live, reason=found.reason)


# ── 진단: 걸기 전 검사·기록 ──────────────────────────────────────────


def _plan(data: VoiceDiagnoseIn) -> tuple[str, tuple[tuple[int, ...], ...]]:
    """요청 하나가 돌릴 종류와 덩어리. 걸거나 받는 걸음은 그 깃발이 진짜 참일 때만 든다."""
    if data.call and data.inbound:
        raise ApiError(422, "one_part_only", "시험 전화와 받는 통화 확인은 한 번에 하나만 할 수 있습니다.")
    part = "call" if data.call is True else "inbound" if data.inbound is True else "connection"
    picked = {int(step[1:]) for step in data.steps} if data.steps else set(DEFAULT_STEPS[part])
    outside = sorted(picked - PARTS[part])
    if outside:
        raise ApiError(422, "steps_not_in_part", "고른 걸음은 이 진단에서 돌릴 수 없습니다.",
                       {"steps": [f"P{n}" for n in outside]})
    if not WAIT_MIN <= data.wait_inbound_s <= diagnostics_voice.MAX_WAIT_INBOUND_S:
        raise ApiError(422, "invalid_wait", f"기다릴 시간은 {WAIT_MIN}초에서 {diagnostics_voice.MAX_WAIT_INBOUND_S}초 "
                                            "사이여야 합니다.")
    if part == "connection":
        return part, (tuple(sorted(picked)),)
    if picked & {7, 8}:
        picked.add(6)  # P7·P8 은 P6 과 한 통화다
    chunks = [c for c in (picked & FIRST_CHUNK[part], picked - FIRST_CHUNK[part]) if c]
    chunks[0] = chunks[0] | LINK
    return part, tuple(tuple(sorted(c)) for c in chunks)


def _call_target(conn: NotifyConnection, row: VoiceSettings, data: VoiceDiagnoseIn) -> str:
    """걸 번호(받는 통화에서는 받아 줄 번호) — 확인한 목록의 첫 허용 번호뿐. 걸 수 없으면 ApiError(아무것도 돌리기 전)."""
    allow = list(conn.allow_numbers_json or [])
    if not allow:
        raise ApiError(422, "no_allow_numbers", "허용 번호를 먼저 넣어 주세요")
    version = data.allow_numbers_version
    # 판은 ASCII 글이다 — 다른 글자가 섞인 값은 견주기 전에 「바뀜」으로 다룬다(hmac.compare_digest 는 ASCII 만 받는다)
    service.check_allow_version(conn, version if version is None or version.isascii() else "", VERSION_NEEDED)
    if not phone.can_call(allow[0]):
        raise ApiError(422, "test_number_not_callable", "첫 허용 번호가 전화를 걸 수 없는 번호입니다.")
    if not numbers.effective_agent_number(conn, row):
        raise ApiError(422, "no_agent_number", "AI 전화 번호를 먼저 넣어 주세요.")
    return allow[0]


def _settings(session: Session, conn_id: int, *, fresh: bool = False) -> VoiceSettings:
    row = session.get(VoiceSettings, conn_id, populate_existing=fresh)
    if row is not None and row.provider == "dashboard":
        raise ApiError(422, "voice_provider_not_supported", "대시보드 에이전트 방식은 음성 진단을 하지 않습니다.")
    if row is None or not row.secret_ciphertext:
        raise ApiError(422, "voice_key_required", "음성 모델 키를 먼저 넣어 주세요.")
    return row


def _configured_voices(row: VoiceSettings) -> tuple[tuple[str, str], ...]:
    """설정한 음성 (칸 이름표, 음성 이름): 세 칸, 그다음 언어별(언어 차례). 꼴이 맞는 이름만."""
    found = [(label, getattr(row, slot)) for slot, label in SLOT_LABELS.items() if voices.well_formed(getattr(row, slot))]
    by_language = row.voices_by_language_json if isinstance(row.voices_by_language_json, dict) else {}
    for code in sorted(by_language):
        slots = by_language[code] if isinstance(by_language[code], dict) else {}
        found += [(f"{LANGUAGE_NAMES.get(code, code)} · {label}", slots[slot]) for slot, label in SLOT_LABELS.items()
                  if voices.well_formed(slots.get(slot))]
    return tuple(found)


def _prepare_sync(session: Session, conn_id: int, data: VoiceDiagnoseIn) -> _Prep:
    conn = service.get(session, conn_id)
    if len(data.allow_numbers_version or "") > service.MAX_CHARS["allow_numbers_version"]:
        raise _too_long("allow_numbers_version", service.MAX_CHARS["allow_numbers_version"])
    part, chunks = _plan(data)
    row = _settings(session, conn_id)
    call_to = _call_target(conn, row, data) if part != "connection" else None
    key = service.stored_key(conn)
    voice_key = _plain(row.secret_ciphertext)
    if voice_key is None:
        raise ApiError(409, "voice_secret_unreadable", "저장된 음성 모델 키를 읽을 수 없습니다. 키를 다시 넣어 주세요.")
    provider.register_secrets(key, conn.account_id)  # 풀자마자, SDK 를 건드리기 전에 로그 거르개에 올린다
    redact.add_secrets(voice_key)
    prep = _Prep(
        part=part, chunks=chunks, wait=data.wait_inbound_s, agent_number=numbers.effective_agent_number(conn, row),
        call_to=call_to,
        conn=diagnostics.DiagnosticConn(base_url=conn.base_url, key=key, account_id=conn.account_id,
                                        sender=conn.sender_number or ""),
        voice=diagnostics_voice.VoiceDiag(provider=row.provider, key=voice_key,
                                          model=numbers.effective_model(row.provider, row.model),
                                          voices=_configured_voices(row),
                                          call_voice=row.voice_unknown if voices.well_formed(row.voice_unknown) else None))
    session.rollback()  # 트랜잭션을 끝내고 부른다
    return prep


def _record(row: VoiceSettings | None) -> dict:
    found = row.last_diagnosis_json if row is not None else None
    return found if isinstance(found, dict) else {}


def _calls(record: dict) -> list[dict]:
    rows = record.get("calls")
    return [dict(r) for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _open_call(calls: list[dict], now: datetime) -> bool:
    """마지막 시험 전화의 결과를 모르고(거는 중·모름) 10분이 안 됐는가."""
    if not calls or calls[-1].get("outcome") not in ("calling", "unknown"):
        return False
    at = diagnose._when(calls[-1].get("at"))
    return at is None or now - at < RECALL_WINDOW


def _mark_calling_sync(session: Session, conn_id: int, data: VoiceDiagnoseIn, by: str, now: datetime) -> None:
    """쓰기 트랜잭션 하나: 목록 판·앞선 통화의 결과를 다시 보고 「거는 중」 기록을 남긴다(앞 진단의 걸음 줄은 그대로 둔다)."""
    service.begin_write(session)
    try:
        conn = service.get(session, conn_id, fresh=True)
        row = _settings(session, conn_id, fresh=True)
        _call_target(conn, row, data)
        record = _record(row)
        calls = _calls(record)  # 앞서 끝나지 못하고 남은 「거는 중」도 다시 걸기를 막는다(끝나면 _save_sync 가 「모름」으로 닫는다)
        if not data.confirm_recall and _open_call(calls, now):
            raise ApiError(409, "call_unknown_pending", RECALL)
    except ApiError:
        session.rollback()
        raise
    calls = (calls + [{"at": now.isoformat(), "by": by, "outcome": "calling"}])[-CALLS_KEPT:]
    row.last_diagnosis_json = {"state": "calling", "part": "call", "ran_at": now.isoformat(), "by": by,
                               "steps": record.get("steps") or [], "real": False, "calls": calls}
    session.commit()


# ── 진단: 돌리기 ─────────────────────────────────────────────────────


async def _checks(prep: _Prep, budget: diagnostics_voice.VoiceBudget) -> tuple[dict[int, diagnostics.DiagnosticStep], str]:
    """({걸음 번호: 결과}, 멈춘 까닭). 까닭: "" · "timeout"(상한) · "unlinked"(연결 실패) · "stopped"(앞 통화의 끝을 모름).
    통화 수는 `budget` 에 남는다 — 도중에 끊겨도(취소) 진단 모듈이 통화를 끊고 `maybe_live` 를 적어 둔다."""
    rows: dict[int, diagnostics.DiagnosticStep] = {}
    busy = worker_connected(prep.agent_number)
    for steps in prep.chunks:
        try:
            async with asyncio.timeout(_ceiling(steps, prep.wait)):
                found = await diagnostics_voice.run_voice_checks(
                    prep.conn, prep.voice, agent_number=prep.agent_number, steps=steps, call_to=prep.call_to,
                    wait_inbound_s=prep.wait, worker_connected=busy, budget=budget)
        except TimeoutError:
            return rows, "timeout"
        by_id = {step.id: step for step in found}
        got = {n: by_id[f"P{n}"] for n in steps if f"P{n}" in by_id}
        rows.update(got)
        if (5 in got and got[5].ok is not True) or any(s.code == "skipped_not_connected" for s in got.values()):
            return rows, "unlinked"
        if budget.maybe_live or any(s.maybe_sent is True or s.code in HALTED for s in got.values()):
            return rows, "stopped"
    return rows, ""


def _line(n: int, *, ran_at: str | None, code: str, detail: str, ok: bool = False, skipped: bool = False,
          latency_ms: int | None = None, notes: list[str] | None = None, maybe_sent: bool = False,
          pending: bool = False, data: dict | None = None) -> dict:
    """걸음 줄 하나(저장하는 꼴 = 내보내는 꼴). 이름표는 늘 우리 것."""
    return {"id": f"P{n}", "label": diagnostics_voice.LABELS[f"P{n}"], "ok": ok, "skipped": skipped, "detail": detail,
            "latency_ms": latency_ms, "notes": notes or [], "code": code, "maybe_sent": maybe_sent, "pending": pending,
            "data": data or {}, "ran_at": ran_at}


def _never(n: int) -> dict:
    return _line(n, ran_at=None, code="skipped_not_requested", detail=diagnostics.NOT_REQUESTED, skipped=True)


def _data(raw: object, clean: Callable[..., str]) -> dict:
    """참거짓·작은 수·짧은 글만 남긴다(안쪽 dict 는 한 단계, 참거짓·수만). 열쇠는 낱말 꼴만 — 그 밖은 버린다."""
    out: dict = {}

    def plain(value: object) -> bool:
        return value is None or type(value) is bool or (type(value) is int and abs(value) < 10_000_000)

    for key, value in (raw.items() if isinstance(raw, dict) else ()):
        if not (isinstance(key, str) and _WORD.fullmatch(key)):
            continue
        if isinstance(value, dict):
            inner = {k: v for k, v in value.items() if isinstance(k, str) and _WORD.fullmatch(k) and plain(v)}
            if inner:
                out[key] = inner
        elif plain(value):
            out[key] = value
        elif isinstance(value, str):
            out[key] = clean(value, limit=80)
    return out


def _fresh(prep: _Prep, rows: dict[int, diagnostics.DiagnosticStep], halt: str, budget: diagnostics_voice.VoiceBudget,
           now: datetime) -> dict[int, dict]:
    """이번 요청이 돌린 걸음의 줄 {걸음 번호: 줄}. 글은 한 번 더 지우고, 끝나지 못한 걸음은 까닭을 적는다. 상한에 걸린 덩어리의 걸음은
    결과를 모르는 것이라 실패가 아니라 `pending`(확인하지 못함)이다 — 그 가운데 걸렸을 수 있는 통화 걸음에는 `maybe_sent` 도 선다."""
    clean = partial(diagnostics.scrub, secrets=[prep.conn.key, prep.conn.account_id, prep.voice.key],
                    numbers=[n for n in (prep.agent_number, prep.call_to, prep.conn.sender) if n])
    stamp, out = now.isoformat(), {}
    wanted = sorted({n for chunk in prep.chunks for n in chunk})
    unsure = next((n for n in wanted if n in (6, 10) and n not in rows), None) if budget.maybe_live else None
    for n in wanted:
        step = rows.get(n)
        if step is not None:
            code = step.code if isinstance(step.code, str) and _WORD.fullmatch(step.code) else "unknown"
            skipped = step.skipped is True
            out[n] = _line(n, ran_at=stamp, code=code, detail=clean(step.detail, limit=400), skipped=skipped,
                           ok=step.ok is True and not skipped, maybe_sent=step.maybe_sent is True,
                           latency_ms=step.latency_ms if type(step.latency_ms) is int else None,
                           notes=[clean(note, limit=500) for note in (step.notes or [])][:20],
                           data=_data(getattr(step, "data", None), clean))
        elif halt == "timeout":
            maybe = n == unsure
            detail = f"{TIMED_OUT} {diagnostics_voice.MAYBE_PLACED}" if maybe else TIMED_OUT
            out[n] = _line(n, ran_at=stamp, code="timeout", detail=detail, maybe_sent=maybe, pending=True)
        elif halt == "unlinked":
            out[n] = _line(n, ran_at=stamp, code="skipped_not_connected", detail=diagnostics_voice.NOT_LINKED, skipped=True)
        else:
            out[n] = _line(n, ran_at=stamp, code="skipped_stopped", detail=diagnostics_voice.STOPPED, skipped=True)
    return out


def _outcome(fresh: dict[int, dict], halt: str, budget: diagnostics_voice.VoiceBudget) -> str:
    """시험 전화 요청의 결과: unknown(걸렸는지·끊겼는지 모름) · placed(걸렸고 끝남) · not_placed(걸리지 않음)."""
    if budget.maybe_live or any(line["maybe_sent"] for line in fresh.values()):
        return "unknown"
    rang = any(fresh[n]["ok"] or fresh[n]["code"] in RANG for n in (6, 10) if n in fresh)
    return "placed" if rang or (halt == "timeout" and budget.placed > 0) else "not_placed"


def _steps(record: dict, fresh: dict[int, dict] | None = None) -> list[dict]:
    """열 줄(P5~P14): 이번에 돌린 줄, 아니면 저장된 마지막 결과, 그것도 없으면 「확인하지 않음」."""
    saved = {s.get("id"): s for s in record.get("steps") or [] if isinstance(s, dict)}
    out = []
    for n in diagnostics_voice.STEPS:
        line = (fresh or {}).get(n)
        if line is None:
            try:
                line = VoiceStepOut(**saved[f"P{n}"]).model_dump(mode="json") if f"P{n}" in saved else _never(n)
            except (ValidationError, TypeError):
                line = _never(n)
        out.append(line)
    return out


def _status(steps: list[dict]) -> str | None:
    """걸음마다의 마지막 결과 가운데 연결(P5)·번호 묶기(P11)·통화(P6)로 정한다. 결과를 모르는 줄 — 시간 상한에 걸린 `pending`, 걸렸는지·
    끊겼는지 모르는 통화 `maybe_sent`(cut_unconfirmed·not_finished …) — 은 판정에서 뺀다(고침 1, 계약 C5): 실패로도 성공으로도 세지 않고,
    이번에 돌리지 않은 걸음의 묵은 「모름」이 분명한 결과를 막지도 않는다. 세 결과(성공·실패·모름)는 셋으로 남는다.

    | 남은(모름 아닌) P5·P11·P6 가운데 분명한 실패 | P5        | 결과                 |
    | 있음                                         | 무엇이든  | "failed"             |
    | 없음                                         | 성공      | "ok"                 |
    | 없음                                         | 모름      | None(앞 값 그대로)   |
    | 없음                                         | 돌린 적 없음·건너뜀, 셋 가운데 모름 있음 | None(앞 값 그대로) |
    | 없음                                         | 돌린 적 없음·건너뜀, 모름 없음           | "unknown"          |
    """
    if any(line["id"] == "P9" and line["ran_at"] and line["code"] == "voice_rejected" for line in steps):
        return "failed"  # 공급자가 받지 않은 음성 — 그 칸을 쓰는 전화는 받은 뒤 끊긴다(Task 99 고침 1)
    judged = {line["id"]: line for line in steps if line["id"] in ("P5", "P11", "P6")}
    definite = [line for line in judged.values() if not (line["pending"] or line["maybe_sent"])]
    if any(line["ran_at"] and not line["ok"] and not line["skipped"] for line in definite):
        return "failed"
    if judged["P5"]["ok"]:
        return "ok"
    return None if len(definite) < len(judged) else "unknown"


def _closed(record: dict, stamp: str = "", outcome: str | None = None) -> dict:
    """「거는 중」으로 남은 통화를 닫은 기록(state "done"). 이번 통화(`stamp`)는 `outcome` 으로, 그 밖에 남은 것은 끝을 알 수 없으므로
    「모름」으로 닫는다. 기록 자신의 통화가 「모름」이 되면 P6 줄을 not_finished 로 바꾼다. 남은 「거는 중」을 닫는 곳은 여기뿐이다."""
    calls, ran = _calls(record), record.get("ran_at")
    for call in calls:
        if call.get("outcome") == "calling":
            call["outcome"] = outcome if outcome and call.get("at") == stamp else "unknown"
    steps = record.get("steps") or []
    if record.get("state") == "calling" and any(c.get("at") == ran and c.get("outcome") == "unknown" for c in calls):
        steps = _steps(record, {6: _line(6, ran_at=ran, code="not_finished", detail=NOT_FINISHED, maybe_sent=True)})
    return {**record, "state": "done", "steps": steps, "calls": calls, "real": outcome == "placed"}


def _save_sync(session: Session, conn_id: int, part: str, fresh: dict[int, dict], outcome: str | None, now: datetime,
               by: str) -> VoiceDiagnosisOut:
    """결과로 바꾼다(쓰기 트랜잭션 하나, 줄은 다시 읽는다). 통화 기록은 이어 쓰고 이번 것은 결과로 고친다. 걸지 않는 진단이
    앞서 끝나지 못한 「거는 중」 기록 위에 쓸 때는 그 통화를 「모름」으로 닫아 남긴다(P6 줄도) — 표시가 지워지지 않게."""
    service.begin_write(session)
    row = session.get(VoiceSettings, conn_id, populate_existing=True)
    previous = _record(row)
    closed = _closed(previous, now.isoformat(), outcome)
    steps = _steps(closed if outcome is None else previous, fresh)
    record = {"state": "done", "part": part, "ran_at": now.isoformat(), "by": by, "steps": steps,
              "real": outcome == "placed", "calls": closed["calls"]}
    if row is None:  # 그사이 지워졌다 — 저장하지 않고 결과만 돌려준다
        session.rollback()
        return _shown(record, now)
    row.last_diagnosis_json = record
    status = _status(steps)
    if status is not None and fresh.get(5, {}).get("code") != "worker_connected":  # 일꾼이 붙어 연결해 보지 않은 진단도 그대로
        row.status, row.checked_at = status, now
    session.commit()
    return _shown(record, datetime.now(UTC))


def _settle_cancelled(conn_id: int, stamp: str, budget: diagnostics_voice.VoiceBudget) -> None:
    """끊긴(취소된) 시험 전화 요청의 「거는 중」 기록을 닫는다. 진단 모듈은 취소돼도 통화를 끊고 끝을 확인했는지(`maybe_live`)를
    남긴다 — 그것으로 정한다. 취소된 뒤에는 await 를 믿을 수 없어 새 세션으로 곧바로 쓴다. 쓰지 못하면 기록은 「거는 중」으로 남아
    뒤에 「모름」으로 읽힌다(닫힌 쪽)."""
    outcome = "unknown" if budget.maybe_live else "placed" if budget.placed else "not_placed"
    try:
        with contextmanager(get_session)() as session:
            service.begin_write(session)
            row = session.get(VoiceSettings, conn_id)
            record = _record(row)
            if record.get("state") == "calling" and record.get("ran_at") == stamp:
                row.last_diagnosis_json = _closed(record, stamp, outcome)
            session.commit()
    except Exception:  # noqa: BLE001, S110 — 취소를 가리지 않는다
        pass


async def _model_refused(prep: _Prep, budget: diagnostics_voice.VoiceBudget, now: datetime) -> dict[int, dict] | None:
    """구글이면 걸기·연결 전에 이 키의 Live 모델 목록을 본다. 구글이 키를 거절했거나(P5 key_refused), 읽은 목록에 Live 모델이 하나도
    없거나(P5 no_live_model), 목록을 읽었는데 고른 모델이 없으면(P5 model_not_available) P5 를 실패로 둔 줄(나머지는 연결 안 됨으로 건너뜀), 아니면(시간 초과 등으로 읽지 못했거나 목록에
    있음·다른 공급자) None — 그때는 전처럼 돈다."""
    if prep.voice.provider != "google" or not prep.voice.model:
        return None
    found = await run_in_threadpool(live_models.list_live_models, prep.voice.key)
    if found.refused:
        detail, code = live_models.KEY_REFUSED, "key_refused"
    elif found.no_live:
        detail, code = live_models.NO_LIVE_MODEL, "no_live_model"
    elif found.fallback or prep.voice.model in found.available:
        return None
    else:
        detail, code = MODEL_UNUSABLE.format(model=prep.voice.model), "model_not_available"
    step = diagnostics_voice.VoiceStep(id="P5", label=diagnostics_voice.LABELS["P5"], ok=False, detail=detail, code=code)
    return _fresh(prep, {5: step}, "unlinked", budget, now)


async def run(session: Session, conn_id: int, data: VoiceDiagnoseIn, by: str) -> VoiceDiagnosisOut:
    prep = await run_in_threadpool(_prepare_sync, session, conn_id, data)
    if conn_id in diagnose._RUNNING:  # 연결 진단(P1~P4)과도 겹치지 않는다
        raise ApiError(409, "diagnosis_running", RUNNING)
    now, budget = datetime.now(UTC), diagnostics_voice.VoiceBudget()
    diagnose._RUNNING.add(conn_id)
    _VOICE_RUNNING[conn_id] = {"part": prep.part, "at": now, "by": by}
    try:
        refused = await _model_refused(prep, budget, now)
        if refused is not None:  # 이 키로 쓸 수 없는 모델 — 연결도 전화도 하지 않는다
            return await run_in_threadpool(_save_sync, session, conn_id, prep.part, refused, None, now, by)
        if prep.part == "call":
            await run_in_threadpool(_mark_calling_sync, session, conn_id, data, by, now)
        try:
            async with inbound.paused(prep.call_to):  # 진단 동안 받는 통화 듣기를 멈춘다(연결은 번호당 하나) — 끝나면 곧바로 다시 듣는다
                rows, halt = await _checks(prep, budget)
        except asyncio.CancelledError:
            if prep.part == "call":
                _settle_cancelled(conn_id, now.isoformat(), budget)
            raise
        fresh = _fresh(prep, rows, halt, budget, now)
        outcome = _outcome(fresh, halt, budget) if prep.part == "call" else None
        return await run_in_threadpool(_save_sync, session, conn_id, prep.part, fresh, outcome, now, by)
    finally:
        diagnose._RUNNING.discard(conn_id)
        _VOICE_RUNNING.pop(conn_id, None)


# ── 진단: 읽기 ───────────────────────────────────────────────────────


def _records(calls: list[dict], now: datetime) -> list[CallRecord]:
    """시험 전화 기록. 상한보다 오래 「거는 중」으로 남은 것은 「모름」으로 읽는다."""
    out = []
    for call in calls:
        at = diagnose._when(call.get("at"))
        outcome = call.get("outcome")
        if at is not None and outcome == "calling" and now - at > timedelta(seconds=STALE_CALL_S):
            outcome = "unknown"
        try:
            out.append(CallRecord(at=at, by=str(call.get("by") or ""), outcome=outcome))
        except ValidationError:
            continue
    return out


def _unknown(calls: list[CallRecord]) -> bool:
    """마지막 시험 전화의 결과를 모르는가. `call_unknown` 은 여기 한 곳에서만 정한다(저장하지 않는다)."""
    return bool(calls) and calls[-1].outcome == "unknown"


def _shown(record: dict, now: datetime) -> VoiceDiagnosisOut | None:
    ran_at = diagnose._when(record.get("ran_at"))
    if ran_at is None:
        return None
    calling = record.get("state") == "calling"
    dialing = calling and now - ran_at <= timedelta(seconds=STALE_CALL_S)  # 걸고 있다(다른 프로세스이거나 방금 죽었을 수도 있다)
    if calling and not dialing:
        record = _closed(record)  # 끝나지 못한 채 상한보다 오래 남았다 — 「모름」
    calls = _records(_calls(record), now)
    base = {"part": record.get("part") if record.get("part") in PARTS else None, "ran_at": ran_at,
            "by": record.get("by") if isinstance(record.get("by"), str) else None, "calls": calls,
            "call_unknown": _unknown(calls)}
    if dialing:
        return VoiceDiagnosisOut(state="running", steps=[], called_real=False, **base)
    return VoiceDiagnosisOut(state="done", steps=_steps(record), called_real=record.get("real") is True, **base)


def last(session: Session, conn_id: int) -> VoiceDiagnosisOut | None:
    service.get(session, conn_id)
    record, now = _record(session.get(VoiceSettings, conn_id)), datetime.now(UTC)
    running = _VOICE_RUNNING.get(conn_id)
    if running is not None:
        calls = _records(_calls(record), now)
        return VoiceDiagnosisOut(state="running", part=running["part"], ran_at=running["at"], by=running["by"],
                                 steps=[], called_real=False, call_unknown=_unknown(calls), calls=calls)
    return _shown(record, now)


# ── 길(모두 관리자) ──────────────────────────────────────────────────


@router.get("/connections/{conn_id}/voice", dependencies=[AdminOnly])
def get_voice(conn_id: int, session: SessionDep) -> VoiceOut:
    return _out(service.get(session, conn_id), session.get(VoiceSettings, conn_id))


@router.put("/connections/{conn_id}/voice", dependencies=[AdminOnly])
def put_voice(conn_id: int, body: VoiceUpdate, session: SessionDep) -> VoiceOut:
    return save(session, conn_id, body)


@router.delete("/connections/{conn_id}/voice", status_code=204, dependencies=[AdminOnly])
def delete_voice(conn_id: int, session: SessionDep) -> Response:
    remove(session, conn_id)
    return Response(status_code=204)


@router.get("/connections/{conn_id}/voice/models", dependencies=[AdminOnly])
def voice_models(conn_id: int, session: SessionDep) -> VoiceModelsOut:
    return models(session, conn_id)


@router.post("/connections/{conn_id}/voice/diagnose")
async def run_voice_diagnosis(conn_id: int, body: VoiceDiagnoseIn, session: SessionDep,
                              user: Annotated[User, Depends(require_admin)]) -> VoiceDiagnosisOut:
    return await run(session, conn_id, body, user.name)


@router.get("/connections/{conn_id}/voice/diagnosis", dependencies=[AdminOnly])
def last_voice_diagnosis(conn_id: int, session: SessionDep) -> VoiceDiagnosisOut | None:
    return last(session, conn_id)
