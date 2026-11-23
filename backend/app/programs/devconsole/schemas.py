from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.store.traces import UsageGroup, UsageOut

__all__ = [
    "ActiveTurnOut",
    "AgentConfigOut",
    "AgentConfigPatch",
    "DbHealthOut",
    "HealthOut",
    "HolidayHealthOut",
    "InfoApiHealthOut",
    "InfoConnOut",
    "LlmHealthOut",
    "NodeDetail",
    "NodeOut",
    "QdrantHealthOut",
    "ReuseHealthOut",
    "SearchHealthOut",
    "StopTurnOut",
    "StructureOut",
    "TimelineItem",
    "ToolToggleIn",
    "ToolToggleOut",
    "TurnDetail",
    "TurnOut",
    "UsageGroup",
    "UsageOut",
    "VisionHealthOut",
]

TurnStatus = Literal["running", "done", "failed", "stopped"]


class TurnOut(BaseModel):
    turn_id: int  # 그 턴의 사용자 메시지 id
    chat_session_id: int
    user_name: str  # 대화 주인
    request: str  # 모델이 읽은 사용자 글 앞 60자
    started_at: datetime
    status: TurnStatus  # end 사건이 없으면: 그 대화에서 턴이 돌고 있고 마지막 턴이면 running, 아니면 stopped
    llm_calls: int  # 루프의 모델 호출 + 도구 안 호출
    tool_calls: int  # 실행 기록의 단계 수
    tokens: int  # 입력 + 출력
    cost: float | None  # 알려 준 비용의 합. 없으면 null
    ms: int | None  # 턴 전체 시간. 끝나지 않았으면 null


class NodeDetail(BaseModel):
    """칸의 자세한 것. in/out 은 칸마다 모양이 다르다(서비스 문서 참고)."""

    model_config = ConfigDict(populate_by_name=True)

    in_: Any = Field(default=None, alias="in")
    out: Any = None
    ms: int | None = None
    model: str | None = None  # 모델 칸(plan·judge)이 쓴 모델. 코드 칸은 null
    settings: str | None = None  # 관련 설정 글(check·approval)


class NodeOut(BaseModel):
    key: str
    label: str
    state: Literal["past", "now", "todo", "skipped"]
    count: int
    detail: NodeDetail


class StructureOut(BaseModel):
    nodes: list[NodeOut]
    loop_count: int  # llm 사건 수
    limit: int  # MAX_STEPS
    # 실제 실행된 분기: check_repair·approval_inbox·approval_auto·vision_turn·files_used·weather_used·skill_matched·
    # self_corrected, 11-23: vision_tool(도구가 그림 읽기 모델을 부름)·단계 신호(TimelineItem.signals)의 합
    edges_lit: list[str] = Field(default_factory=list)
    harness_summary: dict[str, Any] | None = None  # 하네스 점검 요약(rounds·passed·violations·uncheckable·tools)


class TimelineItem(BaseModel):
    seq: int  # 시간표 안 차례(1부터)
    kind: Literal["context", "llm", "tool", "inner_llm"]
    label: str
    started_at: datetime  # tool 은 그 도구를 부른 답이 끝난 때부터 앞 단계 시간을 더한 어림
    ms: int | None
    model: str | None
    input_tokens: int
    output_tokens: int
    cost: float | None
    ok: bool
    error: str | None
    input_text: str
    output_text: str
    parallel_group: int | None  # tool: 그 도구를 부른 llm 사건의 seq(한 답이 함께 부른 도구는 같다). 그 밖은 null
    # tool: 그 단계 기록이 보여 주는 신호(info_used·evidence_reused·evidence_fresh·import_confirmed·import_refused·
    # repair_stopped·role_blocked). 그 밖은 빈 목록
    signals: list[str] = Field(default_factory=list)


class TurnDetail(BaseModel):
    turn: TurnOut
    structure: StructureOut
    timeline: list[TimelineItem]


class AgentConfigOut(BaseModel):
    approval_mode: Literal["all", "important", "auto"]
    max_steps: int = Field(ge=4, le=24)
    max_check_retries: int = Field(ge=1, le=10)
    tool_output_limit: int = Field(ge=1000, le=16000)
    history_limit: int = Field(ge=6, le=60)
    enable_skill_match: bool
    enable_self_reflection: bool


class AgentConfigPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_mode: Literal["all", "important", "auto"] | None = None
    max_steps: int | None = Field(default=None, ge=4, le=24)
    max_check_retries: int | None = Field(default=None, ge=1, le=10)
    tool_output_limit: int | None = Field(default=None, ge=1000, le=16000)
    history_limit: int | None = Field(default=None, ge=6, le=60)
    enable_skill_match: bool | None = None
    enable_self_reflection: bool | None = None


class LlmHealthOut(BaseModel):
    status: Literal["ok", "warn", "error"]
    connections_count: int
    assignments_count: int
    default_name: str | None = None
    default_provider: str | None = None
    default_base_url: str | None = None
    key_ready: bool
    message: str


class QdrantHealthOut(BaseModel):
    status: Literal["ok", "off", "error"]
    collections: list[str] = Field(default_factory=list)
    points_count: int = 0
    latency_ms: int | None = None
    message: str


class SearchHealthOut(BaseModel):
    status: Literal["ok", "warn"]
    ready: bool
    calls_7d: int
    failed_7d: int
    message: str


class DbHealthOut(BaseModel):
    status: Literal["ok"]
    size_bytes: int
    counts: dict[str, int]


class InfoConnOut(BaseModel):
    """정보 API 연결 한 줄. 주소·키·끝 4자리는 내보내지 않는다(이름은 그 연결의 키로 한 번 더 지운다)."""

    id: int
    name: str
    kind: str  # kma(기상청 전용) | generic(범용)
    status: str  # ok | failed | unknown — 마지막 연결 시험
    checked_at: datetime | None


class InfoApiHealthOut(BaseModel):
    status: Literal["ok", "warn", "off"]  # off = 연결 없음, warn = 마지막 시험이 실패한 연결이 있다
    count: int
    connections: list[InfoConnOut]
    message: str


class ReuseHealthOut(BaseModel):
    reusable: int  # 지금 다시 쓸 수 있는 근거(붙은 것·days 일 안·다시 쓰지 않기 아님·웹/학술/법령/업체)
    reused_7d: int  # 최근 7일 저장된 근거를 다시 쓴 호출(Liner 를 부르지 않은 수)
    searches_7d: int  # 최근 7일 Liner 근거 검색(실패 포함, 날씨·정보 API·다시 쓰기 빼고)
    days: int  # 다시 쓰는 기간(evidence_reuse.REUSE_DAYS)


class HolidayHealthOut(BaseModel):
    status: Literal["ok", "warn"]  # warn = 올해나 내년 표가 없다
    years: list[int]
    counts: dict[int, int]  # 해마다 공휴일 수
    message: str


class VisionHealthOut(BaseModel):
    status: Literal["ok", "warn", "error"]  # warn = 연결 없음, error = 키를 읽을 수 없음
    model: str
    connection_name: str | None
    stored: bool  # 설정에 저장한 배정인가(아니면 기본 연결 + 기본 모델)
    key_ready: bool
    message: str


class ActiveTurnOut(BaseModel):
    chat_session_id: int
    title: str
    stop_requested: bool


class HealthOut(BaseModel):
    llm: LlmHealthOut
    qdrant: QdrantHealthOut
    search: SearchHealthOut
    db: DbHealthOut
    active_turns: list[ActiveTurnOut]
    # 11-23: 예전 화면은 이 칸을 모른다(읽지 않을 뿐)
    info_api: InfoApiHealthOut | None = None
    evidence_reuse: ReuseHealthOut | None = None
    holidays: HolidayHealthOut | None = None
    vision: VisionHealthOut | None = None


class StopTurnOut(BaseModel):
    chat_session_id: int
    stopped: bool


class ToolToggleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class ToolToggleOut(BaseModel):
    name: str
    enabled: bool
