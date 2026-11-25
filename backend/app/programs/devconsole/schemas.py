from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.store.settings import _ACCEL_WARN_RATIO_BOUNDS, POINTS_BOUNDS
from app.store.traces import SearchCount, UsageGroup, UsageOut, UsageTotals

__all__ = [
    "ActiveTurnOut",
    "AgentConfigOut",
    "AgentConfigPatch",
    "CallCount",
    "DbHealthOut",
    "DevUsageOut",
    "EventGroupCount",
    "HarnessItem",
    "HarnessMark",
    "HealthOut",
    "HolidayHealthOut",
    "InfoApiHealthOut",
    "InfoConnOut",
    "LlmHealthOut",
    "NodeDetail",
    "NodeOut",
    "NotifyDiagnosisOut",
    "NotifyHealthOut",
    "NotifyStepOut",
    "OutreachDetailOut",
    "OutreachHeadOut",
    "OutreachListOut",
    "OutreachRowOut",
    "OutreachUsageOut",
    "PointsAgentOut",
    "PointsComputeOut",
    "PointsConfigOut",
    "PointsConfigPatch",
    "PointsDomainOut",
    "PointsSearchOut",
    "PointsStageOut",
    "PresenceHealthOut",
    "QdrantHealthOut",
    "ReuseCount",
    "ReuseHealthOut",
    "SearchHealthOut",
    "StopTurnOut",
    "StructureOut",
    "TimelineItem",
    "ToolToggleIn",
    "ToolToggleOut",
    "TurnDetail",
    "TurnOut",
    "UpdateEntryOut",
    "UpdateItemOut",
    "UpdatesOut",
    "UsageCountersOut",
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
    cost: float | None  # 알려 준 비용(없으면 가격표 어림)의 합. 없으면 null
    ms: int | None  # 턴 전체 시간. 끝나지 않았으면 null
    cost_estimated: Literal["all", "some"] | None = None  # cost 합 속 가격표 어림: 모두 · 일부 · 없음


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


class HarnessMark(BaseModel):
    """연락 하네스 사건 한 줄(Task 108 — kind "harness" 인 줄만). 이름·묶음은 harness.types 의 상수에서 읽는다.
    사건의 자유 글(detail·evidence)은 싣지 않는다 — 정해 둔 코드(FIXED_DETAILS)·도구 이름·차례 번호만."""

    group: str | None  # EVENT_GROUPS 의 묶음. 모르는 사건은 null
    group_label: str
    rule: str | None  # 사건 이름(코드). 모르는 사건은 null
    verdict: Literal["blocked", "allowed", "noted"] | None
    verdict_label: str
    attempt: int | None  # 보내기 시도 차례(1부터) — 판정 메모·문 판정·통로 결과만
    order: int | None  # 나가는 문의 차례(GATE_RULES 의 열쇠)
    code: str | None  # 정해 둔 detail 코드(FIXED_DETAILS) 또는 도구 이름
    needs_check: bool  # 통로 결과 unsure — 「확인 필요」(실패가 아니다)
    unknown: bool  # 모양이 틀렸거나 낱말에 없는 사건 — 「알 수 없는 사건」


class TimelineItem(BaseModel):
    seq: int  # 시간표 안 차례(1부터)
    kind: Literal["context", "llm", "tool", "inner_llm", "harness"]
    label: str
    started_at: datetime  # tool 은 그 도구를 부른 답이 끝난 때부터 앞 단계 시간을 더한 어림
    ms: int | None
    model: str | None
    input_tokens: int
    output_tokens: int
    cost: float | None
    cost_estimated: bool = False  # cost 가 가격표 어림인가
    ok: bool
    error: str | None
    input_text: str
    output_text: str
    parallel_group: int | None  # tool: 그 도구를 부른 llm 사건의 seq(한 답이 함께 부른 도구는 같다). 그 밖은 null
    # tool: 그 단계 기록이 보여 주는 신호(info_used·evidence_reused·evidence_fresh·import_confirmed·import_refused·
    # repair_stopped·role_blocked). 그 밖은 빈 목록
    signals: list[str] = Field(default_factory=list)


class HarnessItem(TimelineItem):
    """연락 기록의 시간표 줄(Task 108): 턴과 같은 TimelineItem 꼴 + 하네스 표지. kind 는 늘 "harness"."""

    harness: HarnessMark


class OutreachRowOut(BaseModel):
    """연락 기록 한 줄(문자·카카오톡·통화). 번호는 가린 꼴만, 글·받아쓰기·제공사 id 는 없다."""

    kind: Literal["message", "call"]
    id: int
    at: datetime  # 줄을 만든 때
    direction: str  # out | in
    channel: str  # sms | kakao | call
    origin: str  # user | agent | peer
    origin_name: str
    send_mode: str | None  # manual | approved | delegated
    caller_class: str | None
    status: str
    contact_name: str | None  # 주소록 이름(없으면 「모르는 번호」)
    company_name: str | None
    number_masked: str  # 010-****-0199 꼴
    schedule_name: str | None
    events: int  # 하네스 사건 수
    needs_check: bool  # 보냈는지 확인 필요(unconfirmed)


class OutreachListOut(BaseModel):
    items: list[OutreachRowOut]  # 새것부터
    more: bool  # 상한 밖에 더 있다
    limit: int


class OutreachHeadOut(OutreachRowOut):
    approved_by: str | None
    fail_reason: str | None  # 번호·비밀을 지운 글
    reply_to_id: int | None
    duration_s: int | None = None  # 통화 시간(초) — 문자는 null (Task 110)
    transcript_lines: int | None = None  # 받아쓰기 줄 수만(글은 싣지 않는다) — 문자는 null


class EventGroupCount(BaseModel):
    key: str  # EVENT_GROUP_KEYS 하나 또는 "unknown"
    label: str
    count: int


class OutreachFlowVerdict(BaseModel):
    verdict: str | None
    label: str  # 시간표 줄의 판정 글(확인 필요 포함)
    count: int


class OutreachFlowNode(BaseModel):
    """연락 흐름도 마디 하나(Task 109): inbound · tool · post_check · gate · channel."""

    key: str
    label: str
    count: int  # 그 마디의 사건 수
    verdicts: list[OutreachFlowVerdict]


class OutreachDetailOut(BaseModel):
    head: OutreachHeadOut
    timeline: list[HarnessItem]  # 남긴 차례대로
    groups: list[EventGroupCount]  # EVENT_GROUP_KEYS 차례 + 끝에 unknown
    attempts: int  # 보내기 시도 수
    needs_check: int  # 「확인 필요」 통로 결과 수
    omitted: int  # 보이지 않는 앞선 사건 수(저장할 때 생략된 것 + 상한 밖)
    flow: list[OutreachFlowNode] = Field(default_factory=list)  # 다섯 마디(Task 109)
    branches_lit: list[str] = Field(default_factory=list)  # 기록으로 켜진 가지(inbound_handled)


class PointsComputeOut(BaseModel):
    points: int  # 이 버전(가정)의 포인트 수
    new: int  # 새로 들어옴 + 새 크리티컬(points_max_new 넘은 것 포함)
    tightened: int  # 여유가 줄어듦
    removed: int  # 빠짐


class PointsSearchOut(BaseModel):
    """겨냥 검색 한 갈래. per_1k = 1,000회당 값(USD). 기상청은 Liner 가 아니라 null."""

    branch: Literal["weather", "knowledge", "business"]
    label: str
    calls: int  # 보낸 호출(실패 포함). 저장된 값을 다시 쓴 것은 들지 않는다
    failed: int
    cost_kind: str
    per_1k: float | None


class PointsAgentOut(BaseModel):
    """Search Agent 근거 문장: [근거 문장 보기]를 누른 위험 줄마다 한 번(다시 찾기는 한 번으로 센다)."""

    calls: int  # 찾음 + 못 찾음
    failed: int
    pending: int  # 찾는 중
    cost_kind: str
    per_1k: float


class PointsStageOut(BaseModel):
    """실행 추적의 「관리 포인트」 단계: 계산 → 겨냥 검색 → Search Agent. 검색 수는 그 차이를 적은 때부터 위험 찾기가 끝난 때
    (찾는 중이면 지금)까지 대화 없이 남은 관리 포인트 줄을 시각으로 이은 값이다."""

    schedule_id: int
    schedule_name: str
    version: int
    what_if: bool  # 지연 분석의 가정 포인트(저장 안 한 버전)
    trigger: dict[str, Any]  # {kind: version, from, to} | {kind: delay, …}
    changed_at: datetime
    finished_at: datetime | None  # 위험 찾기가 끝난 때(찾는 중이면 null)
    compute: PointsComputeOut
    risk_status: str  # looking | done | failed | none
    searches: list[PointsSearchOut]
    skipped: int  # 건너뛴 자료(주소 없음 등 — 호출 없음)
    search_agent: PointsAgentOut
    cost: float  # 어림(USD) = Σ 호출 × per_1k / 1000 — Liner 가 알리지 않아 개수로 센다


class TurnDetail(BaseModel):
    turn: TurnOut
    structure: StructureOut
    timeline: list[TimelineItem]
    points: list[PointsStageOut] = Field(default_factory=list)  # 이 턴 동안 바뀐 관리 포인트(계획 5)


class CallCount(BaseModel):
    calls: int = 0
    failed: int = 0


class ReuseCount(BaseModel):
    calls: int = 0  # 저장된 근거를 다시 써 Liner 를 부르지 않은 수(아낀 호출)


class UsageCountersOut(BaseModel):
    """기간 안의 따로 센 호출. 비용은 기록된 것만(정보 API·근거 검색은 비용이 기록되지 않는다)."""

    info_api: CallCount  # info.call(범용 정보 API, evidence_searches mode info)
    weather: CallCount  # info.weather(기상청, mode weather)
    searches: CallCount  # Liner 근거 검색(날씨·정보 API·다시 쓰기 빼고)
    reuses: ReuseCount  # 저장된 근거 다시 쓰기(mode reuse)
    vision: UsageTotals  # 그림 읽기 모델 호출(llm_calls purpose vision)
    embedding: UsageTotals  # 임베딩 호출(llm_calls purpose embedding)
    knowledge: SearchCount  # 관리 포인트 Search + Premium Data(mode knowledge)
    mcp: SearchCount  # 관리 포인트 MCP search_business
    search_agent: SearchCount  # 근거 문장 Search Agent(llm_calls purpose srch_agent)


class TextModelUsageOut(BaseModel):
    kind: str  # text_reply | draft | translation
    count: int
    input_tokens: int
    output_tokens: int
    cost: float | None  # 모델이 알려 준 요금의 합, 없으면 None


class CallModelUsageOut(BaseModel):
    kind: str  # voice_model | transcription | summary
    count: int
    seconds: int  # 알려 준 초의 합
    input_tokens: int  # 0 이면 알려 주지 않음(음성 백엔드는 지금 토큰을 주지 않는다)
    output_tokens: int
    cost: float | None  # 알려 준 요금의 합, 없으면 None(어림하지 않는다)


class CallUsageOut(BaseModel):
    """통화 사용량(Task 110). call_seconds 는 건 통화·받은 통화의 duration_s 합, calls_placed 는 차지한(걸려고 줄에 넣은)
    거는 통화 수 — 결과를 모르는 통화도 여기 들고 실패 셈은 따로 없다. models: voice_model · transcription(기록이 있을 때만) · summary."""

    call_seconds: int
    calls_placed: int
    models: list[CallModelUsageOut]
    calls_answered: int = 0  # 받은 통화 · 받기 전 거절한 통화(Task 98 — outreach_usage.summary 그대로)
    calls_rejected: int = 0


class OutreachUsageOut(BaseModel):
    """연락 사용량(store.outreach_usage.summary 의 다섯 칸). long 은 sms 의 부분 집합. provider_cost 가 None 이면 제공사가
    요금을 알려 주지 않았다."""

    sms: int
    long: int
    kakao: int
    auto_replies: int
    provider_cost: float | None
    fallback_sms: int = 0  # 카카오톡 요청이 문자로 대신 나간 수(Task 111) — sms 에 들어 있다
    kakao_not_ready: int = 0  # 그 가운데 「카카오톡 준비 안 됨」 사건이 남은 수
    text_models: list[TextModelUsageOut] = Field(default_factory=list)  # 글 쪽 모델 사용(Task 109)
    calls: CallUsageOut | None = None  # 통화 사용량(Task 110)


class DevUsageOut(UsageOut):
    counters: UsageCountersOut | None = None
    outreach: OutreachUsageOut | None = None


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


SourceKind = Literal["weather", "materials", "fx", "business", "regulation"]
DomainKey = Annotated[str, StringConstraints(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")]


def _int_field(name: str) -> Any:
    lo, hi = POINTS_BOUNDS[name]
    return Field(default=None, ge=lo, le=hi)


class PointsDomainOut(BaseModel):
    id: str  # 분야 id. 「그 밖의 분야」는 _other
    label: str


class PointsConfigOut(BaseModel):
    """관리 포인트 설정(app.store.settings). points_sources 의 _other = 그 밖의 분야. bounds = [하한, 상한]."""

    points_tf_days: int
    points_window_weeks: int
    points_max_new: int
    points_forecast_reuse_hours: int
    accel_warn_ratio: float
    points_sources: dict[str, list[SourceKind]]
    domains: list[PointsDomainOut]  # 표의 줄 차례(건설·제조 · 저장한 다른 분야 · 그 밖의 분야)
    bounds: dict[str, tuple[float, float]]


class PointsConfigPatch(BaseModel):
    """범위 밖·모르는 갈래·모르는 칸은 422(하나라도 틀리면 아무것도 적지 않는다)."""

    model_config = ConfigDict(extra="forbid")

    points_tf_days: int | None = _int_field("tf_days")
    points_window_weeks: int | None = _int_field("window_weeks")
    points_max_new: int | None = _int_field("max_new")
    points_forecast_reuse_hours: int | None = _int_field("forecast_reuse_hours")
    accel_warn_ratio: float | None = Field(default=None, ge=_ACCEL_WARN_RATIO_BOUNDS[0], le=_ACCEL_WARN_RATIO_BOUNDS[1])
    points_sources: dict[DomainKey, list[SourceKind]] | None = Field(default=None, max_length=40)


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


class NotifyStepOut(BaseModel):
    """저장된 마지막 연결 진단의 걸음 한 줄. outcome: ok · failed · check(결과를 모름 — 실패가 아니다) · skipped."""

    id: str
    label: str
    ok: bool
    skipped: bool
    detail: str
    code: str
    maybe_sent: bool
    pending: bool
    outcome: Literal["ok", "failed", "check", "skipped"]


class NotifyDiagnosisOut(BaseModel):
    ran_at: datetime
    state: str  # done | sending
    steps: list[NotifyStepOut]


class VoiceHealthOut(BaseModel):
    """AI 전화(음성 설정 · 통화 일꾼). 키·끝 4자리·AI 전화 번호는 없다. 마지막 음성 진단은 저장된 것 그대로(다시 돌리지 않음)."""

    provider: str
    model: str | None  # 실제로 쓰는 모델(numbers.effective_model) — 없으면 SDK 기본
    status: str  # ok | failed | unknown — 마지막 음성 진단의 판정
    checked_at: datetime | None
    sdk_installed: bool
    last_diagnosis: NotifyDiagnosisOut | None
    worker: dict[str, Any] | None  # app.outreach.voice.runner.status()


class KakaoTemplateCountsOut(BaseModel):
    approved: int = 0
    reviewing: int = 0
    rejected: int = 0
    dormant: int = 0


class KakaoHealthOut(BaseModel):
    """카카오톡 채널·문안 상태(저장된 값 그대로). channel 이 null 이면 연결된 채널이 없다."""

    available: bool  # 목록 읽는 길이 확인됐는가
    channel: str | None = None
    templates: KakaoTemplateCountsOut
    synced_at: datetime | None = None
    ready: bool


class NotifyHealthOut(BaseModel):
    """기본 알림 연결(키·Account ID 없음, 발신번호는 가린 꼴). 연결이 없으면 connected false 뿐."""

    connected: bool
    status: str | None = None  # ok | failed | unknown — 마지막 연결 시험
    checked_at: datetime | None = None
    test_mode: bool | None = None
    allow_count: int = 0
    sender_masked: str | None = None
    inbound_mode: str | None = None
    agent: dict[str, str] | None = None  # sms·kakao·call → approve | delegate
    worker: dict[str, Any] | None = None  # app.outreach.worker.status()
    needs_check: int = 0  # 보냈는지 확인 필요(unconfirmed) 메시지 수
    last_diagnosis: NotifyDiagnosisOut | None = None  # 저장된 것 그대로(다시 돌리지 않음)
    kakao: KakaoHealthOut | None = None  # Task 111 — 저장된 채널·문안 상태(제공사를 부르지 않음), 연결이 없으면 null
    voice: VoiceHealthOut | None = None  # Task 110 — 음성 설정이 없으면 null


class PresenceHealthOut(BaseModel):
    """지금 접속 중(2분 안에 접속 신호)인 사람·기기 수. 누구인지는 담지 않는다(설정 → 계정이 보인다)."""

    online_users: int
    online_devices: int


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
    notify: NotifyHealthOut | None = None  # Task 108
    presence: PresenceHealthOut | None = None  # 계정별 접속 상태(설정 → 계정)


class StopTurnOut(BaseModel):
    chat_session_id: int
    stopped: bool


class ToolToggleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class ToolToggleOut(BaseModel):
    name: str
    enabled: bool


class UpdateItemOut(BaseModel):
    """업데이트 내역 한 줄. note = 작게 붙는 덧말(없으면 null)."""

    text: str
    note: str | None = None


class UpdateEntryOut(BaseModel):
    """실서버에 올린 판 하나(deploy/updates.jsonl 한 줄)."""

    at: datetime  # 시간대가 붙은 때(+09:00)
    commit: str  # 짧은 커밋
    title: str
    notice: str | None = None  # 모두에게 알릴 한 줄(예: 다시 로그인)
    added: list[UpdateItemOut] = Field(default_factory=list)  # 새 기능
    fixed: list[UpdateItemOut] = Field(default_factory=list)  # 고침
    safety: list[UpdateItemOut] = Field(default_factory=list)  # 안전


class UpdatesOut(BaseModel):
    entries: list[UpdateEntryOut]  # 새것이 위, 많아야 MAX_ENTRIES
    running_commit: str | None  # 서버가 켤 때 읽은 자기 git HEAD(짧은 꼴), 못 읽으면 null
