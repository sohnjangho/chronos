"""하네스 사건 기록. 메시지와 통화가 같은 꼴로 그 줄의 harness_json 에 한 줄씩 남긴다:
{rule, verdict, detail, evidence, at} — 어느 규칙이 무엇을 막았나(blocked)·지나보냈나(allowed)·적어 두었나(noted)와 근거.

- detail·evidence 는 저장하기 전에 hide_phones 를 거친다(번호는 사건에 남지 않는다).
- 한 줄 더하기는 UPDATE 한 문장(SQLite json_insert)이라 두 세션이 같은 줄에 남겨도 어느 것도 잃지 않는다.
  같은 세션에 읽혀 있던 그 줄의 harness_json 은 만료돼 다음에 다시 읽힌다.
- commit 은 부른 쪽이 한다(판정과 사건이 한 묶음으로 남거나 함께 사라진다).
"""

import json
from datetime import UTC, datetime
from typing import Literal, get_args

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.outreach.harness.types import Ref
from app.outreach.redact import hide_phones
from app.store.outreach import NotFound
from app.store.tables_outreach import OutreachCall, OutreachMessage

EventVerdict = Literal["blocked", "allowed", "noted"]
_VERDICTS = get_args(EventVerdict)
_ROWS: dict[str, type[OutreachMessage] | type[OutreachCall]] = {"message": OutreachMessage, "call": OutreachCall}


def record(
    session: Session, ref: Ref, rule: str, verdict: EventVerdict, detail: str, evidence: str | None = None
) -> None:
    """그 줄의 harness_json 끝에 사건 한 줄. 줄이 없으면 NotFound, 판정이 셋 가운데 하나가 아니면 ValueError."""
    if verdict not in _VERDICTS:
        raise ValueError(f"사건 판정은 {_VERDICTS} 가운데 하나입니다")
    event = {
        "rule": rule,
        "verdict": verdict,
        "detail": hide_phones(detail),
        "evidence": None if evidence is None else hide_phones(evidence),
        "at": datetime.now(UTC).isoformat(timespec="milliseconds"),
    }
    model = _ROWS[ref.kind]
    appended = func.json_insert(model.harness_json, "$[#]", func.json(json.dumps(event, ensure_ascii=False)))
    result = session.execute(update(model).where(model.id == ref.row_id).values(harness_json=appended))
    if result.rowcount != 1:
        raise NotFound(ref.row_id)


def of(session: Session, ref: Ref) -> list[dict]:
    """그 줄의 사건 전부(남긴 차례대로). 줄이 없으면 NotFound."""
    model = _ROWS[ref.kind]
    found = session.execute(select(model.harness_json).where(model.id == ref.row_id)).one_or_none()
    if found is None:
        raise NotFound(ref.row_id)
    return list(found[0])
