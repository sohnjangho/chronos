// 워크플로우 실행 기록 API(Task 10). 일반 사용자는 자기 대화의 실행만, 관리자는 모두 받는다.
import { api } from '../../shared/api';

export type StepStatus = 'running' | 'done' | 'failed' | 'stopped' | 'pending';

export interface Step {
  n: number;
  tool: string;
  program: string | null;
  /** 이 호출을 낸 에이전트 글(200자). */
  why: string;
  status: StepStatus | string;
  /** JSON 글. 관리자가 아니면 앞 2,000자에서 잘려 온다. */
  input_json: string;
  output_json: string | null;
  ms: number | null;
  /** 이 호출을 낸 LLM 답의 모델·토큰·비용(한 답이 둘을 부르면 두 단계가 같은 값). */
  model: string | null;
  tokens: number;
  cost: number | null;
}

export interface RunItem {
  id: number;
  chat_session_id: number;
  title: string;
  status: 'running' | 'done' | 'failed' | 'stopped' | string;
  started_at: string;
  ended_at: string | null;
  tokens: number;
  cost: number | null;
  step_count: number;
}

export interface RunDetail extends RunItem {
  request: string;
  steps: Step[];
}

export interface SkillItem {
  id: number;
  name: string;
  description: string;
  triggers: string[];
  steps: { tool: string; why?: string }[];
  source_run_id: number | null;
  use_count: number;
  created_at: string;
}

export const wfApi = {
  runs: () => api<RunItem[]>('/api/workflows/runs'),
  run: (id: number) => api<RunDetail>(`/api/workflows/runs/${id}`),
  skills: () => api<SkillItem[]>('/api/workflows/skills'),
  saveSkill: (runId: number, name: string, triggers: string[] = []) =>
    api<SkillItem>(`/api/workflows/runs/${runId}/save-skill`, {
      method: 'POST',
      body: JSON.stringify({ name, triggers }),
    }),
  deleteSkill: (skillId: number) => api<void>(`/api/workflows/skills/${skillId}`, { method: 'DELETE' }),
};

/** 서버가 잘라 보내는 길이(관리자가 아닐 때). */
export const CUT_AT = 2000;
