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

export interface TraceItem {
  seq: number;
  kind: 'context' | 'llm' | 'tool' | 'inner_llm';
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
}

export const RECENT = 30;

export const devApi = {
  turns: () => api<Turn[]>(`/api/devconsole/turns?limit=${RECENT}`),
  turn: (id: number) => api<TurnDetail>(`/api/devconsole/turns/${id}`),
  usage: (days: number, group: UsageGroup) => api<UsageOut>(`/api/devconsole/usage?days=${days}&group=${group}`),
  catalog: () => api<CatalogOut>('/api/devconsole/catalog'),
  testHarness: (ruleId: string) => api<HarnessTestOut>(`/api/devconsole/harness/${ruleId}/test`, { method: 'POST' }),
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
