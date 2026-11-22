"""승인 건(approvals): 만들기·읽기·목록·반영·결정 기록.

한 줄 = 에이전트가 낸 변경 하나. kind 'first_save'(초안을 새 일정으로) | 'change'(일정 고침, base_version 위에)
| 'rule'(분야 범위 내 규칙 저장 — 일정은 건드리지 않는다).
반영할 내용(snapshot_json·conditions_json·changes_json)과 화면에 보일 것(summary_json·diff_json)을 낼 때 정해 둔다.
status: pending → approved | rejected(retry 면 에이전트가 다시 짠다) | conflict, 또는 처음부터 auto(자동 적용).
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.store import links
from app.store.drafts import get_draft
from app.store.schedules import NotFound, create_schedule, from_json, load
from app.store.tables import Approval, ChangeLog, ChatMessage, ChatSession, Scenario
from app.store.versions import mark_plan, save_new_version
from app.store.view import plan_changed

__all__ = [
    "AGENT_NAME", "REQUEST_LIMIT", "STATUS_GROUPS", "DraftUsed", "NotFound", "apply", "create", "get", "last_request",
    "listed", "pending_count", "pending_for_draft", "pending_retries", "record_decision", "was_resumed",
]

AGENT_NAME = "에이전트"  # 자동 적용한 버전의 작성자
REQUEST_LIMIT = 200
STATUS_GROUPS = {"pending": ("pending",), "decided": ("approved", "rejected", "conflict"), "auto": ("auto",)}


class DraftUsed(Exception):
    """첫 저장을 반영하려는데 초안이 이미 일정으로 저장됐다(초안은 한 번만 쓴다)."""


def create(session: Session, **fields: Any) -> Approval:
    """승인 표에 한 줄을 넣고 flush 한다(id 가 생긴다). commit 은 부르는 쪽이 한다. 칸은 tables.Approval."""
    row = Approval(**fields)
    session.add(row)
    session.flush()
    return row


def get(session: Session, approval_id: int) -> Approval:
    """없으면 NotFound."""
    row = session.get(Approval, approval_id)
    if row is None:
        raise NotFound(approval_id)
    return row


def listed(session: Session, group: str) -> list[Approval]:
    """STATUS_GROUPS 의 한 묶음(pending·decided·auto), 새것부터."""
    query = select(Approval).where(Approval.status.in_(STATUS_GROUPS[group])).order_by(Approval.id.desc())
    return list(session.scalars(query))


def pending_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Approval).where(Approval.status == "pending"))


def pending_for_draft(session: Session, draft_id: int) -> bool:
    """이 초안의 승인 건이 아직 결정을 기다리는가."""
    query = select(Approval.id).where(Approval.draft_id == draft_id, Approval.status == "pending")
    return session.scalar(query) is not None


def last_request(session: Session, chat_session_id: int | None) -> str:
    """대화의 마지막 사용자 글(kind text), 앞 200자. 대화가 없거나 글이 없으면 빈 글."""
    if chat_session_id is None:
        return ""
    query = (
        select(ChatMessage.content_json)
        .where(ChatMessage.session_id == chat_session_id, ChatMessage.role == "user")
        .order_by(ChatMessage.id.desc())
    )
    text = next((c.get("text", "") for c in session.scalars(query) if c.get("kind") == "text"), "")
    return text[:REQUEST_LIMIT]


def _plan_change(session: Session, row: Approval) -> bool:
    """고침 건(change)을 반영한 버전이 Plan 을 새로 찍는가(PM 결정 11-20 밤, store.versions).

    - 복사본 반영: 지연 반영안(source 'delay')만 물려받고, 단축안·에이전트 복사본은 계획 변경.
    - 일정 범위 내 규칙: 계획 변경.
    - 그 밖(에이전트 고침·조건 확정·실적 입력): 조건이 바뀌었거나 계획 칸이 바뀌었으면 계획 변경, 실적·Data Date 만
      바꿨으면(schedule.record_actual) 물려받는다. 계획 칸과 실적을 같이 바꾸면 계획 변경이다.
    """
    # 에이전트 op 이 실적 칸을 받게 되면 이 분류를 다시 볼 것(지금 op 은 od·이름·선행·더함·지움뿐).
    if row.link_kind == "scenario":
        scenario = session.get(Scenario, row.link_id)
        return scenario is None or scenario.source != "delay"
    if row.link_kind == "rule":
        return True
    before, conditions, _ = load(session, row.schedule_id, row.base_version)
    return list(row.conditions_json) != conditions or plan_changed(before, from_json(row.snapshot_json))


def apply(session: Session, row: Approval, *, by_name: str) -> None:
    """승인 건의 변경을 일정에 넣는다. flush 만 하고 commit 하지 않는다. row.schedule_id·row.version 을 채운다.

    새 버전·변경 이력의 by_kind 는 변경을 낸 쪽(row.requested_kind: "agent" | "user", 예전 줄은 "agent")이다.
    - change: base_version 위에 새 버전. 그 사이 바뀌었으면 VersionConflict(아무것도 쓰지 않음). 계획 변경인지는 _plan_change.
    - first_save: 초안의 분야·정밀도로 새 일정(이름 = 제목)과 버전 1을 만들고 「처음 계획」으로 표시한다(is_plan). 변경 이력 한 줄을 남기고
      초안을 쓴 것(used_at·schedule_id)으로 표시한다. 초안이 이미 쓰였으면 DraftUsed(아무것도 쓰지 않음).
    - rule: 일정은 건드리지 않는다(schedule_id·version 그대로 None). 내 규칙은 links.after_apply 가 만든다.
    반영한 뒤 이어진 것(복사본·지연 사건·내 규칙)에 알린다(store.links.after_apply).
    """
    if row.kind == "rule":
        links.after_apply(session, row)
        session.flush()
        return
    schedule, conditions = from_json(row.snapshot_json), list(row.conditions_json)
    by_kind = row.requested_kind or "agent"
    if row.kind == "change":
        row.version = save_new_version(
            session, row.schedule_id, schedule, conditions, by_kind=by_kind, by_name=by_name, note=row.title,
            changes=list(row.changes_json), base_version=row.base_version,
            plan_change=_plan_change(session, row), commit=False,
        )
        links.after_apply(session, row)
        return
    draft = get_draft(session, row.draft_id)
    if draft.used_at is not None:
        raise DraftUsed(draft.id)
    sid = create_schedule(
        session, name=row.title, domain=draft.domain, level=draft.level, schedule=schedule, conditions=conditions,
        by_kind=by_kind, by_name=by_name, note=row.title, commit=False,
    )
    mark_plan(session, sid, 1, commit=False)
    session.add(ChangeLog(schedule_id=sid, version_n=1, by_kind=by_kind, by_name=by_name, summary=row.title))
    draft.used_at, draft.schedule_id = datetime.now(UTC), sid
    row.schedule_id, row.version = sid, 1
    if row.chat_session_id is not None:
        chat = session.get(ChatSession, row.chat_session_id)
        if chat is not None:
            chat.schedule_id = sid
    links.after_apply(session, row)
    session.flush()


def record_decision(session: Session, row: Approval, status: str, *, by: str, note: str, retry: bool = False) -> bool:
    """결정(approved·rejected·conflict)을 적는다 — DB 에서 아직 pending 일 때만(조건부 UPDATE 한 문).

    다른 사람이 먼저 결정했으면 아무것도 바꾸지 않고 False(부르는 쪽이 rollback 한다). commit 은 부르는 쪽이 한다.
    """
    result = session.execute(
        update(Approval)
        .where(Approval.id == row.id, Approval.status == "pending")
        .values(status=status, decided_by=by, note=note, retry=retry, decided_at=datetime.now(UTC))
        .execution_options(synchronize_session=False)
    )
    session.expire(row, ["status", "decided_by", "note", "retry", "decided_at"])  # 다음에 읽을 때 DB 값으로
    return result.rowcount == 1


def _resumed(session: Session, chat_ids: list[int]) -> set[tuple[int, int]]:
    """(대화 id, 승인 건 id): 그 대화에서 이미 이어 간 거부(approval_rejected 메시지)."""
    query = select(ChatMessage.session_id, ChatMessage.content_json).where(
        ChatMessage.session_id.in_(chat_ids),
        ChatMessage.role == "user",
        ChatMessage.content_json["kind"].as_string() == "approval_rejected",
    )
    return {(chat_id, c.get("approval_id")) for chat_id, c in session.execute(query)}


def was_resumed(session: Session, chat_id: int, approval_id: int) -> bool:
    """이 승인 건의 거부로 이미 대화를 이어 갔는가(approval_rejected 메시지가 있는가)."""
    return (chat_id, approval_id) in _resumed(session, [chat_id])


def pending_retries(session: Session, chat_ids: list[int]) -> dict[int, list[Approval]]:
    """대화마다 아직 이어 가지 않은 '거부하고 다시 짜기' 건(status rejected·retry), 오래된 것부터.

    대화 주인만 이어 갈 수 있으므로, 다른 사람이 결정한 건은 주인이 대화 화면에서 보고 시작한다.
    """
    if not chat_ids:
        return {}
    resumed = _resumed(session, chat_ids)
    query = (
        select(Approval)
        .where(Approval.chat_session_id.in_(chat_ids), Approval.status == "rejected", Approval.retry)
        .order_by(Approval.id)
    )
    out: dict[int, list[Approval]] = {}
    for row in session.scalars(query):
        if (row.chat_session_id, row.id) not in resumed:
            out.setdefault(row.chat_session_id, []).append(row)
    return out
