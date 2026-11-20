// 지연 기록 시험 전용 도우미: 가상 일정 「5층 사무동 신축」(shared testKit) + 가짜 지연 API.
// 화면 코드는 이 파일을 import 하지 않는다. 사람·현장은 모두 가상이다.
import { vi } from 'vitest';
import { useSchedulePreview, type MovedActivity, type PreviewView } from '../../os/schedulePreview';
import { activity, fetchMock, makeView, setup } from '../../shared/schedule/testKit';
import { json } from '../../test-helpers';
import type { DelayEvent, DelaysData, Impact } from './delaysApi';

/** shared testKit 의 일정 + 외장·설비 묶음의 「작업 B」. */
export const VIEW = (() => {
  const v = makeView();
  const b = activity(['B', '작업 B', 'task', '3', 10, null, '2027-07-15', '2027-07-28', null, null, 0, 'on_plan', 4, 4]);
  return { ...v, activities: [...v.activities, b] };
})();

const impact = (over: Partial<Impact> = {}): Impact => ({
  applied: true, note: null, finish_before: '2027-11-24', finish_after: '2027-11-24', finish_delta: 0, absorbed: 0,
  milestones: [], critical_added: [], critical_removed: [], affected: [], new_clashes: [], cost: null, ...over,
});

export function ev(over: Partial<DelayEvent> = {}): DelayEvent {
  return {
    id: 1, activity_id: 'B', activity_name: '작업 B', start_date: '2027-06-02', days: 2, cause: '우천', responsibility: 'force',
    daily_cost: 3_100_000, evidence: '', source: 'user', status: 'open',
    impact: impact({
      finish_after: '2027-11-26', finish_delta: 2, cost: 6_200_000, affected: ['B', 'A4010', 'A4030'],
      milestones: [{ activity_id: 'A4030', name: '준공', before: '2027-11-24', after: '2027-11-26', delta: 2 }],
      critical_added: [{ id: 'B', name: '작업 B' }],
    }),
    analyzed_version: 1, reflected_version: null, stale: false, created_by: '김하늘', created_at: '2027-06-02T01:00:00Z',
    ...over,
  };
}

/** 두 번째 사건: 여유로 다 흡수, 새 타워크레인 겹침, 하루 금액 없음. */
export const E2 = ev({
  id: 2, activity_id: 'A3020', activity_name: '전기·기계 배관', start_date: '2027-06-14', days: 3, cause: '자재 반입 지연',
  responsibility: 'owner', daily_cost: null, evidence: '공문_0611.pdf', source: 'chat',
  impact: impact({ absorbed: 3, affected: ['A3020'], new_clashes: [{ resource_id: 'crane', name: '타워크레인', first: '2027-07-19', days: 4, over: 1 }] }),
});

export const D: DelaysData = {
  schedule_id: 1, version: 1, events: [ev(), E2],
  totals: { finish_impact: 2, by_responsibility: { owner: 0, ours: 0, force: 2, undecided: 0 }, absorbed: 3, absorbed_events: 1, cost: 6_200_000, open_count: 2 },
  finish: { plan: '2027-11-24', current: '2027-11-24', with_open: '2027-11-26', deadline: '2027-11-30', deadline_float: 2 },
};

/** 간트 미리 보기의 일정(B 가 밀린 것처럼 — 값은 시험용). */
export const V: PreviewView = { ...VIEW, finish: '2027-11-26' } as PreviewView;
export const m = (aid: string): MovedActivity => ({
  activity_id: aid, name: aid, before: { start: '2027-07-15', finish: '2027-07-28' }, after: { start: '2027-07-19', finish: '2027-07-30' },
});

type Reply = { status: number; body: unknown };
let getReply: Reply = { status: 200, body: D };
let writeQueue: Reply[] = [];
let scenarioReply: Reply = { status: 200, body: { scenario_id: 1 } };
let previewReply: Reply = { status: 200, body: { view: V, moved: [] } };
let calls: { method: string; url: string; body: unknown }[] = [];

/** 지연 목록 GET 의 응답(쓰기의 기본 응답도 이것). */
export function mockDelays(data: DelaysData) {
  getReply = { status: 200, body: data };
}
/** 다음 쓰기(POST·PATCH·analyze) 하나의 응답. */
export const mockWrite = (data: DelaysData) => writeQueue.push({ status: 200, body: data });
export const mockPostError = (status: number, body: unknown) => writeQueue.push({ status, body });
export function mockScenario(id: number) {
  scenarioReply = { status: 200, body: { scenario_id: id } };
}
export function mockScenarioError(status: number, body: unknown) {
  scenarioReply = { status, body };
}
export function mockDelayPreview(p: { view: PreviewView; moved: MovedActivity[] }) {
  previewReply = { status: 200, body: p };
}

function route(method: string, url: string): Reply {
  if (url === '/api/schedules/1/delays/scenario') return scenarioReply;
  if (url === '/api/schedules/1/delays/preview') return previewReply;
  if (method === 'GET') return getReply;
  return writeQueue.shift() ?? getReply;
}

/** 가짜 일정 서버(일정 1) + 로그인 + 지연 API. */
export function stubDelaysApi() {
  setup(VIEW);
  getReply = { status: 200, body: D };
  writeQueue = [];
  scenarioReply = { status: 200, body: { scenario_id: 1 } };
  previewReply = { status: 200, body: { view: V, moved: [] } };
  calls = [];
  const base = fetchMock;
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (!url.startsWith('/api/schedules/1/delays')) return base(input, init);
      const method = init?.method ?? 'GET';
      calls.push({ method, url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      const r = route(method, url);
      return Promise.resolve(json(r.status, r.body));
    }),
  );
}

/** 지연 API 요청들. */
export const delayCalls = () => calls;
export const lastBody = () => calls.filter((c) => c.method !== 'GET').at(-1)?.body;
export const previewFor = (id: number) => useSchedulePreview.getState().previews[id];
