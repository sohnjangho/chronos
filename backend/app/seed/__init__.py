"""시연용 씨앗 자료. `python -m app.seed demo` 로 가상 예시 일정을 만든다.

- 지금 있는 것(일정마다 모듈 하나):
  - `office` 「5층 사무동 신축」(건설·L3) — 액티비티 59개, 버전 1 처음 계획 → 버전 2 실적 입력.
  - `factory` 「가상 부품 공장 — 브래킷 BR-200 2만 개」(생산·L3) — 액티비티 30개, 처음 계획 하나뿐(실적 없음).
- 여러 번 돌려도 같다: 같은 이름의 일정과 그 일정에 딸린 줄을 먼저 지우고 새로 만든다. 다른 일정은 건드리지 않는다.
- LLM 을 부르지 않는다. 날짜는 넣지 않고(시작일·실적만) 계산은 core 가 한다.
- 일정을 더하려면 모듈 하나에 함수 하나(세션 → 일정 id)를 만들어 DEMO 에 넣는다.
- 사람·회사·현장은 모두 가상이다.
"""

import sys
from collections.abc import Callable, Sequence

from sqlalchemy import Engine, create_engine, delete, select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.seed.factory import FACTORY, parts_factory
from app.seed.office import CRANE_CONDITION, DATA_DATE, OFFICE, office_building
from app.store.tables import Base, ChatSession, ScheduleRecord
from app.store.upgrade import add_missing_columns

__all__ = ["CRANE_CONDITION", "DATA_DATE", "DEMO", "FACTORY", "OFFICE", "main", "seed_demo"]

# ── 지우고 만들기 ────────────────────────────────────────────────────────

DEMO: tuple[tuple[str, Callable[[Session], int]], ...] = ((OFFICE, office_building), (FACTORY, parts_factory))


def _clear(session: Session, name: str) -> None:
    """그 이름의 일정과 일정에 딸린 줄(schedule_id 칸이 있는 모든 표)을 지운다. 대화는 남기고 일정 연결만 끊는다."""
    ids = list(session.scalars(select(ScheduleRecord.id).where(ScheduleRecord.name == name)))
    if not ids:
        return
    session.execute(update(ChatSession).where(ChatSession.schedule_id.in_(ids)).values(schedule_id=None))
    for table in reversed(Base.metadata.sorted_tables):
        column = table.columns.get("schedule_id")
        if column is not None and table.name != ChatSession.__tablename__:
            session.execute(delete(table).where(column.in_(ids)))
    session.execute(delete(ScheduleRecord).where(ScheduleRecord.id.in_(ids)))


def seed_demo(session: Session) -> list[int]:
    """시연 일정을 모두 지우고 다시 만든다(한 트랜잭션). 만든 일정 id 를 차례로 준다."""
    try:
        for name, _ in DEMO:
            _clear(session, name)
        ids = [make(session) for _, make in DEMO]
        session.commit()
    except BaseException:
        session.rollback()
        raise
    return ids


def _engine() -> Engine:
    """앱과 같은 DB 파일. 표가 없으면 만든다(첫 관리자는 앱이 뜰 때 만든다)."""
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{settings.data_dir / 'chronos.db'}")
    Base.metadata.create_all(engine)
    add_missing_columns(engine, Base.metadata)
    return engine


def main(argv: Sequence[str]) -> int:
    if list(argv) != ["demo"]:
        print("사용법: python -m app.seed demo", file=sys.stderr)
        return 2
    engine = _engine()
    try:
        with Session(engine) as session:
            ids = seed_demo(session)
    finally:
        engine.dispose()
    print(f"시연 일정 {len(ids)}개를 만들었습니다: {', '.join(name for name, _ in DEMO)}")
    return 0

