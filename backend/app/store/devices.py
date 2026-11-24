"""기기 세션(계정별 접속 상태·기기 로그아웃). 로그인마다 기기 줄 하나에 묶고(토큰에 그 줄 id), 관리자가 그 줄을 닫으면
그 기기의 다음 요청은 401 이다(app.security.deps.current_user 가 기본 키로 한 번 읽는다).

device_key 는 브라우저마다 화면이 만든 임의 값이다(관리자 응답에는 내보내지 않는다). 브라우저·OS 는 서버가 User-Agent 를
작은 고정 낱말로 줄여 둔다 — 접속 주소(IP)와 User-Agent 원문은 두지 않는다. 줄은 지우지 않는다(닫힌 줄이 감사 기록:
revoked_at·revoked_by). 30일 넘게 신호가 없는 기기는 목록에서만 뺀다.

표는 app.db 가 import 해서 create_all 전에 Base 에 올린다 — 새 DB·기존 DB 모두 시작할 때 create_all 이 만든다.
"""

import re
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import Index, String, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.store.tables import Base
from app.store.tables_outreach import UtcDateTime
from app.store.timeutil import as_utc

ONLINE_WINDOW = timedelta(minutes=2)
HIDE_AFTER = timedelta(days=30)
KINDS = ("desktop", "tablet", "phone")
OTHER = "기타"


def utcnow() -> datetime:
    """지금(UTC). 시험이 바꿔 끼운다."""
    return datetime.now(UTC)


class UserDevice(Base):
    __tablename__ = "user_devices"
    __table_args__ = (Index("ix_user_devices_user_key", "user_id", "device_key"), {"sqlite_autoincrement": True})

    id: Mapped[int] = mapped_column(primary_key=True)  # 토큰의 sid. 지운 뒤에도 같은 id 를 다시 쓰지 않는다
    user_id: Mapped[int]
    device_key: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(10))  # desktop | tablet | phone
    browser: Mapped[str] = mapped_column(String(20))  # Chrome | Safari | Edge | Firefox | 기타
    os: Mapped[str] = mapped_column(String(20))  # macOS | Windows | iOS | Android | Linux | 기타
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    last_seen_at: Mapped[datetime] = mapped_column(UtcDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    revoked_by: Mapped[int | None] = mapped_column(default=None)  # 닫은 관리자 users.id


_BROWSERS = (  # 앞에서부터: Edge·삼성 등은 Chrome 글을 함께 담는다
    (re.compile(r"Edg(e|A|iOS)?/"), "Edge"),
    (re.compile(r"SamsungBrowser/|OPR/|Opera|Whale/|YaBrowser/|KAKAOTALK|NAVER"), OTHER),
    (re.compile(r"Firefox/|FxiOS/"), "Firefox"),
    (re.compile(r"Chrome/|CriOS/|Chromium/"), "Chrome"),
    (re.compile(r"Version/[\d.]+.*Safari/"), "Safari"),
)
_SYSTEMS = (
    (re.compile(r"iPhone|iPad|iPod"), "iOS"),
    (re.compile(r"Android"), "Android"),
    (re.compile(r"Windows"), "Windows"),
    (re.compile(r"Macintosh|Mac OS X"), "macOS"),
    (re.compile(r"Linux|X11|CrOS"), "Linux"),
)


def parse_user_agent(ua: str) -> tuple[str, str]:
    """User-Agent → (브라우저, OS) 고정 낱말. 모르면 기타."""
    browser = next((name for pattern, name in _BROWSERS if pattern.search(ua)), OTHER)
    system = next((name for pattern, name in _SYSTEMS if pattern.search(ua)), OTHER)
    return browser, system


def kind_from_user_agent(ua: str) -> str:
    """화면이 kind 를 보내지 않은 로그인(예전 화면·스크립트)용 거친 짐작."""
    if re.search(r"iPhone|iPod|Android.*Mobile|Windows Phone", ua):
        return "phone"
    if re.search(r"iPad|Tablet|Android", ua):
        return "tablet"
    return "desktop"


def _fill(row: UserDevice, kind: str, ua: str, now: datetime) -> None:
    row.kind = kind
    row.browser, row.os = parse_user_agent(ua)
    row.last_seen_at = now


def open_device(session: Session, user_id: int, device_key: str | None, kind: str | None, ua: str) -> UserDevice:
    """로그인·예전 토큰의 첫 신호: 이 사용자·이 브라우저의 열린 줄을 이어 쓰고, 없으면(닫혔으면) 새 줄. 커밋한다."""
    now = utcnow()
    key = device_key or secrets.token_urlsafe(16)
    row = session.scalar(
        select(UserDevice)
        .where(UserDevice.user_id == user_id, UserDevice.device_key == key, UserDevice.revoked_at.is_(None))
        .order_by(UserDevice.id.desc())
        .limit(1)
    )
    if row is None:
        row = UserDevice(user_id=user_id, device_key=key, created_at=now)
        session.add(row)
    _fill(row, kind or kind_from_user_agent(ua), ua, now)
    session.commit()
    return row


def touch(session: Session, row: UserDevice, kind: str, ua: str) -> None:
    """접속 신호: 마지막 접속 시각과 기기 모양을 고친다. 커밋한다."""
    _fill(row, kind, ua, utcnow())
    session.commit()


def active_device(session: Session, device_id: int, user_id: int) -> UserDevice | None:
    """토큰의 기기 줄이 그 사용자 것이고 닫히지 않았으면 그 줄(요청마다 기본 키로 한 번 읽는다)."""
    row = session.get(UserDevice, device_id)
    return row if row is not None and row.user_id == user_id and row.revoked_at is None else None


def revoke(session: Session, row: UserDevice, actor_id: int) -> UserDevice:
    """기기 로그아웃. 이미 닫힌 줄은 그대로 둔다(처음 닫은 사람·시각을 지키려고). 커밋한다."""
    if row.revoked_at is None:
        row.revoked_at = utcnow()
        row.revoked_by = actor_id
        session.commit()
    return row


def revoke_all(session: Session, user_id: int, actor_id: int) -> None:
    """그 사용자의 열린 기기 줄을 모두 닫는다(계정 삭제). 커밋은 부르는 쪽."""
    now = utcnow()
    for row in session.scalars(select(UserDevice).where(UserDevice.user_id == user_id, UserDevice.revoked_at.is_(None))):
        row.revoked_at = now
        row.revoked_by = actor_id


def is_online(row: UserDevice, now: datetime) -> bool:
    return row.revoked_at is None and as_utc(row.last_seen_at) >= now - ONLINE_WINDOW


def visible_devices(session: Session) -> list[UserDevice]:
    """목록에 보일 기기(30일 안에 신호가 있던 것), 사용자·최근 접속 순."""
    since = utcnow() - HIDE_AFTER
    return list(
        session.scalars(
            select(UserDevice)
            .where(UserDevice.last_seen_at >= since)
            .order_by(UserDevice.user_id, UserDevice.last_seen_at.desc(), UserDevice.id.desc())
        )
    )


def online_counts(session: Session) -> tuple[int, int]:
    """지금 접속 중인 (사람 수, 기기 수)."""
    since = utcnow() - ONLINE_WINDOW
    where = (UserDevice.revoked_at.is_(None), UserDevice.last_seen_at >= since)
    people = session.scalar(select(func.count(func.distinct(UserDevice.user_id))).where(*where)) or 0
    count = session.scalar(select(func.count()).select_from(UserDevice).where(*where)) or 0
    return people, count
