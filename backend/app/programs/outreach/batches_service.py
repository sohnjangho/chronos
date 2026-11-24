"""여러 명에게 한 번에(계획 4 Task 103): 같은 글을 받는 사람마다 한 줄씩 만들어 **한 사람씩** 나가는 문에 넣는다.

- **한 번 누름 = 한 묶음**: 화면은 창마다 요청 번호(request_key)를 하나 만들어 같은 묶음의 모든 시도(두 번 누름·답을 못 받고 다시
  물음)에 같은 값을 보낸다. 줄의 중복 방지 키(idempotency_key, 고유 칸)를 `b<sha256(일정:사람:요청 번호) 앞 40자>-<연락처 id>`
  로 정해 두므로 — 먼저 그 앞부분의 줄이 있는지 보고(있으면 저장된 결과만, 문을 부르지 않음), 없어서 넣을 때 다른 요청이 먼저
  넣었으면 고유 칸에 걸려 아무것도 만들지 않고 그 저장된 결과를 돌려준다(조건부 넣기). 같은 요청 번호에 다른 내용(받는 사람·통로·
  글·문안·연결)이 오면 409 key_reused — 아무것도 만들거나 보내지 않는다.
- **다시 온 요청이 첫 요청이 아직 도는 동안이면**: 문에 아직 넣지 않은 초안(사건 없음)과 나가는 중(sending)인 줄은, 묶음이 만들어진 지
  IN_PROGRESS_S(받는 사람 상한 × 제공사 요청 시간 제한) 안이면 `in_progress` 「보내는 중일 수 있습니다 — 잠시 뒤 다시 확인해 주세요」
  (응답의 in_progress 참). 그보다 오래된 초안은 첫 요청이 끝내 넣지 못한 것(서버가 죽음)이라 `not_sent`, 그보다 오래 sending 에
  머문 줄은 결과를 적지 못한 것이라 `unsure`(「확인 필요」).
- **결과 확인은 보내지 않는다**: `check(…)`(GET …/batches/by-key)는 같은 사람·일정의 요청 번호로 저장된 묶음만 찾아 같은 꼴로 돌려준다.
  없으면 404 「이 묶음은 서버에 닿지 않았습니다 — 보내지 않았습니다」 — 만들지도 문을 부르지도 않는다.
- **줄은 한 번에 만들고 보내기는 한 사람씩**: 모든 연락처·연결 id·글을 먼저 본 뒤(하나라도 틀리면 404/422, 아무것도 만들지 않음)
  줄을 모두 초안으로 commit 하고, 방금 만든 그 일정의 줄만 차례로 `gate.dispatch` 에 넣는다. 한 사람의 실패·거절·「확인 필요」·
  뜻밖의 오류는 다음 사람을 멈추거나 다시 보내게 하지 않는다(오류는 「확인 필요」로 — 나갔는지 모르므로 보냄이라 하지 않는다).
  서버가 묶음 가운데 죽으면 아직 문에 넣지 않은 줄은 초안으로 남는다 — 일꾼은 초안을 보내지 않으므로 나중에 몰래 나가지 않고,
  같은 요청을 다시 보내면 「아직 보내지 않았습니다」로 보인다.
- batch_id 는 그 묶음 첫 줄의 id(줄 id 는 다시 쓰지 않는다). Actor 는 로그인한 사람(service._actor). send_mode 는 쓰지 않는다.
- 번호는 응답·로그에 없다(이름과 판정 글만). 오류 로그에는 예외의 이름만 남긴다.
"""

import hashlib
import logging
from typing import Annotated

from pydantic import BaseModel, Field, StrictInt, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.outreach import kakao, provider
from app.outreach.harness import gate
from app.outreach.harness.types import Outcome
from app.programs.outreach import service
from app.programs.outreach.schemas import (
    ActivityId,
    Body,
    Channel,
    OutcomeOut,
    Strict,
    VarName,
    VarValue,
)
from app.store.tables import User
from app.store.tables_outreach import Contact, KakaoTemplate, OutreachMessage
from app.store.timeutil import as_utc

logger = logging.getLogger(__name__)

BATCH_MAX = 20  # 한 묶음에 받는 사람 수
BATCH_NOT_FOUND = "묶음을 찾을 수 없습니다."
SAME_PERSON = "같은 사람이 두 번 들어 있습니다."
NEED_TEXT = "보낼 글이나 문안을 넣어 주세요."
VARS_WITHOUT_TEMPLATE = "문안 값은 문안과 함께 보냅니다."
BAD_TEMPLATE = "문안의 빈 칸을 모두 채워 주세요."
NOT_SENT = "아직 보내지 않았습니다 — 그 사람의 대화에 초안으로 남아 있습니다"
GONE_NAME = "지워진 연락처"
IN_PROGRESS = "보내는 중일 수 있습니다 — 잠시 뒤 다시 확인해 주세요"
NOT_REACHED = "이 묶음은 서버에 닿지 않았습니다 — 보내지 않았습니다"
KEY_REUSED = "이 요청 번호는 다른 내용의 묶음에 이미 쓰였습니다 — 창을 다시 열어 보내 주세요."
IN_PROGRESS_S = BATCH_MAX * provider.TIMEOUT_S  # 첫 요청이 아직 돌고 있을 수 있는 시간(사람마다 제공사 요청 하나)
_SENT = ("accepted", "delivered")
KEY_PATTERN = r"^[A-Za-z0-9_-]{8,64}$"  # 요청 번호(제공사 중복 방지 키와 같은 꼴)


class BatchIn(Strict):
    """같은 글을 1~20명에게. request_key = 화면이 창마다 만든 요청 번호(같은 묶음의 모든 시도에 같은 값)."""

    contact_ids: Annotated[list[StrictInt], Field(min_length=1, max_length=BATCH_MAX)]
    channel: Channel
    body: Body | None = None
    template_id: StrictInt | None = None
    template_vars: Annotated[dict[VarName, VarValue], Field(max_length=20)] | None = None
    activity_id: ActivityId | None = None
    field_item_id: StrictInt | None = None
    approval_id: StrictInt | None = None
    request_key: Annotated[str, Field(pattern=KEY_PATTERN)]

    @model_validator(mode="after")
    def _shape(self) -> "BatchIn":
        if len(set(self.contact_ids)) != len(self.contact_ids):
            raise ValueError(SAME_PERSON)
        if self.body is None and self.template_id is None:
            raise ValueError(NEED_TEXT)
        if self.template_vars is not None and self.template_id is None:
            raise ValueError(VARS_WITHOUT_TEMPLATE)
        return self


class BatchResultOut(BaseModel):
    contact_id: int
    name: str
    outcome: OutcomeOut


class BatchSendOut(BaseModel):
    batch_id: int
    results: list[BatchResultOut]  # 보낸 차례(요청의 contact_ids 차례)
    replayed: bool  # 이미 받은 요청 — 저장된 결과이고 이번에는 아무것도 보내지 않았다
    in_progress: bool  # 첫 요청이 아직 보내는 중일 수 있음(결과 가운데 in_progress 가 있음) — 잠시 뒤 같은 요청으로 다시 묻는다


class BatchStatsOut(BaseModel):
    total: int  # 그 묶음의 메시지 수(받는 사람 수)
    sent: int  # 나간 것(접수·도착)
    replied: int  # 그 묶음 메시지에 reply_to_id 로 답한 사람 수


def _prefix(schedule_id: int, user: User, request_key: str) -> str:
    digest = hashlib.sha256(f"{schedule_id}:{user.id}:{request_key}".encode()).hexdigest()[:40]
    return f"b{digest}-"


def _stored(session: Session, schedule_id: int, prefix: str) -> list[OutreachMessage] | None:
    """그 요청으로 이미 만든 줄(만든 차례). 없으면 None."""
    rows = list(session.scalars(select(OutreachMessage).where(
        OutreachMessage.schedule_id == schedule_id, OutreachMessage.idempotency_key.startswith(prefix, autoescape=True),
    ).order_by(OutreachMessage.id)))
    return rows or None


def _now_outcome(row: OutreachMessage, young: bool) -> Outcome | OutcomeOut:
    """저장된 줄의 지금 모습을 판정 꼴로(다시 온 요청에 돌려줄 것). 보냄으로 보이는 것은 접수·도착뿐.
    young = 묶음이 IN_PROGRESS_S 안에 만들어짐(첫 요청이 아직 돌 수 있음)."""
    if row.status in _SENT:
        return Outcome("accepted", "보냈습니다")
    if row.status == "failed":
        return Outcome("failed", row.fail_reason or gate.SEND_FAILED)
    if row.status == "unconfirmed":
        return Outcome("unsure", gate.UNSURE)
    if row.status == "sending" and not young:  # 결과를 적지 못하고 오래 남음 — 나갔는지 모른다
        return Outcome("unsure", gate.UNSURE)
    if row.status == "sending" or (row.status == "draft" and not row.harness_json and young):
        return OutcomeOut(code="in_progress", message=IN_PROGRESS, scheduled_at=None)
    if row.status == "blocked_test":
        return Outcome("blocked_test", row.fail_reason or "시험 모드라 허용한 번호에만 연락합니다")
    if row.status == "scheduled":
        return OutcomeOut(code="scheduled", message="근무시간 밖이라 다음 근무 시작에 보냅니다",
                          scheduled_at=service._utc(row.scheduled_at))
    return OutcomeOut(code="not_sent", message=row.fail_reason or NOT_SENT, scheduled_at=None)


def _names(session: Session, schedule_id: int, ids: set[int]) -> dict[int, str]:
    rows = session.scalars(select(Contact).where(Contact.schedule_id == schedule_id, Contact.id.in_(ids)))
    return {row.id: row.name for row in rows}


def _result(contact_id: int, names: dict[int, str], outcome: Outcome | OutcomeOut) -> BatchResultOut:
    out = outcome if isinstance(outcome, OutcomeOut) else service._outcome(outcome)
    return BatchResultOut(contact_id=contact_id, name=names.get(contact_id, GONE_NAME), outcome=out)


def _replay(session: Session, schedule_id: int, rows: list[OutreachMessage]) -> BatchSendOut:
    names = _names(session, schedule_id, {row.contact_id for row in rows if row.contact_id is not None})
    young = (service._now() - as_utc(rows[0].created_at)).total_seconds() <= IN_PROGRESS_S
    results = [_result(row.contact_id or 0, names, _now_outcome(row, young)) for row in rows]
    return BatchSendOut(batch_id=rows[0].batch_id or rows[0].id, replayed=True, results=results,
                        in_progress=any(r.outcome.code == "in_progress" for r in results))


def _same_request(rows: list[OutreachMessage], body: BatchIn) -> bool:
    """저장된 묶음이 이 요청과 같은 내용인가(받는 사람 차례·통로·글·문안·연결). 카카오톡을 문이 문자로 바꿨으면 그것도 같음."""
    if [row.contact_id for row in rows] != body.contact_ids:
        return False
    return all(
        (row.channel == body.channel or (row.fallback_sms and body.channel == "kakao"))
        and (body.body is None or row.body == body.body) and row.template_id == body.template_id
        and dict(row.template_vars_json or {}) == (body.template_vars or {})
        and (row.activity_id, row.field_item_id, row.approval_id) == (body.activity_id, body.field_item_id, body.approval_id)
        for row in rows)


def _answer(session: Session, schedule_id: int, rows: list[OutreachMessage], body: BatchIn) -> BatchSendOut:
    """이미 받은 요청 번호: 같은 내용이면 저장된 결과, 다른 내용이면 409(아무것도 하지 않음)."""
    if not _same_request(rows, body):
        raise ApiError(409, "key_reused", KEY_REUSED)
    return _replay(session, schedule_id, rows)


def _text(session: Session, body: BatchIn) -> str:
    """보낼 글: 받은 본문, 없으면 문안을 다 채운 글(빈 칸이 남으면 422)."""
    if body.body is not None:
        return body.body
    template = session.get(KakaoTemplate, body.template_id)
    try:
        return kakao.fill(template.body, body.template_vars or {})
    except kakao.KakaoError:
        raise ApiError(422, "invalid_template", BAD_TEMPLATE, detail={"field": "template_vars"}) from None


def check(session: Session, schedule_id: int, request_key: str, user: User) -> BatchSendOut:
    """결과 확인만: 그 사람·일정의 요청 번호로 저장된 묶음의 지금 결과. 없으면 404 — 만들거나 보내지 않는다."""
    stored = _stored(session, schedule_id, _prefix(schedule_id, user, request_key))
    if stored is None:
        raise ApiError(404, "not_found", NOT_REACHED)
    return _replay(session, schedule_id, stored)


async def send(session: Session, schedule_id: int, body: BatchIn, user: User) -> BatchSendOut:
    """요청 번호로 이미 만든 묶음이면 그 결과만. 아니면 검사 → 줄을 모두 초안으로 commit → 한 사람씩 문에 넣는다."""
    prefix = _prefix(schedule_id, user, body.request_key)
    stored = _stored(session, schedule_id, prefix)
    if stored is not None:
        return _answer(session, schedule_id, stored, body)
    people = [service._contact(session, schedule_id, cid) for cid in body.contact_ids]  # 하나라도 아니면 404
    service.check_body(body.body, *(body.template_vars or {}).values())
    service._check_links(session, schedule_id, activity_id=body.activity_id, field_item_id=body.field_item_id,
                         approval_id=body.approval_id, template_id=body.template_id)
    text = _text(session, body)
    rows = [OutreachMessage(
        schedule_id=schedule_id, contact_id=who.id, direction="out", channel=body.channel, kind="normal", body=text,
        template_id=body.template_id, template_vars_json=dict(body.template_vars or {}), origin="user",
        origin_name=user.name, status="draft", activity_id=body.activity_id, field_item_id=body.field_item_id,
        approval_id=body.approval_id, idempotency_key=f"{prefix}{who.id}",
    ) for who in people]
    try:
        session.add_all(rows)
        session.flush()
        for row in rows:
            row.batch_id = rows[0].id
        session.commit()
    except IntegrityError:  # 같은 요청이 그 사이 먼저 넣었다 — 그 묶음의 결과만
        session.rollback()
        stored = _stored(session, schedule_id, prefix)
        if stored is None:
            raise
        return _answer(session, schedule_id, stored, body)
    names = {who.id: who.name for who in people}
    batch_id = rows[0].id
    row_ids = [(row.id, row.contact_id) for row in rows]
    results = []
    for row_id, contact_id in row_ids:
        results.append(_result(contact_id, names, await _dispatch_one(batch_id, row_id, user)))
    return BatchSendOut(batch_id=batch_id, results=results, replayed=False, in_progress=False)


async def _dispatch_one(batch_id: int, row_id: int, user: User) -> Outcome:
    """한 사람. 문의 판정 그대로 — 뜻밖의 오류는 나갔는지 모르므로 「확인 필요」(다시 보내지 않는다)."""
    try:
        return await gate.dispatch("message", row_id, service._actor(user), now=service._now())
    except Exception as exc:  # noqa: BLE001 — 한 사람의 오류가 묶음을 멈추지 않게
        logger.error("묶음 %s 의 줄 %s 를 문에 넣다 오류가 났습니다: %s", batch_id, row_id, type(exc).__name__)
        return Outcome("unsure", gate.UNSURE)


def stats(session: Session, schedule_id: int, batch_id: int) -> BatchStatsOut:
    """그 일정의 묶음 셈. 없거나 다른 일정 묶음이면 404."""
    mine = select(OutreachMessage.id).where(OutreachMessage.schedule_id == schedule_id,
                                            OutreachMessage.batch_id == batch_id, OutreachMessage.direction == "out")
    total = session.scalar(select(func.count()).select_from(mine.subquery())) or 0
    if not total:
        raise ApiError(404, "not_found", BATCH_NOT_FOUND)
    sent = session.scalar(select(func.count()).select_from(mine.where(OutreachMessage.status.in_(_SENT)).subquery()))
    replied = session.scalar(select(func.count(func.distinct(OutreachMessage.contact_id))).where(
        OutreachMessage.schedule_id == schedule_id, OutreachMessage.direction == "in",
        OutreachMessage.reply_to_id.in_(mine)))
    return BatchStatsOut(total=total, sent=sent or 0, replied=replied or 0)

