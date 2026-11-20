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

export interface Structure {
  nodes: StructureNode[];
  /** llm 사건 수. */
  loop_count: number;
  limit: number;
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

export const RECENT = 30;

export const devApi = {
  turns: () => api<Turn[]>(`/api/devconsole/turns?limit=${RECENT}`),
  turn: (id: number) => api<TurnDetail>(`/api/devconsole/turns/${id}`),
  usage: (days: number, group: UsageGroup) => api<UsageOut>(`/api/devconsole/usage?days=${days}&group=${group}`),
};
