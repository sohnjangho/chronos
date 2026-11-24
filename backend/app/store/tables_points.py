"""관리 포인트 카드·근거 문장 표 — app.db 가 create_all 전에 올린다(app.points·app.llm 을 끌어오지 않게 여기 둔다)."""

from datetime import UTC, datetime

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.store.tables import Base
from app.store.tables_outreach import UtcDateTime


class PointCard(Base):
    __tablename__ = "point_cards"

    schedule_id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(primary_key=True)
    what_if: Mapped[bool] = mapped_column(primary_key=True)
    data_json: Mapped[dict] = mapped_column(JSON)  # {basis, new, more, tightened, removed, diff, trigger}
    points_json: Mapped[list] = mapped_column(JSON)  # 그때의 포인트(store.points 꼴)
    risk_status: Mapped[str]
    risks_json: Mapped[list] = mapped_column(JSON, default=list)  # [asdict(risk.Risk)]
    generation: Mapped[int] = mapped_column(default=0)  # 다시 적을 때마다 +1 — 늦게 끝난 옛 찾기가 덮어쓰지 않게
    changed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)  # 이 차이를 처음 적은 때(주의할 일정의 「최근」)
    outdoor_json: Mapped[dict] = mapped_column(JSON, default=dict)  # 액티비티 → 실외 작업인가(LLM weather_sensitive, 고른 것만)
    shown_generation: Mapped[int] = mapped_column(default=0)  # 옛 칸(쓰지 않음 — 이미 만든 DB 의 NOT NULL 때문에 둔다)
    shown_json: Mapped[dict] = mapped_column(JSON, default=dict)  # 대화(chat_session_id) → 카드를 낸 차이 지문(shown_mark)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime)


class PointQuote(Base):
    __tablename__ = "point_quotes"

    schedule_id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(primary_key=True)
    activity_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), primary_key=True)  # weather·materials·fx·business
    status: Mapped[str] = mapped_column(String(10))
    quotes_json: Mapped[list] = mapped_column(JSON, default=list)  # [{text, url, title}]
    error_code: Mapped[str | None] = mapped_column(String(20), default=None)
    updated_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
