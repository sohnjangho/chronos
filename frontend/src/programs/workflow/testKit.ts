// 워크플로우 시험 전용 도우미. 화면 코드는 이 파일을 import하지 않는다. 사람·현장은 모두 가상이다.
import { json, signInAsDemo, stubFetch } from '../../test-helpers';
import type { RunDetail, RunItem, Step } from './wfApi';

export function step(n: number, over: Partial<Step> = {}): Step {
  return {
    n,
    tool: 'schedule.read',
    program: 'schedule',
    why: `${n}단계: 지금 일정을 읽어 지연을 확인하겠습니다.`,
    status: 'done',
    input_json: JSON.stringify({ schedule_id: 1 }),
    output_json: JSON.stringify({ name: '5층 사무동 신축', activity_count: 62, critical: ['A1010', 'A2020'] }),
    ms: 200,
    model: 'liner-fast',
    tokens: 1200,
    cost: null,
    ...over,
  };
}

export function run(over: Partial<RunDetail> = {}): RunDetail {
  return {
    id: 12,
    chat_session_id: 7,
    title: '골조 지연 만회 계획',
    status: 'running',
    started_at: new Date(Date.now() - 60_000).toISOString(),
    ended_at: null,
    tokens: 21400,
    cost: null,
    step_count: 4,
    request: '골조가 4일 밀렸어. 만회 계획 세워 줘',
    steps: [
      step(1),
      step(2, { tool: 'harness.check', program: 'conditions', why: '두 안을 같이 점검합니다.', ms: 1100 }),
      step(3, { tool: 'calc.cpm', program: null, why: '두 안을 같이 점검합니다.', ms: 2100 }),
      step(4, { tool: 'out.submit_change', program: 'approvals', status: 'running', output_json: null, ms: null }),
    ],
    ...over,
  };
}

export const item = (r: RunDetail): RunItem => {
  const { request: _r, steps: _s, ...rest } = r;
  void _r;
  void _s;
  return rest;
};

export const DONE = run({ id: 11, title: '5층 사무동 공정표 생성', status: 'done', ended_at: new Date(Date.now() - 3_600_000 + 41_000).toISOString(), started_at: new Date(Date.now() - 3_600_000).toISOString(), step_count: 2, cost: 0.12, steps: [step(1), step(2, { tool: 'generate.run', program: null })] });

type Routes = Parameters<typeof stubFetch>[0];
export let fetchMock: ReturnType<typeof stubFetch>;

/** 가짜 실행 기록 서버(id → 상세). extra 로 경로를 바꿔 끼운다. */
export function setup(details: Record<number, RunDetail> = { 12: run(), 11: DONE }, extra: Routes = {}, role: 'admin' | 'user' = 'admin') {
  signInAsDemo(role);
  const routes: Routes = {
    '/api/workflows/runs': () => json(200, Object.values(details).map(item).sort((a, b) => b.id - a.id)),
  };
  for (const [id, d] of Object.entries(details)) routes[`/api/workflows/runs/${id}`] = () => json(200, d);
  fetchMock = stubFetch({ ...routes, ...extra });
}

export const callsTo = (url: string) => fetchMock.mock.calls.filter(([u]) => String(u) === url);
