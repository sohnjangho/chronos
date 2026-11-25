"""접속 기록: 로그인한 사람의 API 요청 한 번 = 한 줄(무엇을 썼는지). 줄은 지우지 않는다.

접속 주소(IP)·User-Agent 원문은 두지 않는다(기기는 user_devices 의 브라우저·OS 낱말로만 — app.store.devices 와 같은 방침).
저절로 도는 요청(접속 신호·화면 상태 저장·개발 콘솔 읽기)은 빼고, 같은 사람·같은 길의 GET 이 1분 안에 되풀이되면 건너뛴다.
기록은 요청과 따로 짧은 세션으로 쓰며, 실패해도 삼킨다 — 기록 때문에 응답이 달라지면 안 된다.

표는 app.db 가 import 해서 create_all 전에 Base 에 올린다.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import Index, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.store.tables import Base
from app.store.tables_outreach import UtcDateTime

log = logging.getLogger(__name__)

REPEAT_WINDOW = timedelta(minutes=1)
LOGIN_ROUTE = "/api/auth/login"
SKIP_PREFIXES = ("/api/me/presence", "/api/me/ui-state", "/api/health", "/api/devconsole", "/api/auth/me")
SKIP_ROUTES = {LOGIN_ROUTE}  # 로그인은 라우터가 성공·실패를 직접 적는다(실패는 토큰이 없어 미들웨어가 모른다)


class ActivityLog(Base):
    __tablename__ = "activity_log"
    __table_args__ = (Index("ix_activity_log_user_at", "user_id", "at"), {"sqlite_autoincrement": True})

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(default=None)  # 로그인 실패에서 계정을 못 찾으면 None
    at: Mapped[datetime] = mapped_column(UtcDateTime)
    method: Mapped[str] = mapped_column(String(10))
    route: Mapped[str] = mapped_column(String(200))  # 길 틀(/api/schedules/{schedule_id}/delays)
    feature: Mapped[str] = mapped_column(String(60))
    schedule_id: Mapped[int | None] = mapped_column(default=None)
    device_id: Mapped[int | None] = mapped_column(default=None)
    status: Mapped[int] = mapped_column(default=0)
    note: Mapped[str | None] = mapped_column(String(60), default=None)  # 로그인 실패 때 입력한 아이디(앞 20자)


_WRITE = {"POST", "PUT", "PATCH", "DELETE"}
# (길 틀 안에 들어 있는 낱말, 읽기 이름, 쓰기 이름). 앞에서부터 처음 맞는 것. 길 틀이 정확히 같은 것은 _EXACT 가 먼저.
_EXACT = {
    ("POST", "/api/chat/sessions/{chat_id}/messages"): "에이전트 질문",
    ("POST", "/api/chat/sessions"): "새 대화",
    ("POST", "/api/chat/sessions/{chat_id}/stop"): "대화 멈춤",
    ("POST", "/api/auth/logout"): "로그아웃",
    ("POST", "/api/schedules"): "일정 만들기",
    ("DELETE", "/api/schedules/{schedule_id}"): "일정 지우기",
    ("POST", "/api/approvals/{approval_id}/decide"): "승인 결정",
    ("POST", "/api/schedules/{schedule_id}/versions/{n}/restore"): "버전 되돌리기",
}
_PARTS = (
    ("/chat", "대화 보기", "대화"),
    ("/approvals", "승인함 보기", "승인 설정"),
    ("/conditions", "조건 보기", "조건 바꾸기"),
    ("/contacts", "연락처 보기", "연락처 편집"),
    ("/delays", "지연 분석 보기", "지연 분석"),
    ("/scenarios", "만회 시나리오 보기", "만회 시나리오"),
    ("/points", "관리 포인트 보기", "관리 포인트"),
    ("/field", "현장 진도 보기", "현장 진도"),
    ("/outreach", "연락 보기", "연락 보내기"),
    ("/visuals", "그림 보기", "그림 만들기"),
    ("/reports", "보고서 보기", "보고서 만들기·고치기"),
    ("/versions", "버전 비교", "버전 바꾸기"),
    ("/activities", "작업 보기", "작업 편집"),
    ("/files", "파일 보기", "파일 올리기·고치기"),
    ("/evidence", "근거 보기", "근거 관리"),
    ("/questionnaire", "설문 보기", "설문 답하기"),
    ("/workflows", "업무 흐름 보기", "업무 흐름 저장"),
    ("/rules", "규칙 보기", "규칙 바꾸기"),
    ("/llm", "LLM 설정 보기", "LLM 설정 바꾸기"),
    ("/notify", "알림 설정 보기", "알림 설정 바꾸기"),
    ("/info", "외부 API 설정 보기", "외부 API 설정 바꾸기"),
    ("/auth/users", "계정 보기", "계정 관리"),
    ("/attention", "할 일 보기", "할 일"),
    ("/progress", "진도 보기", "진도 입력"),
    ("/projects", "프로젝트 보기", "프로젝트 바꾸기"),
    ("/wallpaper", "배경 보기", "배경 바꾸기"),
    ("/schedules", "일정 보기", "일정 편집"),
)


def feature_name(method: str, route: str) -> str:
    """요청 → 기능 이름. 표에 없으면 길 틀 그대로."""
    if (method, route) in _EXACT:
        return _EXACT[(method, route)]
    for part, read, write in _PARTS:
        if part in route:
            return write if method in _WRITE else read
    return route


def skipped(route: str) -> bool:
    return route in SKIP_ROUTES or route.startswith(SKIP_PREFIXES) or not route.startswith("/api/")


def utcnow() -> datetime:
    return datetime.now(UTC)


def record(session: Session, *, user_id: int | None, method: str, route: str, status: int,
           schedule_id: int | None = None, device_id: int | None = None, note: str | None = None,
           feature: str | None = None) -> bool:
    """한 줄 쓴다(같은 사람·같은 길 GET 이 1분 안이면 건너뛰고 False)."""
    now = utcnow()
    if method == "GET" and user_id is not None:
        same_schedule = (ActivityLog.schedule_id.is_(None) if schedule_id is None
                         else ActivityLog.schedule_id == schedule_id)
        last = session.scalar(
            select(ActivityLog.at).where(ActivityLog.user_id == user_id, ActivityLog.method == "GET",
                                         ActivityLog.route == route, same_schedule)
            .order_by(ActivityLog.id.desc()).limit(1))
        if last is not None and now - _aware(last) < REPEAT_WINDOW:
            return False
    session.add(ActivityLog(user_id=user_id, at=now, method=method, route=route[:200],
                            feature=(feature or feature_name(method, route))[:60], schedule_id=schedule_id,
                            device_id=device_id, status=status, note=note))
    session.commit()
    return True


def record_safely(engine, **kw) -> None:
    """미들웨어·로그인용: 따로 세션을 열어 쓰고, 어떤 실패도 삼킨다."""
    if engine is None:
        return
    try:
        with Session(engine) as session:
            record(session, **kw)
    except Exception:
        log.warning("접속 기록을 쓰지 못했습니다", exc_info=True)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
