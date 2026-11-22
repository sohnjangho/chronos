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
    "LlmHealthOut",
    "NodeDetail",
    "NodeOut",
    "QdrantHealthOut",
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
    edges_lit: list[str] = Field(default_factory=list)  # 실제 실행된 분기: check_repair·approval_inbox·approval_auto·vision_turn·files_used·weather_used
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


class StopTurnOut(BaseModel):
    chat_session_id: int
    stopped: bool


class ToolToggleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class ToolToggleOut(BaseModel):
    name: str
    enabled: bool
