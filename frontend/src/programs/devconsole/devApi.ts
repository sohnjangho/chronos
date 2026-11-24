// 개발 콘솔 API(Task 29, backend/app/programs/devconsole/schemas.py). 관리자만 — 아니면 403 admin_only.
import { api } from '../../shared/api';

export type TurnStatus = 'running' | 'done' | 'failed' | 'stopped';

export interface Turn {
  turn_id: number;
  chat_session_id: number;
  user_name: string;
  /** 모델이 읽은 사용자 글 앞 60자. */
  request: string;
  started_at: string;
  status: TurnStatus;
  /** 루프의 모델 호출 + 도구 안 호출. */
  llm_calls: number;
  tool_calls: number;
  tokens: number;
  cost: number | null;
  /** 턴 전체 시간. 끝나지 않았으면 null. */
  ms: number | null;
}

export type NodeKey = 'request' | 'context' | 'skill' | 'plan' | 'judge' | 'tool' | 'check' | 'approval' | 'respond';
export type NodeState = 'past' | 'now' | 'todo' | 'skipped';

/** in/out 모양은 칸마다 다르다(글·JSON 글·객체·목록). */
export interface NodeDetail {
  in: unknown;
  out: unknown;
  ms: number | null;
  /** 모델 칸(plan·judge)이 쓴 모델. 코드 칸은 null. */
  model: string | null;
  settings: string | null;
}

export interface StructureNode {
  key: NodeKey;
  label: string;
  state: NodeState;
  count: number;
  detail: NodeDetail;
}

export interface HarnessSummary {
  tools: string[];
  rounds: number;
  passed: number;
  violations: number;
  uncheckable: number;
}

export interface Structure {
  nodes: StructureNode[];
  /** llm 사건 수. */
  loop_count: number;
  limit: number;
  /** 실제 실행된 분기: check_repair·approval_inbox·approval_auto·vision_turn·files_used·weather_used, 11-23 신호(signals.ts). */
  edges_lit?: string[];
  /** 하네스 점검 요약. */
  harness_summary?: HarnessSummary | null;
}

/** context 칸 in 의 재료 하나. tokens 는 첫 호출 입력 토큰을 글자 비중으로 나눈 어림(없으면 null). */
export interface ContextPart {
  name: string;
  chars: number;
  tokens: number | null;
  share: number;
}

/** 연락 하네스 사건 한 줄의 표지(Task 108). 이름·묶음은 서버가 harness.types 상수에서 읽는다. 자유 글은 없다. */
export interface HarnessMark {
  /** EVENT_GROUPS 의 묶음. 모르는 사건은 null. */
  group: string | null;
  group_label: string;
  /** 사건 이름(코드). 모르는 사건은 null. */
  rule: string | null;
  verdict: 'blocked' | 'allowed' | 'noted' | null;
  verdict_label: string;
  /** 보내기 시도 차례(1부터) — 판정 메모·문 판정·통로 결과만. */
  attempt: number | null;
  /** 나가는 문의 차례. */
  order: number | null;
  /** 정해 둔 detail 코드 또는 도구 이름. */
  code: string | null;
  /** 통로 결과 unsure — 「확인 필요」(실패 아님). */
  needs_check: boolean;
  unknown: boolean;
}

export interface TraceItem {
  seq: number;
  kind: 'context' | 'llm' | 'tool' | 'inner_llm' | 'harness';
  label: string;
  /** tool 은 그 도구를 부른 답이 끝난 때부터 앞 단계 시간을 더한 어림. */
  started_at: string;
  ms: number | null;
  model: string | null;
  input_tokens: number;
  output_tokens: number;
  cost: number | null;
  ok: boolean;
  error: string | null;
  input_text: string;
  output_text: string;
  /** tool: 그 도구를 부른 답(같은 값 = 한 답이 함께 부름). 짝을 읽지 못한 단계와 그 밖의 줄은 null. */
  parallel_group: number | null;
  /** tool: 그 단계 기록이 보여 주는 신호(signals.ts). 예전 서버는 보내지 않는다. */
  signals?: string[];
  /** harness: 연락 하네스 사건의 표지. */
  harness?: HarnessMark;
}

export type OutreachKind = 'message' | 'call';

/** 연락 기록 한 줄(번호는 가린 꼴만, 글·받아쓰기 없음). */
export interface OutreachRow {
  kind: OutreachKind;
  id: number;
  at: string;
  direction: 'out' | 'in' | string;
  channel: 'sms' | 'kakao' | 'call' | string;
  origin: 'user' | 'agent' | 'peer' | string;
  origin_name: string;
  send_mode: 'manual' | 'approved' | 'delegated' | null;
  caller_class: string | null;
  status: string;
  /** 주소록 이름. 없으면 「모르는 번호」. */
  contact_name: string | null;
  company_name: string | null;
  number_masked: string;
  schedule_name: string | null;
  events: number;
  needs_check: boolean;
}

export interface OutreachList {
  items: OutreachRow[];
  /** 상한 밖에 더 있다. */
  more: boolean;
  limit: number;
}

export interface OutreachHead extends OutreachRow {
  approved_by: string | null;
  fail_reason: string | null;
  reply_to_id: number | null;
  /** 통화만(Task 110): 통화 시간(초) · 받아쓰기 줄 수(글은 오지 않는다). 문자는 null. */
  duration_s?: number | null;
  transcript_lines?: number | null;
}

/** 연락 흐름도 마디 하나(Task 109): inbound · tool · post_check · gate · channel. 판정 글은 서버의 것. */
export interface OutreachFlowNode {
  key: string;
  label: string;
  count: number;
  verdicts: { verdict: string | null; label: string; count: number }[];
}

export interface OutreachDetail {
  head: OutreachHead;
  timeline: TraceItem[];
  /** 묶음별 사건 수(EVENT_GROUP_KEYS 차례 + unknown). */
  groups: { key: string; label: string; count: number }[];
  attempts: number;
  needs_check: number;
  /** 보이지 않는 앞선 사건 수. */
  omitted: number;
  /** 다섯 마디 흐름도(Task 109). 예전 서버는 없다. */
  flow?: OutreachFlowNode[];
  /** 기록으로 켜진 가지(inbound_handled). 예전 서버는 없다. */
  branches_lit?: string[];
}

export interface TurnDetail {
  turn: Turn;
  structure: Structure;
  timeline: TraceItem[];
}

export type UsageGroup = 'model' | 'user' | 'day' | 'purpose';

export interface UsageTotals {
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cost: number | null;
  failed: number;
}

export interface UsageRow extends UsageTotals {
  key: string;
}

export interface UsageOut {
  rows: UsageRow[];
  totals: UsageTotals;
  cost_known: boolean;
  searches: { calls: number; failed: number };
  /** 11-23: 따로 센 호출. 예전 서버는 보내지 않는다. */
  counters?: UsageCounters | null;
  /** Task 108: 연락 사용량. long 은 sms 의 부분 집합, provider_cost null = 제공사가 알려 주지 않음. */
  outreach?: OutreachUsage | null;
}

export interface OutreachUsage {
  sms: number;
  long: number;
  kakao: number;
  auto_replies: number;
  provider_cost: number | null;
  /** 글 쪽 모델 사용(text_reply · draft · translation). cost 는 모델이 알려 준 것만. 예전 서버는 없다. */
  text_models?: { kind: string; count: number; input_tokens: number; output_tokens: number; cost: number | null }[];
  /** 통화 사용량(Task 110). models: voice_model · transcription(기록이 있을 때만) · summary — 알려 준 값만. */
  calls?: CallUsage | null;
}

export interface UsageCounters {
  info_api: { calls: number; failed: number };
  weather: { calls: number; failed: number };
  searches: { calls: number; failed: number };
  /** 저장된 근거를 다시 써 Liner 를 부르지 않은 수. */
  reuses: { calls: number };
  vision: UsageTotals;
  embedding: UsageTotals;
}

export interface HarnessRule {
  id: string;
  /** 묶음(일정 계산·에이전트 루프·바깥 정보·권한·가져오기·생성·현장). 예전 서버는 없다 — area 로 묶는다. */
  group?: string;
  area: string;
  title: string;
  description: string;
  code: string;
  mode: string;
  feedback_sample: string;
  /** 세션 기록 수. 기록에 남는 값이 없는 규칙은 null(지어내지 않는다). */
  passed_count: number | null;
  blocked_count: number | null;
}

export interface HarnessTestOut {
  rule_id: string;
  title: string;
  blocked: boolean;
  engine?: string;
  elapsed_ms?: number;
  simulated_input: string;
  model_feedback: Record<string, unknown>;
  /** 연락 하네스 격자 칸(Task 98 — 모래상자 자식 프로세스): 대본의 기대가 모두 참인가 · 기대마다 · 하네스 사건 · 칸 말. */
  passed?: boolean;
  checks?: { text: string; ok: boolean; guarded?: boolean }[];
  events?: { ref: string; rule: string; verdict: string; detail: string | null; group: string | null; group_label: string }[];
  note?: string | null;
  /** 가드 끄고 돌리기: 무른 지키는 곳 · 무르니 실패했는가(= 가드 확인됨). 그냥 돌리기는 null. */
  broken_guard?: string | null;
  guard_confirmed?: boolean | null;
  /** 가드 판정의 까닭(서버 글) · 같은 자식의 그냥 돌리기가 통과했는가(그냥 돌려도 실패면 guard_confirmed null). */
  guard_reason?: string | null;
  baseline_passed?: boolean | null;
}

/** 칸 말의 종류 — 운영 동작이 아님을 가려 보인다(가짜에서만 · 하네스 갈라짐 · 공통 겹만 · 설계와 다름). */
export type GridNoteKind = 'simulated' | 'diverged' | 'common_only' | 'design_diff';
export interface GridCell {
  /** run = ● · none = — · 그 밖은 설계 표의 글(막음·받지 않음·기록만·예약 …). */
  mark: string;
  runnable: boolean;
  /** 그 칸을 지키는 곳(무르기 이름) — 없으면 null(가드 끄고 돌리기 없음). */
  guard: string | null;
  note: string | null;
  note_kind: GridNoteKind | null;
}
export interface GridRow {
  id: string;
  title: string;
  refs: string[];
  cells: Record<string, GridCell>;
}
export interface GridCase extends GridCell {
  id: string;
  case: string;
  title: string;
  medium: 'call' | 'sms' | 'kakao';
  refs: string[];
  column: string;
}
/** 카탈로그의 「연락 하네스」 묶음(Task 98). connection_id = 기본 알림 연결(운영 상한은 공용 LimitsForm 이 읽고 고친다). */
export interface OutreachGridOut {
  group: string;
  principles: string[];
  limits_note: string;
  connection_id: number | null;
  columns: { key: string; label: string }[];
  rows: GridRow[];
  channel_only: GridCase[];
  error: string | null;
}

export interface GuideSource {
  name: string;
  file: string;
  chars: number;
  keywords: string[];
  programs: string[];
  content: string;
}

export interface PipelinePromptSource {
  name: string;
  file: string;
  chars: number;
  content: string;
}

export interface DomainSource {
  id: string;
  name: string;
  file: string;
  knowledge: string;
}

export interface ToolRegistryItem {
  name: string;
  llm_name: string;
  program: string | null;
  category: string;
  enabled?: boolean;
  calls?: number;
  failed?: number;
  avg_ms?: number | null;
  description: string;
  schema: Record<string, unknown>;
  /** 자료를 바꾸는 도구인가(등록할 때 정한 값). 예전 서버는 없다. */
  mutates?: boolean;
  /** 부를 수 있는 역할(admin·user·field) — 서버가 막는 바로 그 줄(ctx.require_editor)로 정한다. 예전 서버는 없다. */
  roles?: string[];
  /** 현장 관리자는 어떤 인자에서만 거절(도구 코드의 조건 안 require_editor). 예전 서버는 없다. */
  field_limited?: boolean;
  /** false = 끄기 길이 없음(연락 하네스 도구 — 등록부 밖). */
  toggle?: boolean;
  /** 역할 칸의 설명(연락 도구, Task 109). */
  role_note?: string | null;
  /** 연락 하네스 도구를 받는 발신자 등급(toolsets.for_class). */
  classes?: string[];
  /** 연락 하네스 도구의 매체(sms · call). */
  media?: string[];
}

export interface SkillRegistryItem {
  id: number;
  name: string;
  description: string;
  triggers: string[];
  steps: { tool: string; why?: string }[];
  use_count: number;
}

export type ApprovalMode = 'all' | 'important' | 'auto';

export interface AgentConfig {
  approval_mode: ApprovalMode;
  max_steps: number;
  max_check_retries: number;
  tool_output_limit: number;
  history_limit: number;
  enable_skill_match: boolean;
  enable_self_reflection: boolean;
}

export interface CatalogOut {
  principles: string[];
  harness: HarnessRule[];
  agent_config?: AgentConfig;
  sources: {
    system_file: string;
    system_raw: string;
    system_chars: number;
    levels_prompt: string;
    guides: GuideSource[];
    pipeline_prompts?: PipelinePromptSource[];
    domains: DomainSource[];
  };
  registry: {
    tools: ToolRegistryItem[];
    skills: SkillRegistryItem[];
  };
  /** 연락 하네스 묶음(Task 98). 예전 서버는 없다. */
  outreach_grid?: OutreachGridOut;
}

export interface HealthOut {
  llm: {
    status: 'ok' | 'warn' | 'error';
    connections_count: number;
    assignments_count: number;
    default_name: string | null;
    default_provider: string | null;
    default_base_url: string | null;
    key_ready: boolean;
    message: string;
  };
  qdrant: {
    status: 'ok' | 'off' | 'error';
    collections: string[];
    points_count: number;
    latency_ms: number | null;
    message: string;
  };
  search: {
    status: 'ok' | 'warn';
    ready: boolean;
    calls_7d: number;
    failed_7d: number;
    message: string;
  };
  db: {
    status: 'ok';
    size_bytes: number;
    counts: Record<string, number>;
  };
  active_turns: {
    chat_session_id: number;
    title: string;
    stop_requested: boolean;
  }[];
  /** 11-23 칸 — 예전 서버는 보내지 않는다. */
  info_api?: InfoApiHealth | null;
  evidence_reuse?: ReuseHealth | null;
  holidays?: HolidayHealth | null;
  vision?: VisionHealth | null;
  /** Task 108: 기본 알림 연결. */
  notify?: NotifyHealth | null;
}

/** 저장된 마지막 연결 진단의 걸음. outcome check = 결과를 모름(실패 아님). */
export interface CallModelUsage {
  kind: string;
  count: number;
  seconds: number;
  input_tokens: number;
  output_tokens: number;
  cost: number | null;
}

export interface CallUsage {
  call_seconds: number;
  calls_placed: number;
  models: CallModelUsage[];
  /** 받은 통화 · 받기 전 거절한 통화(Task 98). 예전 서버는 없다. */
  calls_answered?: number;
  calls_rejected?: number;
}

/** 시스템 진단의 AI 전화(Task 110). 키·끝 4자리·번호는 없다. worker = 통화 일꾼 runner.status(). */
export interface VoiceHealth {
  provider: string;
  model: string | null;
  status: string;
  checked_at: string | null;
  sdk_installed: boolean;
  last_diagnosis: NotifyDiagnosis | null;
  worker: Record<string, unknown> | null;
}

export interface NotifyDiagnosis {
  ran_at: string;
  state: string;
  steps: NotifyStep[];
}

export interface NotifyStep {
  id: string;
  label: string;
  ok: boolean;
  skipped: boolean;
  detail: string;
  code: string;
  maybe_sent: boolean;
  pending: boolean;
  outcome: 'ok' | 'failed' | 'check' | 'skipped';
}

/** 기본 알림 연결(키·Account ID 없음, 발신번호는 가린 꼴). 연결이 없으면 connected false 뿐. */
export interface NotifyHealth {
  connected: boolean;
  status: string | null;
  checked_at: string | null;
  test_mode: boolean | null;
  allow_count: number;
  sender_masked: string | null;
  inbound_mode: string | null;
  agent: Record<string, string> | null;
  /** 연락 일꾼 메모리 상태(시각은 ISO). */
  worker: Record<string, unknown> | null;
  needs_check: number;
  last_diagnosis: NotifyDiagnosis | null;
  kakao: null;
  voice?: VoiceHealth | null;
}

/** 정보 API 연결(주소·키 없음). */
export interface InfoApiHealth {
  status: 'ok' | 'warn' | 'off';
  count: number;
  connections: { id: number; name: string; kind: string; status: string; checked_at: string | null }[];
  message: string;
}

export interface ReuseHealth {
  reusable: number;
  reused_7d: number;
  searches_7d: number;
  days: number;
}

export interface HolidayHealth {
  status: 'ok' | 'warn';
  years: number[];
  counts: Record<string, number>;
  message: string;
}

export interface VisionHealth {
  status: 'ok' | 'warn' | 'error';
  model: string;
  connection_name: string | null;
  stored: boolean;
  key_ready: boolean;
  message: string;
}

export const RECENT = 30;

export const devApi = {
  turns: () => api<Turn[]>(`/api/devconsole/turns?limit=${RECENT}`),
  turn: (id: number) => api<TurnDetail>(`/api/devconsole/turns/${id}`),
  outreachList: () => api<OutreachList>(`/api/devconsole/outreach?limit=${RECENT}`),
  outreach: (kind: OutreachKind, id: number) => api<OutreachDetail>(`/api/devconsole/outreach/${kind}/${id}`),
  usage: (days: number, group: UsageGroup) => api<UsageOut>(`/api/devconsole/usage?days=${days}&group=${group}`),
  catalog: () => api<CatalogOut>('/api/devconsole/catalog'),
  /** broken: 연락 하네스 칸을 지키는 곳을 그 자식 프로세스 안에서만 끄고 돌린다(서버는 문·도구를 건드리지 않는다). */
  testHarness: (ruleId: string, broken = false) =>
    api<HarnessTestOut>(`/api/devconsole/harness/${ruleId}/test${broken ? '?broken=1' : ''}`, { method: 'POST' }),
  getAgentConfig: () => api<AgentConfig>('/api/devconsole/agent-config'),
  saveAgentConfig: (cfg: AgentConfig) =>
    api<AgentConfig>('/api/devconsole/agent-config', { method: 'PUT', body: JSON.stringify(cfg) }),
  health: () => api<HealthOut>('/api/devconsole/health'),
  stopTurn: (chatId: number) =>
    api<{ chat_session_id: number; stopped: boolean }>(`/api/devconsole/turns/${chatId}/stop`, { method: 'POST' }),
  setToolEnabled: (name: string, enabled: boolean) =>
    api<{ name: string; enabled: boolean }>(`/api/devconsole/tools/${encodeURIComponent(name)}`, {
      method: 'PUT',
      body: JSON.stringify({ enabled }),
    }),
  deleteSkill: (skillId: number) => api<void>(`/api/workflows/skills/${skillId}`, { method: 'DELETE' }),
};
