"""열어 둔 창·탭(화면 형태 desktop·tablet·phone 마다 한 줄) — 계정에 붙어 기기 사이를 따라간다.

창 자리·프로그램 id·탭 이름·작은 id 만 둔다(번호·글은 받지 않는다 — app.programs.ui_state.schemas). 나중에 쓴 것이
이긴다(updated_at 은 서버 시각). FK 는 두지 않는다: 계정을 지우면 줄이 남지만, 계정이 만들어지기 전 줄은 내보내지 않는다
(지운 계정의 id 를 새 계정이 다시 받아도 앞 사람 것이 보이지 않게). app.db 가 import 해서 create_all 이 표를 만든다.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, String, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.store.tables import Base, User
from app.store.timeutil import as_utc


class UiState(Base):
    __tablename__ = "ui_states"

    user_id: Mapped[int] = mapped_column(primary_key=True)
    mode: Mapped[str] = mapped_column(String(10), primary_key=True)  # 'desktop' | 'tablet' | 'phone' | 'appearance'(바탕화면 배경)
    state_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


def _iso(dt: datetime) -> str:
    return as_utc(dt).isoformat()


def get_all(session: Session, user: User) -> dict[str, dict[str, Any]]:
    """그 사람의 화면 형태별 상태 {mode: {state, updated_at}}. 계정보다 오래된 줄은 뺀다."""
    born = as_utc(user.created_at)
    rows = session.scalars(select(UiState).where(UiState.user_id == user.id)).all()
    return {
        r.mode: {"state": r.state_json, "updated_at": _iso(r.updated_at)}
        for r in rows
        if as_utc(r.updated_at) >= born
    }


def put(session: Session, user: User, mode: str, state: dict[str, Any]) -> str:
    """덮어쓴다(나중에 쓴 것이 이긴다). 서버 시각 updated_at 을 돌려준다.

    한 문장 upsert(INSERT … ON CONFLICT DO UPDATE) — 두 기기의 첫 저장이 겹쳐도 겹침 오류 없이 나중 것이 남는다.
    """
    now = datetime.now(UTC)
    stmt = sqlite_insert(UiState).values(user_id=user.id, mode=mode, state_json=state, updated_at=now)
    stmt = stmt.on_conflict_do_update(
        index_elements=[UiState.user_id, UiState.mode],
        set_={"state_json": stmt.excluded.state_json, "updated_at": stmt.excluded.updated_at},
    )
    session.execute(stmt)
    session.commit()
    return _iso(now)
