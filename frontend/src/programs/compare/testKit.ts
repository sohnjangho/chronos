// 비교판 시험 전용 도우미: 가상 일정 「5층 사무동 신축」(일정 1)의 비교·요약·버전 응답과 가짜 서버.
// 값은 Task 34 비교 API 시험과 같은 뜻(근무일 차이, 기한 3/16)으로 손으로 맞췄다. 화면 코드는 이 파일을 import 하지 않는다.
import { vi, type Mock } from 'vitest';
import { json, signInAsDemo } from '../../test-helpers';
import type { CompareOut, SideOut, VersionItem } from './compareApi';

const side = (over: Partial<SideOut> & Pick<SideOut, 'ref' | 'label'>): SideOut => ({
  version: 3, finish: '2027-03-19', plan_delta: 0, deadline: '2027-03-16', deadline_float: -3, critical_count: 3,
  violations: 0, uncheckable: 0, peak: null, changes: [], stale: false, status: null, ...over,
});

export const CURRENT = side({
  ref: 'current', label: '현재 일정 (버전 3)', plan_delta: 2, violations: 1,
  peak: { resource_id: 'crane', name: '타워크레인', need: 2, capacity: 1, when: '2027-03-08' },
});
export const PLAN = side({ ref: 'plan', label: 'Plan (버전 3)', finish: '2027-03-17', plan_delta: 0, deadline_float: -1 });
export const DELAY = side({ ref: 's:4', label: '지연 반영안 (1건)', finish: '2027-03-19', plan_delta: 2, status: 'open' });
export const RECOVERY = side({
  ref: 's:5', label: '만회안 A · 병행 우선', finish: '2027-03-16', plan_delta: -1, deadline_float: 0, critical_count: 2,
  uncheckable: 1, changes: ['A 절반 지점에서 B 시작'], status: 'open',
});

/** 요약 표: 현재 · Plan · 열린 복사본 새것부터. */
export const S = { sides: [CURRENT, PLAN, RECOVERY, DELAY] };

/** 현재 일정 대 만회안 A. A 같음 · B 당김(시작 −2, 종료 −3, OD 5→4) · E 밀림(+2, 여유 안) · C·M 당김 −3. */
export const C: CompareOut = {
  base: CURRENT,
  other: RECOVERY,
  rows: [
    { activity_id: 'A', name: '작업 A', wbs: '1', base: { start: '2027-03-01', finish: '2027-03-05', od: 5 }, other: { start: '2027-03-01', finish: '2027-03-05', od: 5 }, start_delta: 0, finish_delta: 0, change: 'same' },
    { activity_id: 'B', name: '작업 B', wbs: '1', base: { start: '2027-03-08', finish: '2027-03-12', od: 5 }, other: { start: '2027-03-04', finish: '2027-03-09', od: 4 }, start_delta: -2, finish_delta: -3, change: 'pulled' },
    { activity_id: 'E', name: '작업 E', wbs: '2', base: { start: '2027-03-08', finish: '2027-03-10', od: 3 }, other: { start: '2027-03-10', finish: '2027-03-12', od: 3 }, start_delta: 2, finish_delta: 2, change: 'pushed' },
    { activity_id: 'C', name: '작업 C', wbs: '2', base: { start: '2027-03-15', finish: '2027-03-19', od: 5 }, other: { start: '2027-03-10', finish: '2027-03-16', od: 5 }, start_delta: -3, finish_delta: -3, change: 'pulled' },
    { activity_id: 'M', name: '준공', wbs: '2', base: { start: '2027-03-19', finish: '2027-03-19', od: 0 }, other: { start: '2027-03-16', finish: '2027-03-16', od: 0 }, start_delta: -3, finish_delta: -3, change: 'pulled' },
  ],
  changed_count: 4,
};

export const V: VersionItem[] = [
  { n: 3, note: '지연 기록 반영', by_kind: 'user', by_name: '김하늘', is_plan: false, created_at: '2027-03-03T01:00:00Z' },
  { n: 2, note: '실적 입력', by_kind: 'agent', by_name: '에이전트', is_plan: false, created_at: '2027-03-02T01:00:00Z' },
  { n: 1, note: '첫 저장', by_kind: 'user', by_name: '김하늘', is_plan: true, created_at: '2027-03-01T01:00:00Z' },
];

type Reply = { status: number; body: unknown };
const asReply = (b: unknown): Reply => (b && typeof b === 'object' && 'status' in b && 'body' in b ? (b as Reply) : { status: 200, body: b });
let replies: Record<'summary' | 'compare' | 'submit' | 'discard' | 'versions', Reply>;
/** 붙잡아 둔 다음 응답(요약·비교). 풀 때까지 답하지 않는다. */
let gates: Partial<Record<'summary' | 'compare', Promise<void>>> = {};
type FetchFn = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
export let fetchMock: Mock<FetchFn>;

export const mockSummary = (b: unknown) => void (replies.summary = asReply(b));
export const mockCompare = (b: unknown) => void (replies.compare = asReply(b));
export const mockSubmit = (b: unknown) => void (replies.submit = asReply(b));
export const mockDiscard = (b: unknown) => void (replies.discard = asReply(b));
export const mockVersions = (b: unknown) => void (replies.versions = asReply(b));

/** 다음 요약·비교 응답을 부르는 쪽이 풀 때까지 붙잡는다. 돌려준 함수로 푼다. */
export function holdNext(kind: 'summary' | 'compare'): () => void {
  let release!: () => void;
  gates[kind] = new Promise<void>((ok) => (release = ok));
  return release;
}

async function gated(kind: 'summary' | 'compare', reply: () => Reply): Promise<Response> {
  const gate = gates[kind];
  delete gates[kind];
  if (gate) await gate;
  const x = reply();
  return json(x.status, x.body);
}

async function respond(url: string, method: string): Promise<Response> {
  const r = (x: Reply) => json(x.status, x.body);
  if (url === '/api/schedules/1/compare/summary') return gated('summary', () => replies.summary);
  if (url.startsWith('/api/schedules/1/compare?')) return gated('compare', () => replies.compare);
  if (url === '/api/schedules/1/versions') return r(replies.versions);
  if (url === '/api/schedules') return json(200, [{ id: 1, name: '5층 사무동 신축' }, { id: 2, name: '가상 부품 공장' }]);
  if (url === '/api/approvals/count') return json(200, { pending: 1 });
  if (method === 'POST' && /^\/api\/schedules\/1\/scenarios\/\d+\/submit$/.test(url)) return r(replies.submit);
  if (method === 'DELETE' && /^\/api\/schedules\/1\/scenarios\/\d+$/.test(url)) return r(replies.discard);
  return json(404, { code: 'not_found', message: '찾을 수 없습니다.', detail: null });
}

/** 로그인(가상 사람) + 가짜 서버. 기본 응답은 S · C · 제출 승인 7 · 버리기 성공. */
export function stubCompareApi() {
  signInAsDemo('admin');
  replies = {
    summary: { status: 200, body: S },
    compare: { status: 200, body: C },
    submit: { status: 200, body: { approval_id: 7, applied: false, status: 'submitted' } },
    discard: { status: 200, body: { status: 'discarded' } },
    versions: { status: 200, body: V },
  };
  gates = {};
  fetchMock = vi.fn<FetchFn>((input, init) => respond(String(input), init?.method ?? 'GET'));
  vi.stubGlobal('fetch', fetchMock);
}

const calls = () => fetchMock.mock.calls.map(([u, init]) => [init?.method ?? 'GET', String(u), init?.body ? JSON.parse(String(init.body)) : undefined] as const);
/** 비교 API 를 부른 주소들(요약 빼고). */
export const compareUrls = () => calls().filter(([m, u]) => m === 'GET' && u.startsWith('/api/schedules/1/compare?')).map(([, u]) => u);
export const lastUrl = () => compareUrls().at(-1) ?? '';
export const summaryCalls = () => calls().filter(([, u]) => u === '/api/schedules/1/compare/summary').length;
/** 쓰기 요청들 [메서드, 경로, 본문]. */
export const writes = () => calls().filter(([m]) => m !== 'GET');
export const lastBody = () => writes().at(-1)?.[2];
