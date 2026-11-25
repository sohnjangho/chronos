"""개발 콘솔 「접속 기록」: 계정별 대화(세션별)·만든 프로젝트·쓴 기능(app.store.activity)."""

from collections import Counter
from datetime import UTC, datetime

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.store.activity import ActivityLog
from app.store.devices import UserDevice
from app.store.tables import ChatMessage, ChatSession, ScheduleRecord, User

FEATURE_LIMIT = 500
TEXT_LIMIT = 2000


class AccountRow(BaseModel):
    user_id: int
    login_id: str
    name: str
    role: str
    last_at: datetime | None
    logins: int
    failed_logins: int
    chats: int
    features: int


class ChatLine(BaseModel):
    role: str  # user | assistant
    text: str
    at: datetime
    turn_id: int | None  # 사용자 글이면 「실행 추적」의 턴 id


class ChatOut(BaseModel):
    id: int
    title: str
    created_at: datetime
    schedule: str | None
    messages: list[ChatLine]


class ProjectOut(BaseModel):
    id: int
    name: str
    domain: str
    created_at: datetime


class FeatureLine(BaseModel):
    at: datetime
    feature: str
    method: str
    route: str
    schedule: str | None
    device: str | None
    status: int
    note: str | None


class FeatureCount(BaseModel):
    feature: str
    count: int


class AccountActivity(BaseModel):
    account: AccountRow
    chats: list[ChatOut]
    projects: list[ProjectOut]
    features: list[FeatureLine]
    summary: list[FeatureCount]


class UnknownLogin(BaseModel):
    at: datetime
    login_id: str


class AccountsOut(BaseModel):
    accounts: list[AccountRow]
    unknown_failed: list[UnknownLogin]  # 없는 아이디로 로그인 시도(최근 50)


def _utc(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=UTC) if dt is not None and dt.tzinfo is None else dt


def _row(session: Session, u: User) -> AccountRow:
    def count(*where) -> int:
        return session.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.user_id == u.id, *where)) or 0
    last = session.scalar(select(func.max(ActivityLog.at)).where(ActivityLog.user_id == u.id,
                                                                   ActivityLog.feature != "로그인 실패"))
    chats = session.scalar(select(func.count()).select_from(ChatSession).where(ChatSession.user_id == u.id)) or 0
    return AccountRow(user_id=u.id, login_id=u.login_id, name=u.name, role=u.role, last_at=_utc(last),
                      logins=count(ActivityLog.feature == "로그인"), failed_logins=count(ActivityLog.feature == "로그인 실패"),
                      chats=chats, features=count())


def accounts(session: Session) -> AccountsOut:
    rows = [_row(session, u) for u in session.scalars(select(User).order_by(User.id))]
    rows.sort(key=lambda r: r.last_at or datetime.min.replace(tzinfo=UTC), reverse=True)
    unknown = session.scalars(select(ActivityLog).where(ActivityLog.user_id.is_(None))
                              .order_by(ActivityLog.id.desc()).limit(50))
    return AccountsOut(accounts=rows, unknown_failed=[UnknownLogin(at=_utc(r.at), login_id=r.note or "") for r in unknown])


def _text(role: str, content: dict) -> str:
    if role == "user":
        kind = content.get("kind")
        if kind == "questionnaire_submitted":
            return "(설문 답 제출)"
        if kind == "approval_rejected":
            return "(승인 거절)"
    return (content.get("text") or "")[:TEXT_LIMIT]


def _chats(session: Session, user_id: int, names: dict[int, str]) -> list[ChatOut]:
    out = []
    for c in session.scalars(select(ChatSession).where(ChatSession.user_id == user_id).order_by(ChatSession.id.desc())):
        lines = []
        for m in session.scalars(select(ChatMessage).where(ChatMessage.session_id == c.id).order_by(ChatMessage.id)):
            if m.role not in ("user", "assistant"):
                continue
            text = _text(m.role, m.content_json or {})
            if not text:  # 도구만 부른 중간 답
                continue
            lines.append(ChatLine(role=m.role, text=text, at=_utc(m.created_at),
                                  turn_id=m.id if m.role == "user" else None))
        out.append(ChatOut(id=c.id, title=c.title or "(제목 없음)", created_at=_utc(c.created_at),
                           schedule=names.get(c.schedule_id) if c.schedule_id else None, messages=lines))
    return out


def account(session: Session, user_id: int) -> AccountActivity:
    u = session.get(User, user_id)
    if u is None:
        raise ApiError(404, "not_found", "계정을 찾을 수 없습니다.")
    names = {i: n for i, n in session.execute(select(ScheduleRecord.id, ScheduleRecord.name))}
    projects = [ProjectOut(id=s.id, name=s.name, domain=s.domain, created_at=_utc(s.created_at)) for s in
                session.scalars(select(ScheduleRecord).where(ScheduleRecord.created_by == u.name)
                                .order_by(ScheduleRecord.id.desc()))]
    devices = {d.id: f"{d.browser}/{d.os}" for d in session.scalars(select(UserDevice).where(UserDevice.user_id == user_id))}
    logs = list(session.scalars(select(ActivityLog).where(ActivityLog.user_id == user_id)
                                .order_by(ActivityLog.id.desc()).limit(FEATURE_LIMIT)))
    features = [FeatureLine(at=_utc(r.at), feature=r.feature, method=r.method, route=r.route,
                            schedule=names.get(r.schedule_id) if r.schedule_id else None,
                            device=devices.get(r.device_id) if r.device_id else None, status=r.status, note=r.note)
                for r in logs]
    every = Counter(f for (f,) in session.execute(select(ActivityLog.feature).where(ActivityLog.user_id == user_id)))
    summary = [FeatureCount(feature=f, count=n) for f, n in every.most_common()]
    return AccountActivity(account=_row(session, u), chats=_chats(session, user_id, names), projects=projects,
                           features=features, summary=summary)
