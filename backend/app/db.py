"""SQLite 연결. 파일은 <Settings.data_dir>/chronos.db."""

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.points import quotes  # noqa: F401  근거 문장 표(point_quotes)도 create_all 전에
from app.security.passwords import hash_password
from app.store import (
    devices,  # noqa: F401  기기 세션 표(user_devices)도 create_all 전에
    tables_outreach,  # noqa: F401  계획 4 표를 Base 에 올린다(init_db 의 create_all 전에)
    ui_states,  # noqa: F401  화면 상태 표(열어 둔 창·탭)도 create_all 전에
    wallpapers,  # noqa: F401  내 사진 배경 표도 create_all 전에
)
from app.store.tables import Base, User
from app.store.upgrade import add_missing_columns

_engine: Engine | None = None


def init_db() -> None:
    """표를 만들고(기존 표에 빠진 칸은 더하고), 첫 관리자가 없으면 만든다(있으면 건드리지 않는다)."""
    global _engine
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    _engine = create_engine(f"sqlite:///{settings.data_dir / 'chronos.db'}", hide_parameters=True)  # 오류 글에 값(번호) 없이
    Base.metadata.create_all(_engine)
    add_missing_columns(_engine, Base.metadata)  # 지금 모델에 더해진 칸을 기존 DB 에도 더한다
    with Session(_engine) as session:
        found = session.scalar(select(User).where(User.login_id == settings.admin_id))
        if found is None:
            session.add(
                User(
                    login_id=settings.admin_id,
                    name="관리자",
                    role="admin",
                    password_hash=hash_password(settings.admin_password),
                )
            )
            session.commit()


def current_engine() -> Engine | None:
    """init_db 뒤의 엔진(아직이면 None)."""
    return _engine


def close_db() -> None:
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None


def get_session() -> Iterator[Session]:
    """FastAPI 의존성: 요청마다 세션 하나."""
    with Session(_engine) as session:
        yield session
