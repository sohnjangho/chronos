"""한 사람 여러 프로젝트·관리자 등급(11-24 PM)의 밑 함수. 주소록은 그대로 프로젝트(일정)마다 줄이 따로고(하네스·연락 기록·
들어오는 문이 contacts.schedule_id 를 본다), 같은 사람의 줄들을 person_key 로 잇는다.

- 함께 저장되는 칸(SHARED_COPIED + 수신 거부): 한 줄을 고치면 같은 열쇠의 모든 줄(숨긴 줄도)에 같은 값. 수신 거부는 줄마다
  service._settle_do_not_contact 가 번호 기록 규칙으로 맞춘다(번호 기준 전체 — 들어오는 문도 번호로 본다).
- 프로젝트마다 따로인 칸: 협력사·담당·근무시간·메모·숨김.
- 관리자 등급(access_level)을 정하거나 바꾸는 것은 관리자만(check_level — 403 admin_only_level). 바뀐 줄마다
  contact_access_changes 에 한 줄(번호 없음)과 로그 한 줄.
- 옛 줄(이 칸 전)은 person_key 가 비어 있다 — 혼자인 사람이고, 잇는 순간 ensure_key 가 열쇠를 준다.
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.programs.contacts.schemas import ProjectLink
from app.store.tables import ScheduleRecord, User
from app.store.tables_outreach import (
    Contact,
    ContactAccessChange,
    ContactCompany,
    new_person_key,
)

logger = logging.getLogger(__name__)

# 같은 사람의 줄에 그대로 옮기는 칸(수신 거부·까닭은 줄마다 번호 기록 규칙으로 — service._settle_do_not_contact)
SHARED_COPIED = ("name", "gender", "language", "voice_mode", "voice_id", "can_sms", "can_kakao", "can_call", "access_level")
# 요청에 이 칸이 하나라도 있으면 같은 사람의 다른 줄에도 저장한다
SHARED_INPUT = frozenset({*SHARED_COPIED, "phone", "do_not_contact", "dnc_reason"})
ADMIN_LEVEL = "관리자 등급은 관리자만 정하거나 바꿀 수 있습니다."
DEFAULT_LEVEL = "trade"
MANAGER_LEVEL = "manager"


def ensure_key(row: Contact) -> str:
    """그 줄의 사람 열쇠(옛 줄이면 지금 새로 준다)."""
    if not row.person_key:
        row.person_key = new_person_key()
    return row.person_key


def linked(session: Session, row: Contact) -> list[Contact]:
    """같은 사람의 **다른** 줄(모든 프로젝트, 숨긴 줄도), id 순. 열쇠가 없으면 []."""
    if not row.person_key:
        return []
    return list(session.scalars(select(Contact).where(Contact.person_key == row.person_key, Contact.id != row.id)
                                .order_by(Contact.id)))


def copy_shared(source: Contact, target: Contact) -> None:
    """함께 저장되는 칸을 source 에서 target 으로(번호가 바뀌면 「잘못된 번호」 표시는 내린다). 수신 거부는 옮기지 않는다."""
    for column in SHARED_COPIED:
        setattr(target, column, getattr(source, column))
    if target.phone != source.phone:
        target.phone, target.phone_invalid = source.phone, False


def check_level(user: User | None, before: list[str | None], wanted: str) -> None:
    """등급을 정하거나 바꾸는가(새 줄은 before None — 기본 trade 로 본다). 그렇다면 관리자만, 아니면 403(아무것도 바꾸기 전)."""
    changes = any((level or DEFAULT_LEVEL) != wanted for level in before)
    if changes and (user is None or user.role != "admin"):
        raise ApiError(403, "admin_only_level", ADMIN_LEVEL)


def record_level(session: Session, row: Contact, before: str | None, user: User) -> None:
    """등급 기록 한 줄(바뀐 줄만 — 새 줄은 before None, 기본 등급의 새 줄은 남기지 않는다). commit 은 부른 쪽."""
    if before == row.access_level or (before is None and row.access_level == DEFAULT_LEVEL):
        return
    session.flush()  # 새 줄의 id
    session.add(ContactAccessChange(schedule_id=row.schedule_id, contact_id=row.id, user_id=user.id, login_id=user.login_id,
                                    before=before, after=row.access_level))
    logger.info("관리자 등급: 사용자 %s · 일정 %s · 연락처 %s · %s → %s", user.id, row.schedule_id, row.id,
                before or "-", row.access_level)


def project_counts(session: Session, schedule_id: int, people: list[Contact]) -> dict[int, int]:
    """연락처 id → 그 사람이 (숨기지 않고) 등록된 프로젝트 수(이 프로젝트는 늘 셈). 한 번의 질의."""
    keys = {person.person_key for person in people if person.person_key}
    seen: dict[str, set[int]] = {}
    if keys:
        rows = session.execute(select(Contact.person_key, Contact.schedule_id)
                               .where(Contact.person_key.in_(keys), Contact.hidden.is_(False)))
        for key, sid in rows:
            seen.setdefault(key, set()).add(sid)
    return {person.id: len(seen.get(person.person_key or "", set()) | {schedule_id}) for person in people}


def project_links(session: Session, row: Contact) -> list[ProjectLink]:
    """그 사람이 등록된 프로젝트(숨긴 줄은 빼고, 지금 연 줄은 늘), 일정 id 순."""
    rows = [row, *(other for other in linked(session, row) if not other.hidden)]
    out = []
    for person in sorted(rows, key=lambda r: (r.schedule_id, r.id)):
        schedule = session.get(ScheduleRecord, person.schedule_id)
        company = session.get(ContactCompany, person.company_id)
        if schedule is None:
            continue
        out.append(ProjectLink(schedule_id=person.schedule_id, name=schedule.name, contact_id=person.id,
                               company_id=person.company_id, company_name=company.name if company else "",
                               current=person.id == row.id))
    return out
