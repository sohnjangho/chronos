// 개발 콘솔 시험 전용 도우미. 화면 코드는 이 파일을 import 하지 않는다. 사람·현장·모델 이름은 모두 가상이다.
import { vi } from 'vitest';
import { json, signInAsDemo } from '../../test-helpers';
import type {
  HarnessMark,
  HarnessTestOut,
  NodeKey,
  NodeState,
  NotifyHealth,
  NotifyStep,
  OutreachDetail,
  OutreachRow,
  StructureNode,
  TraceItem,
  Turn,
  TurnDetail,
  UsageOut,
  VoiceHealth,
} from './devApi';

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

/** 연락 기록 한 줄(가상 — 번호는 가린 꼴만). */
export function outreachRow(over: Partial<OutreachRow> = {}): OutreachRow {
  return {
    kind: 'message', id: 501, at: new Date(Date.now() - 600_000).toISOString(), direction: 'out', channel: 'sms',
    origin: 'agent', origin_name: '에이전트', send_mode: 'delegated', caller_class: null, status: 'unconfirmed',
    contact_name: '가상 담당', company_name: '한빛전기', number_masked: '010-****-0199', schedule_name: '5층 사무동 신축',
    events: 7, needs_check: true, ...over,
  };
}

const OUTREACH_ROWS = (): OutreachRow[] => [
  outreachRow(),
  outreachRow({ kind: 'call', id: 77, channel: 'call', origin: 'user', origin_name: '김하늘', send_mode: 'approved', caller_class: 'outbound', status: 'completed', contact_name: '나가상', company_name: '동해설비', events: 2, needs_check: false, at: new Date(Date.now() - 900_000).toISOString() }),
  outreachRow({ id: 502, direction: 'in', origin: 'peer', origin_name: '', send_mode: null, caller_class: 'unknown', status: 'received', contact_name: null, company_name: null, schedule_name: null, events: 1, needs_check: false, at: new Date(Date.now() - 1_200_000).toISOString() }),
];

const mark = (over: Partial<HarnessMark>): HarnessMark => ({
  group: 'gate_decision', group_label: '나가는 문 판정', rule: null, verdict: 'allowed', verdict_label: '지나감', attempt: null,
  order: null, code: null, needs_check: false, unknown: false, ...over,
});

/** 연락 기록 하나의 시간표: 예약(근무시간 막음) → 시도 2(메모 → 통로 고르기 → 확인 필요) → 도구 · 도구 거절 · 모르는 사건. */
export function outreachDetail(over: Partial<OutreachDetail> = {}): OutreachDetail {
  const base = Date.now() - 600_000;
  const item = (seq: number, label: string, m: HarnessMark): TraceItem => ({
    seq, kind: 'harness', label, started_at: at(base, seq * 1000), ms: null, model: null, input_tokens: 0, output_tokens: 0,
    cost: null, ok: m.verdict !== 'blocked', error: m.verdict === 'blocked' ? m.verdict_label : null, input_text: '', output_text: '',
    parallel_group: null, harness: m,
  });
  const timeline = [
    item(1, '근무시간', mark({ rule: 'working_hours', verdict: 'blocked', verdict_label: '막음', attempt: 1, order: 3 })),
    item(2, '판정 메모', mark({ group: 'gate_note', group_label: '판정 메모', rule: 'reply_within_grace', verdict: 'noted', verdict_label: '메모', attempt: 2 })),
    item(3, '통로 고르기 — 문자', mark({ rule: 'channel_choice', attempt: 2, order: 7, code: 'sms' })),
    item(4, '통로 결과 — 보냈는지 확인 필요', mark({ group: 'channel_result', group_label: '통로 결과', rule: 'delivery', verdict: 'noted', verdict_label: '확인 필요', attempt: 2, needs_check: true })),
    item(5, '도구 find_contact', mark({ group: 'tool', group_label: '도구', rule: 'tool:find_contact', code: 'find_contact' })),
    item(6, '도구 거절 schedule_fact', mark({ group: 'tool', group_label: '도구', rule: 'scope_denied', verdict: 'blocked', verdict_label: '막음', code: 'schedule_fact' })),
    item(7, '알 수 없는 사건', mark({ group: null, group_label: '알 수 없는 사건', verdict: null, verdict_label: '—', unknown: true })),
  ];
  return {
    head: { ...outreachRow(), approved_by: null, fail_reason: null, reply_to_id: null },
    timeline,
    groups: [
      { key: 'gate_decision', label: '나가는 문 판정', count: 2 }, { key: 'gate_note', label: '판정 메모', count: 1 },
      { key: 'admission', label: '들어오는 문', count: 0 }, { key: 'tool', label: '도구', count: 2 },
      { key: 'post_check', label: '뒤 확인', count: 0 }, { key: 'channel_result', label: '통로 결과', count: 1 },
      { key: 'call', label: '통화', count: 0 }, { key: 'text_reply', label: '문자 답 만들기', count: 0 },
      { key: 'recovery', label: '서버 다시 시작', count: 0 }, { key: 'unknown', label: '알 수 없는 사건', count: 1 },
    ],
    attempts: 2,
    needs_check: 1,
    omitted: 0,
    flow: [
      { key: 'inbound', label: '들어오는 문', count: 0, verdicts: [] },
      { key: 'tool', label: '도구', count: 2, verdicts: [{ verdict: 'allowed', label: '지나감', count: 1 }, { verdict: 'blocked', label: '막음', count: 1 }] },
      { key: 'post_check', label: '뒤 확인', count: 0, verdicts: [] },
      { key: 'gate', label: '나가는 문', count: 3, verdicts: [{ verdict: 'blocked', label: '막음', count: 1 }, { verdict: 'noted', label: '메모', count: 1 }, { verdict: 'allowed', label: '지나감', count: 1 }] },
      { key: 'channel', label: '통로', count: 1, verdicts: [{ verdict: 'noted', label: '확인 필요', count: 1 }] },
    ],
    branches_lit: [],
    ...over,
  };
}

/** 통화 하나(Task 110): 문 판정 → 걸기 직전 재확인 → 도구 → 침묵 → 뒤 확인 깃발 → 끝을 모르는 통화 결과(확인 필요). */
export function callDetail(over: Partial<OutreachDetail> = {}): OutreachDetail {
  const base = outreachDetail();
  const item = (seq: number, label: string, m: HarnessMark, ok = m.verdict !== 'blocked'): TraceItem => ({
    ...base.timeline[0], seq, label, ok, error: m.verdict === 'blocked' ? m.verdict_label : null, harness: m,
  });
  const call = (rule: string, label: string, verdict: HarnessMark['verdict'], verdictLabel: string) =>
    mark({ group: 'call', group_label: '통화', rule, verdict, verdict_label: verdictLabel });
  return outreachDetail({
    head: { ...outreachRow({ kind: 'call', id: 77, channel: 'call', caller_class: 'outbound', status: 'failed', needs_check: true }), approved_by: null, fail_reason: '걸렸는지 확인 필요', reply_to_id: null, duration_s: 95, transcript_lines: 12 },
    timeline: [
      item(1, '통로 고르기 — 전화', mark({ rule: 'channel_choice', attempt: 1, order: 7, code: 'call' })),
      item(2, '걸기 직전 재확인', call('recheck_before_dial', '걸기 직전 재확인', 'allowed', '지나감')),
      item(3, '도구 find_contact', mark({ group: 'tool', group_label: '도구', rule: 'tool:find_contact', code: 'find_contact' })),
      item(4, '침묵 확인', call('silence', '침묵 확인', 'noted', '메모')),
      item(5, '도구 결과에 없는 날짜', mark({ group: 'post_check', group_label: '뒤 확인', rule: 'unsupported_date', verdict: 'noted', verdict_label: '메모' })),
      item(6, '통화 결과 — 음성 서버 오류', call('call_result', '통화 결과', 'blocked', '확인 필요'), true),
      item(7, '통로 결과 — 보냈는지 확인 필요', mark({ group: 'channel_result', group_label: '통로 결과', rule: 'delivery', verdict: 'noted', verdict_label: '확인 필요', needs_check: true })),
    ],
    attempts: 1,
    needs_check: 1,
    branches_lit: ['call_placed'],
    ...over,
  });
}

/** 시스템 진단의 AI 전화(가상) — 키·번호 없음. 마지막 음성 진단: 정상 · 확인 필요 · 실패(key_refused) · 건너뜀. */
export function voiceHealth(over: Partial<VoiceHealth> = {}): VoiceHealth {
  const step = (id: string, outcome: NotifyStep['outcome'], detail: string, code: string): NotifyStep => ({
    id, label: `${id} 걸음`, ok: outcome === 'ok', skipped: outcome === 'skipped', detail, code, maybe_sent: outcome === 'check', pending: false, outcome,
  });
  return {
    provider: 'google', model: 'gemini-3.8-live', status: 'ok', checked_at: '2026-11-24T00:50:00+00:00', sdk_installed: true,
    last_diagnosis: { ran_at: '2026-11-24T00:50:00+00:00', state: 'done', steps: [
      step('P5', 'ok', '음성 플랫폼 연결됨', 'ok'), step('P6', 'check', '끊김을 확인하지 못했습니다', 'cut_unconfirmed'),
      step('P11', 'failed', '구글이 이 키로 Gemini API 를 쓰지 못하게 합니다', 'key_refused'), step('P12', 'skipped', '', 'skipped'),
    ] },
    worker: { running: true, live: 1, backend: 'ok', listening: false, last_call_at: '2026-11-24T01:10:00+00:00', last_error_kind: 'TimeoutError', off_reason: null },
    ...over,
  };
}

/** 연락 하네스 도구 한 줄(카탈로그 — 등록부 밖, 끄기 없음). classes·media 는 서버가 toolsets.for_class 에서 읽는 값의 가상 꼴. */
export function harnessTool(name: string, classes: string[], media: string[]) {
  return {
    name: `outreach.${name}`, llm_name: name, program: null, category: '연락 하네스 도구', enabled: true, toggle: false, roles: [],
    role_note: '음성·글 에이전트 — 사람이 직접 부르지 않음', classes, media, description: `${name} 설명`, schema: { type: 'object' },
  };
}

/** 시스템 진단의 알림 연결(가상). 실패 한 걸음 · 확인 필요 한 걸음. */
export function notifyHealth(over: Partial<NotifyHealth> = {}): NotifyHealth {
  const step = (id: string, label: string, outcome: NotifyStep['outcome'], detail: string, code: string): NotifyStep => ({
    id, label, ok: outcome === 'ok', skipped: outcome === 'skipped', detail, code, maybe_sent: outcome === 'check' && id === 'P2',
    pending: outcome === 'check' && id === 'P3', outcome,
  });
  return {
    connected: true, status: 'ok', checked_at: '2026-11-24T00:30:00+00:00', test_mode: true, allow_count: 2,
    sender_masked: '070-****-0123', inbound_mode: 'known', agent: { sms: 'delegate', kakao: 'approve', call: 'approve' },
    worker: { running: true, last_tick_at: '2026-11-24T01:02:03+00:00', last_due_at: '2026-11-24T01:02:03+00:00', last_status_poll_at: '2026-11-24T01:01:43+00:00', last_inbound_poll_at: null, last_error_kind: null },
    needs_check: 1,
    last_diagnosis: {
      ran_at: '2026-11-24T00:40:00+00:00', state: 'done', steps: [
        step('P1', '인증 + 발신번호 목록', 'ok', '발신번호 1개(승인 1)', 'ok'),
        step('P2', '시험 문자 1건 보내기', 'skipped', '시험 문자를 청하지 않았습니다', 'skipped_no_send'),
        step('P3', '보낸 문자 상태 조회', 'check', '아직 접수 상태입니다(실패 아님)', 'still_queued'),
        step('P4', '받은 문자 목록', 'failed', '받은 문자 목록을 읽지 못했습니다', 'server'),
      ],
    },
    kakao: null, voice: null, ...over,
  };
}

const OLDER = turn({ turn_id: 38, request: '5층 사무동 공정표 만들어 줘', status: 'done', ms: 64_000, tokens: 48_200, started_at: new Date(Date.now() - 86_400_000).toISOString() });

let list: Turn[] = [];
/** 상세 응답 차례. 숫자는 그 상태 코드의 오류 응답. */
let queue: (TurnDetail | number)[] = [];
let usageBody: UsageOut = usage();
/** 차단 시험 응답에 덮어쓸 칸(blocked 등). */
let harnessPatch: Partial<HarnessTestOut> = {};
const byId = new Map<number, TurnDetail>();
export let fetchMock: ReturnType<typeof vi.fn>;

/** 가짜 카탈로그(예전 서버 모양: group·roles·mutates 없음). mockCatalog 로 고친다. */
function catalogSample() {
  return {
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
      { id: 'H-LOOP-01', area: '루프', title: '도구 실패 시 DB 롤백 및 자가 점검 지시 주입', description: '실패 도구 롤백',
        code: 'app/agent/loop.py', mode: '자동 롤백', feedback_sample: '{}', passed_count: 2, blocked_count: 1 },
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
    sources: {
      system_file: 'system.md',
      system_raw: 'prompt',
      system_chars: 6,
      levels_prompt: 'L3',
      guides: [],
      pipeline_prompts: [{ name: 'wbs', file: 'app/agent/prompts/wbs.md', chars: 120, content: '# WBS prompt body' }],
      domains: [],
    },
    registry: {
      tools: [
        {
          name: 'progress.read',
          llm_name: 'progress__read',
          program: 'progress',
          category: '조회·계산·조작',
          enabled: true,
          calls: 4,
          failed: 1,
          avg_ms: 82,
          description: '공정률과 SPI를 읽습니다.',
          schema: { type: 'object', properties: {} },
        },
      ],
      skills: [
        {
          id: 11,
          name: '월간 공정 보고',
          description: '공정률을 읽고 보고서를 만듭니다.',
          triggers: ['월간', '보고서'],
          steps: [{ tool: 'progress.read' }, { tool: 'report.generate' }],
          use_count: 3,
        },
      ],
    },
  };
}

/** 가짜 시스템 진단(예전 서버 모양). mockHealth 로 칸을 더한다. */
function healthSample() {
  return {
    llm: {
      status: 'ok',
      connections_count: 1,
      assignments_count: 4,
      default_name: 'Liner 기본',
      default_provider: 'liner',
      default_base_url: 'https://api.example.com',
      key_ready: true,
      message: '기본 연결 및 인증 키 준비됨',
    },
    qdrant: {
      status: 'ok',
      collections: ['chunks__inst__embed__1536'],
      points_count: 42,
      latency_ms: 9,
      message: '연결 정상 (컬렉션 1개 · 벡터 42건)',
    },
    search: {
      status: 'ok',
      ready: true,
      calls_7d: 7,
      failed_7d: 0,
      message: 'Liner Search/MCP 준비됨 (최근 7일 7회 · 실패 0건)',
    },
    db: {
      status: 'ok',
      size_bytes: 204800,
      counts: { users: 3, schedules: 2, chats: 5, workflow_runs: 6, files: 4, approvals: 1, reports: 2, skills: 1 },
    },
    active_turns: [{ chat_session_id: 7, title: '골조 지연 만회', stop_requested: false }],
  };
}

let sampleCatalog = catalogSample();
let sampleHealth: Record<string, unknown> = healthSample();
let outreachRows: OutreachRow[] = [];
let outreachMore = false;
const outreachById = new Map<string, OutreachDetail>();

/** 가짜 개발 콘솔 서버. 상세는 queue 를 차례로(마지막 하나는 계속), 다른 턴은 byId 로. */
export function setup(role: 'admin' | 'user' = 'admin') {
  signInAsDemo(role);
  queue = [running()];
  list = [turn(), OLDER];
  byId.clear();
  byId.set(38, done({ turn_id: 38, request: OLDER.request, started_at: OLDER.started_at }, { unpaired: true }));
  usageBody = usage();
  harnessPatch = {};
  sampleCatalog = catalogSample();
  sampleHealth = healthSample();
  outreachRows = OUTREACH_ROWS();
  outreachMore = false;
  outreachById.clear();
  outreachById.set('message/501', outreachDetail());
  fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === '/api/devconsole/turns?limit=30') return json(200, list);
    if (url === '/api/devconsole/outreach?limit=30') return json(200, { items: outreachRows, more: outreachMore, limit: 30 });
    const o = /^\/api\/devconsole\/outreach\/(message|call)\/(\d+)$/.exec(url);
    if (o && outreachById.has(`${o[1]}/${o[2]}`)) return json(200, outreachById.get(`${o[1]}/${o[2]}`));
    const m = /^\/api\/devconsole\/turns\/(\d+)$/.exec(url);
    if (m && Number(m[1]) === 41) return detailResponse(queue.length > 1 ? queue.shift()! : queue[0]);
    if (m && byId.has(Number(m[1]))) return json(200, byId.get(Number(m[1])));
    if (url.startsWith('/api/devconsole/usage?')) return json(200, usageBody);
    if (url === '/api/devconsole/catalog') return json(200, sampleCatalog);
    if (url === '/api/devconsole/health') return json(200, sampleHealth);
    if (/^\/api\/devconsole\/turns\/\d+\/stop$/.test(url) && init?.method === 'POST') {
      return json(200, { chat_session_id: 7, stopped: true });
    }
    if (url.startsWith('/api/devconsole/tools/') && init?.method === 'PUT') {
      const name = decodeURIComponent(url.replace('/api/devconsole/tools/', ''));
      const body = JSON.parse(String(init.body));
      sampleCatalog.registry.tools = sampleCatalog.registry.tools.map((t) => (t.name === name ? { ...t, enabled: body.enabled } : t));
      return json(200, { name, enabled: body.enabled });
    }
    if (url.startsWith('/api/workflows/skills/') && init?.method === 'DELETE') {
      const id = Number(url.replace('/api/workflows/skills/', ''));
      sampleCatalog.registry.skills = sampleCatalog.registry.skills.filter((s) => s.id !== id);
      return new Response(null, { status: 204 });
    }
    const h = /^\/api\/devconsole\/harness\/([^/]+)\/test$/.exec(url);
    if (h && init?.method === 'POST') return json(200, harnessOut(h[1]));
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

/** 차단 시험 응답: 실엔진(live_harness)으로 막았다. mockHarness 로 칸을 덮어쓴다. */
function harnessOut(ruleId: string): HarnessTestOut {
  return {
      rule_id: ruleId,
      title: ruleId,
      blocked: true,
      engine: 'live_harness',
      elapsed_ms: 12,
      simulated_input: '임시 DB 에서 에이전트 루프(loop.run_turn) 실실행',
      model_feedback: { rule_id: ruleId, llm_calls: 12, limit: 12 },
      ...harnessPatch,
    };
  }

  export const mockTurn = (d: TurnDetail) => void (queue = [d]);
  export const mockTurnSequence = (ds: (TurnDetail | number)[]) => void (queue = [...ds]);
  export const mockUsage = (u: Partial<UsageOut>) => void (usageBody = usage(u));
  export const mockHarness = (patch: Partial<HarnessTestOut>) => void (harnessPatch = patch);
/** 카탈로그를 고친다(새 서버의 칸 — group·roles·mutates 등). */
export const mockCatalog = (edit: (c: ReturnType<typeof catalogSample>) => void) => edit(sampleCatalog);
/** 시스템 진단에 칸을 더한다(새 서버의 info_api·evidence_reuse·holidays·vision). */
export const mockHealth = (extra: Record<string, unknown>) => void (sampleHealth = { ...sampleHealth, ...extra });
/** 연락 기록 목록(more = 상한 밖에 더 있음)과 상세(kind/id 열쇠). */
export const mockOutreachList = (rows: OutreachRow[], more = false) => void ((outreachRows = rows), (outreachMore = more));
export const mockOutreach = (kind: string, id: number, d: OutreachDetail) => void outreachById.set(`${kind}/${id}`, d);
  export const urls = () => fetchMock.mock.calls.map(([u]) => String(u));
  export const fetchCount = () => urls().filter((u) => u === '/api/devconsole/turns/41').length;
  export const lastUrl = () => urls().at(-1) ?? '';
