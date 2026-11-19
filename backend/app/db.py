"""SQLite 연결. 파일은 <Settings.data_dir>/chronos.db."""

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.security.passwords import hash_password
from app.store.tables import Base, User

_engine: Engine | None = None


def init_db() -> None:
    """표를 만들고, 첫 관리자가 없으면 만든다(있으면 건드리지 않는다)."""
    global _engine
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    _engine = create_engine(f"sqlite:///{settings.data_dir / 'chronos.db'}")
    Base.metadata.create_all(_engine)
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


def close_db() -> None:
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None


def get_session() -> Iterator[Session]:
    """FastAPI 의존성: 요청마다 세션 하나."""
    with Session(_engine) as session:
        yield session
