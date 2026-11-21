// 개발 콘솔 시험 전용 도우미. 화면 코드는 이 파일을 import 하지 않는다. 사람·현장·모델 이름은 모두 가상이다.
import { vi } from 'vitest';
import { json, signInAsDemo } from '../../test-helpers';
import type { NodeKey, NodeState, StructureNode, TraceItem, Turn, TurnDetail, UsageOut } from './devApi';

const MODEL = 'claude-sonnet-5.5';
const at = (base: number, ms: number) => new Date(base + ms).toISOString();

export function turn(over: Partial<Turn> = {}): Turn {
  return {
    turn_id: 41,
    chat_session_id: 7,
    user_name: '김하늘',
    request: '골조가 4일 밀렸어. 만회 계획 세워 줘',
    started_at: new Date(Date.now() - 12_800).toISOString(),
    status: 'running',
    llm_calls: 4,
    tool_calls: 5,
    tokens: 21_400,
    cost: null,
    ms: null,
    ...over,
  };
}

const LABELS: Record<NodeKey, string> = {
  request: '요청 받기', context: '컨텍스트 조립', skill: '스킬 찾기', plan: '워크플로우 짜기', judge: '판단 (모델)',
  tool: '도구 실행', check: '조건 점검', approval: '승인 판단', respond: '응답·기록',
};
const FLOW: NodeKey[] = ['request', 'context', 'plan', 'judge', 'tool', 'check', 'approval', 'respond'];

const PARTS = [
  ['지시문', 2200], ['분야 지식', 1800], ['정밀도', 400], ['지금 상황', 3000], ['날짜 도우미', 200], ['대화', 1500], ['도구 목록', 900],
] as const;
const CHAR_SUM = PARTS.reduce((s, [, c]) => s + c, 0);
export const contextIn = (firstInput = 9800) => ({
  parts: PARTS.map(([name, chars]) => ({ name, chars, tokens: Math.round((firstInput * chars) / CHAR_SUM), share: Math.round((1000 * chars) / CHAR_SUM) / 10 })),
  history_count: 4,
  tool_count: 21,
});

const messages = JSON.stringify([
  { role: 'system', content: '너는 5층 사무동 신축 현장의 공정 관리 에이전트다.' },
  { role: 'user', content: '골조가 4일 밀렸어. 만회 계획 세워 줘' },
]);
const reply = (...names: string[]) =>
  JSON.stringify({ text: '', tool_calls: names.map((name, i) => ({ id: `c${i}`, name, arguments: JSON.stringify({ schedule_id: 1 }) })) });

function details(key: NodeKey, loop: number): StructureNode['detail'] {
  const none = { in: null, out: null, ms: null, model: null, settings: null };
  const steps = (tools: string[]) => ({
    ...none,
    in: tools.map((tool, i) => ({ n: i + 1, tool, input: JSON.stringify({ schedule_id: 1, activity: 'A2020' }) })),
    out: tools.map((_, i) => ({ n: i + 1, status: 'done', output: JSON.stringify({ ok: true, critical: ['A1010', 'A2020'] }) })),
    ms: 760,
  });
  switch (key) {
    case 'request': return { ...none, in: '골조가 4일 밀렸어. 만회 계획 세워 줘' };
    case 'context': return { ...none, in: contextIn(), ms: 340 };
    case 'skill': return { ...none, in: '스킬은 묶음 3에서 — 지금은 늘 없음' };
    case 'plan': return { ...none, in: messages, out: reply('schedule.read', 'delay.impact'), ms: 2100, model: MODEL };
    case 'judge': return { ...none, in: messages, out: reply('harness.check'), ms: 1800 * (loop - 1), model: MODEL };
    case 'tool': return steps(['schedule.read', 'delay.impact', 'shorten.make']);
    case 'check': return { ...steps(['harness.check']), settings: '점검 한도 5회' };
    case 'approval': return { ...none, in: [], out: [], settings: '승인 수준: 모두 승인' };
    case 'respond': return { ...none, out: '만회안 두 가지를 비교판에 올렸습니다.', ms: 41_200 };
  }
}

function nodes(states: Partial<Record<NodeKey, NodeState>>, loop: number): StructureNode[] {
  return (Object.keys(LABELS) as NodeKey[]).map((key) => {
    const state = key === 'skill' ? 'skipped' : (states[key] ?? 'todo');
    const count = state === 'past' || state === 'now' ? (key === 'judge' ? loop - 1 : key === 'tool' ? 3 : 1) : 0;
    return { key, label: LABELS[key], state, count, detail: details(key, loop) };
  });
}

/** 시간표: 답 하나가 도구 둘을 함께 부름(같은 parallel_group) → 도구 → 도구 안 호출 → 점검 → 다음 답 … 의 루프. */
export function timeline(base: number, opts: { running?: boolean; unpaired?: boolean } = {}): TraceItem[] {
  const row = (seq: number, kind: TraceItem['kind'], label: string, start: number, ms: number | null, over: Partial<TraceItem> = {}): TraceItem => ({
    seq, kind, label, started_at: at(base, start), ms, model: null, input_tokens: 0, output_tokens: 0, cost: null, ok: true,
    error: null, input_text: '', output_text: '', parallel_group: null, ...over,
  });
  const llm = (seq: number, start: number, ms: number | null, out: string, tokens: [number, number]) =>
    row(seq, 'llm', '모델 호출 (normal)', start, ms, { model: MODEL, input_tokens: tokens[0], output_tokens: tokens[1], input_text: messages, output_text: out });
  const tool = (seq: number, name: string, start: number, ms: number, group: number | null) =>
    row(seq, 'tool', name, start, ms, { input_text: JSON.stringify({ schedule_id: 1 }), output_text: JSON.stringify({ ok: true }), parallel_group: group });
  const items = [
    row(1, 'context', '컨텍스트 조립', 0, 340, { input_text: JSON.stringify(contextIn()) }),
    llm(2, 400, 2100, reply('schedule.read', 'delay.impact'), [9800, 220]),
    tool(3, 'schedule.read', 2500, 120, 2),
    tool(4, 'delay.impact', 2620, 640, 2),
    llm(5, 3300, 1800, reply('shorten.make'), [10_900, 180]),
    tool(6, 'shorten.make', 5100, 3100, 3),
    row(7, 'inner_llm', '도구 안 모델 호출 (hard)', 5300, 2400, { model: 'liner-hard-7', input_tokens: 3100, output_tokens: 900 }),
    opts.unpaired ? llm(8, 8300, 1500, `${reply('harness.check').slice(0, 30)}`, [12_100, 160]) : llm(8, 8300, 1500, reply('harness.check'), [12_100, 160]),
    tool(9, 'harness.check', 9800, 600, opts.unpaired ? null : 4),
  ];
  if (opts.running) items.push(llm(10, 10_500, null, '', [0, 0]));
  return items;
}

export function running({ now = 'tool', loop = 4 }: { now?: NodeKey; loop?: number } = {}): TurnDetail {
  const i = FLOW.indexOf(now);
  const states = Object.fromEntries(FLOW.map((k, j) => [k, j < i ? 'past' : j === i ? 'now' : 'todo']));
  const t = turn();
  return { turn: t, structure: { nodes: nodes(states, loop), loop_count: loop, limit: 12 }, timeline: timeline(Date.parse(t.started_at), { running: true }) };
}

export function done(over: Partial<Turn> = {}, opts: { unpaired?: boolean } = {}): TurnDetail {
  const t = turn({ status: 'done', ms: 41_200, cost: 0.12, ...over });
  const states = Object.fromEntries(FLOW.map((k) => [k, k === 'approval' ? 'todo' : 'past']));
  return { turn: t, structure: { nodes: nodes(states, 4), loop_count: 4, limit: 12 }, timeline: timeline(Date.parse(t.started_at), opts) };
}

export const usage = (over: Partial<UsageOut> = {}): UsageOut => ({
  rows: [
    { key: MODEL, calls: 12, input_tokens: 118_000, output_tokens: 2400, cost: null, failed: 1 },
    { key: 'liner-hard-7', calls: 3, input_tokens: 9300, output_tokens: 2700, cost: null, failed: 0 },
  ],
  totals: { calls: 15, input_tokens: 127_300, output_tokens: 5100, cost: null, failed: 1 },
  cost_known: false,
  searches: { calls: 6, failed: 1 },
  ...over,
});

const OLDER = turn({ turn_id: 38, request: '5층 사무동 공정표 만들어 줘', status: 'done', ms: 64_000, tokens: 48_200, started_at: new Date(Date.now() - 86_400_000).toISOString() });

let list: Turn[] = [];
/** 상세 응답 차례. 숫자는 그 상태 코드의 오류 응답. */
let queue: (TurnDetail | number)[] = [];
let usageBody: UsageOut = usage();
const byId = new Map<number, TurnDetail>();
export let fetchMock: ReturnType<typeof vi.fn>;

/** 가짜 개발 콘솔 서버. 상세는 queue 를 차례로(마지막 하나는 계속), 다른 턴은 byId 로. */
export function setup(role: 'admin' | 'user' = 'admin') {
  signInAsDemo(role);
  queue = [running()];
  list = [turn(), OLDER];
  byId.clear();
  byId.set(38, done({ turn_id: 38, request: OLDER.request, started_at: OLDER.started_at }, { unpaired: true }));
  usageBody = usage();
  const sampleCatalog = {
    principles: ['원칙 1'],
    harness: [
      {
        id: 'H-LIM-01',
        area: '루프',
        title: 'ReAct 루프 단계 한도(12바퀴) 및 하네스 재시도 한도(5회) 강제',
        description: '한도 강제',
        code: 'app/agent/loop.py',
        mode: '코드 강제',
        feedback_sample: '{}',
        passed_count: 3,
        blocked_count: 0,
      },
    ],
    agent_config: {
      approval_mode: 'important',
      max_steps: 12,
      max_check_retries: 5,
      tool_output_limit: 4000,
      history_limit: 30,
      enable_skill_match: true,
      enable_self_reflection: true,
    },
    sources: { system_file: 'system.md', system_raw: 'prompt', system_chars: 6, levels_prompt: 'L3', guides: [], domains: [] },
    registry: { tools: [], skills: [] },
  };
  fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === '/api/devconsole/turns?limit=30') return json(200, list);
    const m = /^\/api\/devconsole\/turns\/(\d+)$/.exec(url);
    if (m && Number(m[1]) === 41) return detailResponse(queue.length > 1 ? queue.shift()! : queue[0]);
    if (m && byId.has(Number(m[1]))) return json(200, byId.get(Number(m[1])));
    if (url.startsWith('/api/devconsole/usage?')) return json(200, usageBody);
    if (url === '/api/devconsole/catalog') return json(200, sampleCatalog);
    if (url === '/api/devconsole/agent-config' && init?.method === 'PUT') return json(200, JSON.parse(String(init.body)));
    if (url === '/api/devconsole/agent-config') return json(200, sampleCatalog.agent_config);
    return json(404, { code: 'not_found', message: '찾을 수 없습니다.', detail: null });
  });
  vi.stubGlobal('fetch', fetchMock);
}

const ERRORS: Record<number, string> = { 403: '관리자만 쓸 수 있습니다.', 404: '실행 추적을 찾을 수 없습니다.', 500: '서버 오류가 났습니다.' };
function detailResponse(d: TurnDetail | number) {
  return typeof d === 'number' ? json(d, { code: 'error', message: ERRORS[d] ?? '오류', detail: null }) : json(200, d);
}

export const mockTurn = (d: TurnDetail) => void (queue = [d]);
export const mockTurnSequence = (ds: (TurnDetail | number)[]) => void (queue = [...ds]);
export const mockUsage = (u: Partial<UsageOut>) => void (usageBody = usage(u));
export const urls = () => fetchMock.mock.calls.map(([u]) => String(u));
export const fetchCount = () => urls().filter((u) => u === '/api/devconsole/turns/41').length;
export const lastUrl = () => urls().at(-1) ?? '';
