"""모든 ORM 표. 다음 작업들도 여기에 표를 더한다."""

from datetime import UTC, datetime

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    login_id: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(10))  # 'admin' | 'user'
    password_hash: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class LlmConnection(Base):
    """LLM 연결. 키는 암호문(secret_ciphertext)과 끝 4자리만 둔다."""

    __tablename__ = "llm_connections"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(30))  # 'liner' | 'openai_compatible'
    base_url: Mapped[str] = mapped_column(String(500))
    secret_ciphertext: Mapped[str] = mapped_column(Text)
    secret_last4: Mapped[str] = mapped_column(String(4))
    is_default: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(10), default="unknown")  # 'ok' | 'failed' | 'unknown'
    model_count: Mapped[int | None] = mapped_column(default=None)
    checked_at: Mapped[datetime | None] = mapped_column(default=None)
    latency_ms: Mapped[int | None] = mapped_column(default=None)
    # 마지막으로 성공한 연결 시험의 모델 id 목록
    models_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class LlmAssignment(Base):
    """쓰임새(purpose)마다 어느 연결의 어느 모델을 쓸지."""

    __tablename__ = "llm_assignments"

    purpose: Mapped[str] = mapped_column(String(10), primary_key=True)  # light|normal|hard|longdoc
    connection_id: Mapped[int | None] = mapped_column(ForeignKey("llm_connections.id"))
    model: Mapped[str] = mapped_column(String(200))
    routing_strategy: Mapped[str | None] = mapped_column(String(10))  # cost|balanced|quality


class LlmCall(Base):
    """LLM 호출 한 번의 기록(실패도 남긴다). 주고받은 글과 키는 담지 않는다."""

    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_session_id: Mapped[int | None] = mapped_column(default=None)  # 대화 id (FK 아님)
    purpose: Mapped[str] = mapped_column(String(10))
    model: Mapped[str] = mapped_column(String(200))  # 실제로 답한 모델(실패면 요청한 모델)
    requested_model: Mapped[str] = mapped_column(String(200))
    routing_strategy: Mapped[str | None] = mapped_column(String(10))
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    cost: Mapped[float | None] = mapped_column(default=None)
    latency_ms: Mapped[int]
    ok: Mapped[bool]
    error_code: Mapped[str | None] = mapped_column(String(20), default=None)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class ScheduleRecord(Base):
    """일정 하나. 내용은 버전(schedule_versions)에 있고, 여기에는 지금 버전 번호만 둔다."""

    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    domain: Mapped[str] = mapped_column(String(50))
    level: Mapped[str] = mapped_column(String(2))  # 'L1'..'L5'
    current_version: Mapped[int] = mapped_column(default=1)
    created_by: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class ScheduleVersion(Base):
    """일정의 한 버전. 고칠 때마다 새로 쌓고 지우지 않는다."""

    __tablename__ = "schedule_versions"

    schedule_id: Mapped[int] = mapped_column(ForeignKey("schedules.id"), primary_key=True)
    n: Mapped[int] = mapped_column(primary_key=True)
    snapshot_json: Mapped[dict] = mapped_column(JSON)  # store.schedules.to_json 결과
    conditions_json: Mapped[list[dict]] = mapped_column(JSON, default=list)
    note: Mapped[str] = mapped_column(Text, default="")
    by_kind: Mapped[str] = mapped_column(String(10))  # 'user' | 'agent'
    by_name: Mapped[str] = mapped_column(String(100))
    is_plan: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class ChangeLog(Base):
    """새 버전을 만든 고침 한 번. changes_json 은 [{id, field, from, to}]."""

    __tablename__ = "change_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int] = mapped_column(ForeignKey("schedules.id"))
    version_n: Mapped[int]
    by_kind: Mapped[str] = mapped_column(String(10))
    by_name: Mapped[str] = mapped_column(String(100))
    summary: Mapped[str] = mapped_column(Text, default="")
    changes_json: Mapped[list[dict]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class QuestionnaireRecord(Base):
    """에이전트가 만든 질문을 담은 질문지 하나. 모양은 app/store/questionnaires.py 가 정한다."""

    __tablename__ = "questionnaires"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_session_id: Mapped[int | None] = mapped_column(default=None)  # 대화 id (FK 아님)
    purpose: Mapped[str] = mapped_column(String(10))  # generate|delay|report|recovery|clarify
    title: Mapped[str] = mapped_column(String(100))
    domain: Mapped[str | None] = mapped_column(String(50), default=None)
    level: Mapped[str | None] = mapped_column(String(2), default=None)  # 'L1'..'L5'
    round: Mapped[int] = mapped_column(default=1)  # 몇 번째 묻는가(최대 2)
    questions_json: Mapped[list[dict]] = mapped_column(JSON)  # [Question]
    answers_json: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)  # {질문 id: 답}
    prefilled_json: Mapped[list[dict]] = mapped_column(JSON, default=list)  # [{label, value, source}]
    status: Mapped[str] = mapped_column(String(10), default="open")  # 'open' | 'submitted'
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    submitted_at: Mapped[datetime | None] = mapped_column(default=None)
