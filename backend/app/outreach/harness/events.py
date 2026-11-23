"""하네스 사건 기록. 메시지와 통화가 같은 꼴로 그 줄의 harness_json 에 한 줄씩 남긴다:
{rule, verdict, detail, evidence, at} — 어느 규칙이 무엇을 막았나(blocked)·지나보냈나(allowed)·적어 두었나(noted)와 근거.

- rule 은 코드가 정한 이름만(KNOWN_RULES — types 의 GATE_RULES·EVENT_RULES·`tool:<도구>`·`tool:unknown`). 모델이 준 도구
  이름은 tool_rule 로 바꿔 넣는다(모르는 이름은 `tool:unknown`). 틀린 이름은 ValueError(받은 값은 오류 글에 싣지 않는다).
- detail·evidence 는 저장하기 전에 redact.scrub(redact.secrets() 의 비밀 — 키·Account ID — 과 번호)을 거친 뒤 DETAIL_MAX·
  EVIDENCE_MAX 로 자른다. 비밀 목록을 읽지 못하면 그 글을 HIDDEN_TEXT 로 바꾼다. redact 의 밑줄 이름은 쓰지 않는다.
- 한 줄 더하기는 UPDATE 한 문장(SQLite json_insert, harness_json 이 JSON 목록일 때만)이라 두 세션이 같은 줄에 남겨도 어느
  것도 잃지 않는다. 목록이 아니면(JSON null·객체) 바꾸지 않고 ValueError. 같은 세션에 읽혀 있던 그 줄 객체의 harness_json 은
  만료돼 다음에 다시 읽힌다.
- 한 줄의 사건은 MAX_EVENTS 개까지: 넘으면 가장 오래된 것들을 맨 앞의 「생략됨」 표식 하나(rule OMITTED, 센 수)로 바꾼다.
- commit 은 부른 쪽이 한다(판정·상태와 사건이 한 묶음으로 남거나 함께 사라진다). 첫 UPDATE 부터 commit 까지 SQLite 쓰기
  잠금을 쥐므로 **바로 commit 할 것** — 쥔 채 제공사·모델을 부르면 다른 쓰기가 기다리다 「database is locked」로 실패한다.
"""

import json
import re
from datetime import UTC, datetime
from typing import Literal, get_args

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.outreach import redact
from app.outreach.harness.types import (
    EVENT_RULES,
    GATE_RULES,
    SHARED_TOOLS,
    VOICE_ONLY_TOOLS,
    Ref,
)
from app.store.outreach import NotFound
from app.store.tables_outreach import OutreachCall, OutreachMessage
from app.store.timeutil import as_utc

EventVerdict = Literal["blocked", "allowed", "noted"]
TOOL_NAMES = frozenset(SHARED_TOOLS + VOICE_ONLY_TOOLS)
UNKNOWN_TOOL = "tool:unknown"
RULE_PATTERN = re.compile(r"[a-z_]+(?::[a-z_]+)?")  # 모든 사건 이름의 꼴(시험이 KNOWN_RULES 전부를 견준다)
KNOWN_RULES: frozenset[str] = (
    frozenset(GATE_RULES.values()) | EVENT_RULES | {f"tool:{name}" for name in TOOL_NAMES} | {UNKNOWN_TOOL}
)
OMITTED = "omitted"  # 생략 표식의 rule — 이 모듈만 쓴다(record 로는 남길 수 없다)
DETAIL_MAX, EVIDENCE_MAX, MAX_EVENTS = 300, 500, 200
HIDDEN_TEXT = "(비밀 목록을 읽지 못해 숨겼습니다)"
_VERDICTS = get_args(EventVerdict)
_ROWS: dict[str, type[OutreachMessage] | type[OutreachCall]] = {"message": OutreachMessage, "call": OutreachCall}
_OMITTED_TEXT = re.compile(r"앞선 사건 (\d+)개 생략됨")


def tool_rule(name: str) -> str:
    """도구 호출 사건의 이름. 묶음의 도구면 `tool:<이름>`, 아니면(모델이 지어낸 이름 포함) `tool:unknown`."""
    return f"tool:{name}" if name in TOOL_NAMES else UNKNOWN_TOOL


def _registered_secrets() -> tuple[str, ...] | None:
    """지금 쓰는 비밀 전체(redact.secrets — add_secrets 로 등록한 것 + install 원천). 원천이 실패하면 None(글을 숨긴다).
    redact.secrets 가 없으면(이름이 바뀜) AttributeError 가 그대로 올라간다 — 조용히 숨기지 않게 부르기 전에 꺼낸다."""
    read = redact.secrets
    try:
        return read()
    except Exception:  # noqa: BLE001 — 원천이 무엇으로 실패하든 「읽지 못함」
        return None


def _clean(text: str, limit: int, secrets: tuple[str, ...] | None) -> str:
    cleaned = HIDDEN_TEXT if secrets is None else redact.scrub(text, secrets)
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1] + "…"


def record(
    session: Session,
    ref: Ref,
    rule: str,
    verdict: EventVerdict,
    detail: str,
    evidence: str | None = None,
    *,
    now: datetime | None = None,
) -> None:
    """그 줄의 harness_json 끝에 사건 한 줄(모듈 머리 글). now 는 시험이 시각을 고정할 때(시간대 없으면 UTC).
    줄이 없으면 NotFound, 이름·판정이 틀렸거나 harness_json 이 목록이 아니면 ValueError. commit 은 부른 쪽이 곧바로."""
    if rule not in KNOWN_RULES:
        raise ValueError("사건 이름은 코드가 정한 이름(events.KNOWN_RULES)만 씁니다")
    if verdict not in _VERDICTS:
        raise ValueError(f"사건 판정은 {_VERDICTS} 가운데 하나입니다")
    secrets = _registered_secrets()
    event = {
        "rule": rule,
        "verdict": verdict,
        "detail": _clean(detail, DETAIL_MAX, secrets),
        "evidence": None if evidence is None else _clean(evidence, EVIDENCE_MAX, secrets),
        "at": as_utc(now or datetime.now(UTC)).isoformat(timespec="milliseconds"),
    }
    model = _ROWS[ref.kind]
    appended = func.json_insert(model.harness_json, "$[#]", func.json(json.dumps(event, ensure_ascii=False)))
    is_list = func.json_type(model.harness_json) == "array"
    result = session.execute(update(model).where(model.id == ref.row_id, is_list).values(harness_json=appended))
    if result.rowcount != 1:
        if session.scalar(select(model.id).where(model.id == ref.row_id)) is None:
            raise NotFound(ref.row_id)
        raise ValueError("그 줄의 harness_json 이 사건 목록이 아니라 남기지 않았습니다")
    _trim(session, ref)


def _trim(session: Session, ref: Ref) -> None:
    """MAX_EVENTS 를 넘으면 가장 오래된 것들을 맨 앞 생략 표식 하나로. 앞의 UPDATE 로 쓰기 잠금을 쥔 뒤라 읽고 쓰기가 안전하다."""
    model = _ROWS[ref.kind]
    size = session.scalar(select(func.json_array_length(model.harness_json)).where(model.id == ref.row_id))
    if size <= MAX_EVENTS:
        return
    events = of(session, ref)
    omitted = 0
    if events[0]["rule"] == OMITTED:
        omitted = int(_OMITTED_TEXT.fullmatch(events[0]["detail"]).group(1))
        events = events[1:]
    keep = events[len(events) - (MAX_EVENTS - 1):]
    dropped = events[: len(events) - len(keep)]
    marker = {"rule": OMITTED, "verdict": "noted", "detail": f"앞선 사건 {omitted + len(dropped)}개 생략됨",
              "evidence": None, "at": dropped[-1]["at"]}
    session.execute(update(model).where(model.id == ref.row_id).values(harness_json=[marker, *keep]))


def of(session: Session, ref: Ref) -> list[dict]:
    """그 줄의 사건 전부(남긴 차례대로). 줄이 없으면 NotFound, 칸이 null 이면 [], 목록이 아니면 ValueError."""
    model = _ROWS[ref.kind]
    found = session.execute(select(model.harness_json).where(model.id == ref.row_id)).one_or_none()
    if found is None:
        raise NotFound(ref.row_id)
    value = found[0]
    if value is None:
        return []
    if type(value) is not list:  # 칸에 담긴 값이 틀림(부른 쪽 인자가 아님) — record 와 같은 ValueError
        raise ValueError("그 줄의 harness_json 이 사건 목록이 아닙니다")
    return list(value)
