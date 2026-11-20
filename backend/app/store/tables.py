"""모든 ORM 표. 다음 작업들도 여기에 표를 더한다."""

from datetime import UTC, date, datetime

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
    # 제공자가 알린 끝난 까닭(stop·length·tool_calls …). 알리지 않았거나 실패면 None
    finish_reason: Mapped[str | None] = mapped_column(String(20), default=None)


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
    # 공정률 가중치: 'duration'(기간 비례) | 'manual'(액티비티 manual_weight). 버전에 들지 않는다.
    weight_mode: Mapped[str] = mapped_column(String(10), default="duration")


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


class ScheduleDraft(Base):
    """생성 루프가 만든 일정 초안. 저장(일정·버전)은 승인 뒤에 따로 한다. 모양은 app/store/drafts.py."""

    __tablename__ = "schedule_drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_session_id: Mapped[int | None] = mapped_column(default=None)  # 대화 id (FK 아님)
    domain: Mapped[str] = mapped_column(String(50))
    level: Mapped[str] = mapped_column(String(2))  # 'L1'..'L5'
    schedule_json: Mapped[dict] = mapped_column(JSON)  # store.schedules.to_json 결과(맞춤 전 일정)
    conditions_json: Mapped[list[dict]] = mapped_column(JSON, default=list)  # [Condition.to_dict()]
    report_json: Mapped[dict] = mapped_column(JSON)  # 마지막 점검(CheckReport) 모양
    assumptions_json: Mapped[list[dict]] = mapped_column(JSON, default=list)  # [{label, value, source}]
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    used_at: Mapped[datetime | None] = mapped_column(default=None)  # 승인되어 일정으로 저장된 때
    schedule_id: Mapped[int | None] = mapped_column(default=None)  # 그때 만든 일정 (FK 아님)


class Approval(Base):
    """에이전트가 낸 변경 하나(첫 저장 또는 일정 고침)와 그 결정. 모양은 app/store/approvals.py 가 정한다.

    status: pending(승인 대기) | approved | rejected | conflict(승인하려 했으나 그 사이 일정이 바뀜) | auto(자동 적용).
    """

    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int | None] = mapped_column(default=None)  # 첫 저장은 승인 뒤에 정해진다 (FK 아님)
    draft_id: Mapped[int | None] = mapped_column(default=None)  # 첫 저장의 초안 (FK 아님)
    kind: Mapped[str] = mapped_column(String(10))  # 'first_save' | 'change' | 'rule'
    title: Mapped[str] = mapped_column(String(100))
    reasons_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    base_version: Mapped[int]  # 이 버전 위에 쌓는다. 첫 저장은 0
    summary_json: Mapped[dict] = mapped_column(JSON)  # 화면 요약(준공·크리티컬·조건 변화·점검·기한 여유)
    diff_json: Mapped[list[dict]] = mapped_column(JSON, default=list)  # 바뀌는 액티비티 [{activity_id, …}]
    snapshot_json: Mapped[dict] = mapped_column(JSON)  # 반영할 일정(store.schedules.to_json)
    conditions_json: Mapped[list[dict]] = mapped_column(JSON, default=list)  # 반영할 조건 목록
    changes_json: Mapped[list[dict]] = mapped_column(JSON, default=list)  # 변경 이력에 남길 [{id, field, from, to}]
    status: Mapped[str] = mapped_column(String(10), default="pending")
    retry: Mapped[bool] = mapped_column(default=False)  # 거부하면서 에이전트에게 다시 짜게 했는가
    version: Mapped[int | None] = mapped_column(default=None)  # 반영해서 생긴 버전
    restore_to: Mapped[int | None] = mapped_column(default=None)  # 자동 적용을 되돌릴 버전
    request: Mapped[str] = mapped_column(Text, default="")  # 대화의 마지막 사용자 글(200자)
    chat_session_id: Mapped[int | None] = mapped_column(default=None)  # 낸 대화 (FK 아님)
    requested_by: Mapped[str] = mapped_column(String(100))
    # 변경을 낸 쪽: 'agent'(에이전트 도구) | 'user'(조건·규칙 화면 확정). 반영한 버전의 by_kind 가 된다.
    # 기본값이 있어서 기존 DB 에는 시작할 때 칸이 더해진다(store.upgrade, 있던 줄은 'agent').
    requested_kind: Mapped[str] = mapped_column(String(10), default="agent")
    decided_by: Mapped[str | None] = mapped_column(String(100), default=None)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    decided_at: Mapped[datetime | None] = mapped_column(default=None)
    # 묶음 2. 이어진 것: 'scenario'(만약에 복사본 반영) | 'rule'(내 규칙) 과 그 id (FK 아님)
    link_kind: Mapped[str | None] = mapped_column(String(10), default=None)
    link_id: Mapped[int | None] = mapped_column(default=None)
    reset_plan: Mapped[bool] = mapped_column(default=False)  # 쓰지 않음(PM 11-20: Plan 다시 잡기 없앰, 늘 False)
    rule_json: Mapped[dict | None] = mapped_column(JSON, default=None)  # kind 'rule' 이 넣을 내 규칙


class Setting(Base):
    """작업 공간 설정 한 줄(key → value). 지금은 approval_mode 하나."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(String(200))


class ChatSession(Base):
    """대화 하나. 만든 사용자만 본다. title 은 첫 사용자 글(40자)이고 그 전에는 빈 글이다."""

    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(100), default="")
    schedule_id: Mapped[int | None] = mapped_column(default=None)  # 대화가 다루는 일정 (FK 아님)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class ChatMessage(Base):
    """대화 메시지 하나. role: user | assistant | tool. 모양은 app/store/chats.py 가 정한다."""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("chat_sessions.id"), index=True)
    role: Mapped[str] = mapped_column(String(10))
    content_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class WorkflowRun(Base):
    """도구를 하나 이상 부른 턴 하나의 실행 기록."""

    __tablename__ = "workflow_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_session_id: Mapped[int] = mapped_column(ForeignKey("chat_sessions.id"), index=True)
    title: Mapped[str] = mapped_column(String(100))
    request: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="running")  # running|done|failed|stopped
    started_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    ended_at: Mapped[datetime | None] = mapped_column(default=None)
    tokens: Mapped[int] = mapped_column(default=0)  # 턴의 LLM 입력 + 출력 토큰
    cost: Mapped[float | None] = mapped_column(default=None)  # 턴의 비용 합(알려 준 것이 없으면 None)


class WorkflowStep(Base):
    """실행 기록의 한 단계 = 도구 호출 한 번. input_json·output_json 은 JSON 글."""

    __tablename__ = "workflow_steps"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    n: Mapped[int]  # 1부터
    tool: Mapped[str] = mapped_column(String(100))
    program: Mapped[str | None] = mapped_column(String(50), default=None)
    why: Mapped[str] = mapped_column(Text, default="")  # 호출 앞의 에이전트 글(200자)
    status: Mapped[str] = mapped_column(String(10), default="running")  # running|done|failed|stopped
    input_json: Mapped[str] = mapped_column(Text, default="{}")
    output_json: Mapped[str | None] = mapped_column(Text, default=None)  # 실패면 {"error": …}
    ms: Mapped[int | None] = mapped_column(default=None)
    model: Mapped[str | None] = mapped_column(String(200), default=None)  # 이 호출을 낸 LLM 답의 모델
    tokens: Mapped[int] = mapped_column(default=0)  # 그 LLM 답의 입력 + 출력 토큰
    cost: Mapped[float | None] = mapped_column(default=None)


# ── 묶음 2 (FK 없음) ────────────────────────────────────────────────


class Scenario(Base):
    """만약에 복사본: 저장된 일정과 따로 둔 일정 하나. 반영할 때만 승인(approval_id)으로 들어간다.

    source: 'agent' | 'shorten'(단축안) | 'delay'(지연). status: 'open' | 'submitted' | 'applied' | 'discarded'.
    """

    __tablename__ = "scenarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int] = mapped_column(index=True)
    base_version: Mapped[int]  # 이 버전에서 떠 왔다
    name: Mapped[str] = mapped_column(String(100))
    source: Mapped[str] = mapped_column(String(10))
    snapshot_json: Mapped[dict] = mapped_column(JSON)  # store.schedules.to_json 결과
    conditions_json: Mapped[list[dict]] = mapped_column(JSON)
    moves_json: Mapped[list[dict]] = mapped_column(JSON, default=list)  # 적용한 단축 수
    delay_event_ids: Mapped[list[int]] = mapped_column(JSON, default=list)  # 넣은 지연 사건
    summary_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(10), default="open")
    approval_id: Mapped[int | None] = mapped_column(default=None)
    created_by: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class DelayEvent(Base):
    """지연 사건 하나. status 'open'(아직 일정에 없음) → 'reflected'(반영한 버전 reflected_version).

    responsibility: 'owner'(발주처) | 'ours' | 'force'(불가항력) | 'undecided'. source: 'chat' | 'actual' | 'user'.
    """

    __tablename__ = "delay_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int] = mapped_column(index=True)
    activity_id: Mapped[str] = mapped_column(String(50))
    start_date: Mapped[date]
    days: Mapped[int]
    cause: Mapped[str] = mapped_column(Text, default="")
    responsibility: Mapped[str] = mapped_column(String(10), default="undecided")
    daily_cost: Mapped[int | None] = mapped_column(default=None)  # 하루 금액(원)
    evidence: Mapped[str] = mapped_column(String(200), default="")
    source: Mapped[str] = mapped_column(String(10), default="chat")
    status: Mapped[str] = mapped_column(String(10), default="open")
    impact_json: Mapped[dict] = mapped_column(JSON, default=dict)  # 마지막 영향 계산
    analyzed_version: Mapped[int | None] = mapped_column(default=None)  # 영향을 계산한 버전
    reflected_version: Mapped[int | None] = mapped_column(default=None)
    created_by: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class MyRule(Base):
    """내 규칙 하나(조건 dict). scope 'domain' 이면 그 분야 일정 모두, 'schedule' 이면 schedule_id 만."""

    __tablename__ = "my_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(String(10))
    domain: Mapped[str] = mapped_column(String(50))
    schedule_id: Mapped[int | None] = mapped_column(default=None)
    condition_json: Mapped[dict] = mapped_column(JSON)  # Condition.to_dict() 모양
    enabled: Mapped[bool] = mapped_column(default=True)
    approval_id: Mapped[int | None] = mapped_column(default=None)  # 넣게 한 승인 건
    created_by: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class EvidenceSearch(Base):
    """근거 검색 한 번(실패도 남긴다). 키는 담지 않는다."""

    __tablename__ = "evidence_searches"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_session_id: Mapped[int | None] = mapped_column(default=None, index=True)
    query: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(10))  # 'web' | 'scholar' …
    ok: Mapped[bool]
    error_code: Mapped[str | None] = mapped_column(String(20), default=None)
    result_count: Mapped[int] = mapped_column(default=0)
    latency_ms: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class EvidenceItem(Base):
    """근거 검색 결과 한 줄."""

    __tablename__ = "evidence_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    search_id: Mapped[int] = mapped_column(index=True)
    title: Mapped[str] = mapped_column(String(300))
    url: Mapped[str] = mapped_column(String(1000))
    hostname: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    published: Mapped[str | None] = mapped_column(String(20), default=None)
    extra_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class EvidenceLink(Base):
    """근거 한 줄이 받친 것: 일정·초안·조건·가정 가운데 있는 것."""

    __tablename__ = "evidence_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    evidence_id: Mapped[int] = mapped_column(index=True)
    schedule_id: Mapped[int | None] = mapped_column(default=None)
    draft_id: Mapped[int | None] = mapped_column(default=None)
    condition_id: Mapped[str | None] = mapped_column(String(100), default=None)
    assumption_label: Mapped[str | None] = mapped_column(String(100), default=None)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class TraceEvent(Base):
    """실행 추적 한 줄: 턴(turn_id) 안의 맥락 조립·LLM 호출·끝. 키는 담지 않는다.

    kind: 'context' | 'llm' | 'end'. cost 는 제공자가 알려 줄 때만(없으면 None).
    """

    __tablename__ = "trace_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_session_id: Mapped[int] = mapped_column(index=True)
    turn_id: Mapped[int] = mapped_column(index=True)
    run_id: Mapped[int | None] = mapped_column(default=None)  # 실행 기록(workflow_runs)
    seq: Mapped[int]  # 턴 안 차례
    kind: Mapped[str] = mapped_column(String(10))
    label: Mapped[str] = mapped_column(String(100), default="")
    started_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    ms: Mapped[int | None] = mapped_column(default=None)
    model: Mapped[str | None] = mapped_column(String(200), default=None)
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    cost: Mapped[float | None] = mapped_column(default=None)
    ok: Mapped[bool] = mapped_column(default=True)
    error: Mapped[str | None] = mapped_column(String(200), default=None)
    input_text: Mapped[str] = mapped_column(Text, default="")
    output_text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class Visual(Base):
    """보고서용 그림 한 장(Task 44): 코드가 만든 표(table_json)와 Liner Visualization 이 그린 HTML, 숫자 대조 결과.

    input_hash = 요청 글·종류·버전·기준일의 sha256. 같은 입력의 verified 그림이 있으면 다시 부르지 않는다.
    fallback 이면 화면은 html 대신 우리 그림(SVG)을 그리고 note 를 보인다. checks_json = {problems, external}.
    """

    __tablename__ = "visuals"

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int] = mapped_column(index=True)
    version: Mapped[int]
    kind: Mapped[str] = mapped_column(String(20))
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    data_date: Mapped[date | None] = mapped_column(default=None)
    table_json: Mapped[dict] = mapped_column(JSON)  # {title, columns, rows, chart}
    html: Mapped[str] = mapped_column(Text, default="")
    theme: Mapped[str] = mapped_column(String(40), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    resource_id: Mapped[str] = mapped_column(String(100), default="")
    verified: Mapped[bool] = mapped_column(default=False)
    passed: Mapped[int] = mapped_column(default=0)
    total: Mapped[int] = mapped_column(default=0)
    checks_json: Mapped[dict] = mapped_column(JSON, default=dict)
    attempts: Mapped[int] = mapped_column(default=0)
    fallback: Mapped[bool] = mapped_column(default=False)
    note: Mapped[str] = mapped_column(String(200), default="")
    latency_ms: Mapped[int | None] = mapped_column(default=None)
    created_by: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
