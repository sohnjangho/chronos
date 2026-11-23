"""연락 상대에게 말해도 되는 일정 사실(Task 67). 도구 schedule_fact·my_requests 와 주소록의 「연결된 작업」이 읽는다.

- find — 그 일정 **지금 버전**의 보기 자료(app.store.view — 화면·대화 에이전트와 같은 계산)에서 작업을 이름으로 찾아
  다섯 칸(id·이름·시작·종료·상태)만 준다. 금액·자원·여유·관계는 꺼내지 않는다. allowed 는 **꼭** 넘긴다: 집합이면 그 안의
  작업만(빈 집합은 「없음」 — 계산도 하지 않는다), None 은 「그 일정 전부」이고 내부 등급(Scope.facts "all")만 쓴다.
- allowed_for — 한 협력사·한 사람에게 말해도 되는 작업: 그 사람의 메시지·통화·현장 항목에 연결된 작업 + 이름이나 WBS 이름
  (윗 WBS 포함)에 협력사 공종 말이 든 작업 + 마일스톤. **그 일정의 협력사·연락처만** 센다 — 다른 일정의 id(같은 번호가 다른
  프로젝트에도 있을 때)는 버리고, 그 일정의 협력사가 하나도 남지 않으면 마일스톤도 주지 않는다(빈 집합).
"""

import re
import unicodedata
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.cpm import ScheduleError
from app.core.model import Activity, Schedule
from app.store import schedules, view
from app.store.tables import FieldItem
from app.store.tables_outreach import (
    Contact,
    ContactCompany,
    OutreachCall,
    OutreachMessage,
)

MILESTONES = ("start_ms", "finish_ms")
MIN_TRADE_WORD = 2  # 이보다 짧은 공종 말(「층」 등)은 거의 모든 작업 이름에 들어 있어 쓰지 않는다
_TRADE_SPLIT = re.compile(r"[\s,，/·・ㆍ‧|;()]+")  # 「철근·형틀」「거푸집, 형틀 및 타설」 — 한 글자 말(및)은 아래에서 빠진다


@dataclass(frozen=True)
class Fact:
    """작업 하나의 말해도 되는 다섯 칸. status 는 보기 자료의 상태 글(done · on_plan · late +n · early -n · new)."""

    id: str
    name: str
    start: date
    finish: date
    status: str


def _flat(text: str) -> str:
    """견줄 글: 같은 글자는 같은 꼴로(NFC·대소문자), 빈칸 없이."""
    return "".join(unicodedata.normalize("NFC", text).casefold().split())


def find(session: Session, schedule_id: int, query: str, *, allowed: Collection[str] | None, limit: int = 3) -> list[Fact]:
    """그 일정에서 이름에 query 의 낱말이 모두 든 작업(또는 id 가 query 인 작업). 이름이 꼭 같은 것 먼저, 그다음 시작일 순.
    없는 일정·계산할 수 없는 일정·빈 query 는 []."""
    words = [_flat(word) for word in query.split()]
    if not words or (allowed is not None and not allowed):
        return []
    try:
        rows = view.view_data(session, schedule_id)["activities"]
    except (schedules.NotFound, ScheduleError):
        return []
    whole = "".join(words)
    found = []
    for position, row in enumerate(rows):
        name = _flat(row["name"])
        if allowed is not None and row["id"] not in allowed:
            continue
        if all(word in name for word in words) or whole in name or _flat(row["id"]) == whole:
            found.append((name != whole, row["es"], position, Fact(row["id"], row["name"], row["es"], row["ef"], row["status"])))
    return [fact for *_, fact in sorted(found, key=lambda item: item[:3])[:limit]]


def names(session: Session, schedule_id: int) -> dict[str, str]:
    """그 일정 지금 버전의 작업 id → 이름. 없는 일정이면 {}."""
    try:
        schedule = schedules.load(session, schedule_id)[0]
    except schedules.NotFound:
        return {}
    return {activity.id: activity.name for activity in schedule.activities}


def linked(session: Session, schedule_id: int, contact_ids: Collection[int]) -> set[str]:
    """그 일정의 그 연락처들과 주고받은 메시지·통화, 거기 달린 현장 항목에 연결된 작업 id."""
    people = list(session.scalars(select(Contact.id).where(Contact.schedule_id == schedule_id, Contact.id.in_(contact_ids))))
    if not people:
        return set()
    found: set[str] = set()
    items: set[int] = set()
    for model in (OutreachMessage, OutreachCall):
        rows = session.execute(select(model.activity_id, model.field_item_id).where(
            model.schedule_id == schedule_id, model.contact_id.in_(people)))
        for activity_id, field_item_id in rows:
            found.update([activity_id] if activity_id else [])
            items.update([field_item_id] if field_item_id is not None else [])
    if items:
        found.update(session.scalars(select(FieldItem.activity_id).where(
            FieldItem.schedule_id == schedule_id, FieldItem.id.in_(items))))
    return found


def _trade_words(trades: Collection[str]) -> list[str]:
    words = {_flat(word) for trade in trades for word in _TRADE_SPLIT.split(trade)}
    return [word for word in words if len(word) >= MIN_TRADE_WORD]


def _wbs_names(schedule: Schedule, activity: Activity) -> str:
    """그 작업이 든 WBS 와 그 윗 WBS 들의 이름(이어 붙인 글)."""
    nodes = {node.code: node for node in schedule.wbs}
    out, code = [], activity.wbs
    while code in nodes and len(out) <= len(nodes):
        out.append(nodes[code].name)
        code = nodes[code].parent
    return " ".join(out)


def allowed_for(session: Session, schedule_id: int, company_ids: Collection[int], contact_ids: Collection[int]) -> set[str]:
    """그 일정에서 그 협력사·그 사람에게 말해도 되는 작업 id(모듈 머리 글). 그 일정의 협력사가 없으면 빈 집합."""
    trades = list(session.scalars(select(ContactCompany.trade).where(
        ContactCompany.schedule_id == schedule_id, ContactCompany.id.in_(company_ids))))
    if not trades:
        return set()
    try:
        schedule = schedules.load(session, schedule_id)[0]
    except schedules.NotFound:
        return set()
    words = _trade_words(trades)
    out = linked(session, schedule_id, contact_ids) & {activity.id for activity in schedule.activities}
    for activity in schedule.activities:
        text = _flat(f"{activity.name} {_wbs_names(schedule, activity)}")
        if activity.kind in MILESTONES or any(word in text for word in words):
            out.add(activity.id)
    return out
