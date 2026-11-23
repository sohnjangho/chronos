"""번호 보기 기록(Task 72 — 주소록 API 의 감사 기록). 표는 app.store.tables_outreach.ContactReveal(번호 칸 없음).

record_reveal 은 세기와 넣기를 한 문장으로 한다: INSERT … SELECT … WHERE (그 사용자의 창 안 기록 수) < limit.
SQLite 에서 쓰는 문장은 시작할 때 쓰기 잠금(RESERVED)을 잡고 나서 읽으므로, 동시에 들어온 요청도 한 문장씩 차례로 세고
넣는다 — 상한을 넘는 줄은 어떤 경우에도 기록되지 않는다. commit 은 부른 쪽.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, insert, literal, select
from sqlalchemy.orm import Session

from app.store.tables_outreach import ContactReveal, UtcDateTime

__all__ = ["count_reveals", "record_reveal"]


def _recent(user_id: int, since: datetime):
    return select(func.count()).select_from(ContactReveal).where(ContactReveal.user_id == user_id,
                                                                 ContactReveal.at >= since)


def record_reveal(
    session: Session, *, schedule_id: int, contact_id: int, user_id: int, login_id: str, limit: int,
    window: timedelta, at: datetime | None = None,
) -> bool:
    """at(기본 지금)에 번호를 본 기록 한 줄을, 그 사용자가 [at - window, …) 에 본 횟수가 limit 보다 적을 때만 넣는다.
    login_id 는 그때의 로그인 id(사용자를 지워 id 가 다시 쓰여도 누군지 남게). 넣었으면 True, 상한이라 넣지 않았으면 False.
    한 문장이다(모듈 머리 글)."""
    at = at or datetime.now(UTC)
    row = select(literal(schedule_id), literal(contact_id), literal(user_id), literal(login_id),
                 literal(at, UtcDateTime)).where(_recent(user_id, at - window).scalar_subquery() < limit)
    done = session.execute(insert(ContactReveal).from_select(
        ["schedule_id", "contact_id", "user_id", "login_id", "at"], row))
    return done.rowcount == 1


def count_reveals(session: Session, user_id: int, *, since: datetime) -> int:
    """그 사용자가 since 뒤(같은 시각 포함)에 번호를 본 횟수."""
    return session.scalar(_recent(user_id, since)) or 0
