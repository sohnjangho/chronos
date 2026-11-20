// 일정 도구 프로그램(스케줄·간트차트·CPM·공정률) 시험 전용 도우미: 가상 일정·가짜 일정 서버·창.
// 화면 코드는 이 파일을 import하지 않는다. 일정·사람은 모두 가상이다.
import { vi, type Mock } from 'vitest';
import { useWindows } from '../../os/windowStore';
import { json, signInAsDemo } from '../../test-helpers';
import type { Activity, Relation, ScheduleView, VersionItem } from './scheduleApi';
import { scheduleStore } from './scheduleStore';

type Row = [string, string, Activity['kind'], string, number, number | null, string, string, string | null, string | null, number, string, number, number];
// id, 이름, 유형, WBS, OD, RD, Plan 시작, Plan 종료, Actual 시작, Actual 종료, 진도, 상태, TF, FF
const ROWS: Row[] = [
  ['A1010', '착공', 'start_ms', '1', 0, null, '2027-03-02', '2027-03-02', '2027-03-02', '2027-03-02', 1, 'done', 0, 0],
  ['A1020', '터파기·흙막이', 'task', '1', 15, null, '2027-03-02', '2027-03-19', '2027-03-02', '2027-03-19', 1, 'done', 0, 0],
  ['A1030', '기초 철근·타설', 'task', '1', 15, null, '2027-03-22', '2027-04-09', '2027-03-22', '2027-04-10', 1, 'done', 0, 0],
  ['A1040', '타워크레인 설치', 'task', '1', 5, null, '2027-04-05', '2027-04-09', '2027-04-03', '2027-04-08', 1, 'early -2', 2, 2],
  ['A2010', '지하 1층 골조', 'task', '2', 18, null, '2027-04-12', '2027-05-05', '2027-04-12', '2027-05-10', 1, 'done', 0, 0],
  ['A2020', '지상 1~5층 골조', 'task', '2', 50, 32, '2027-05-06', '2027-07-14', '2027-05-11', null, 0.36, 'late +4', 0, 0],
  ['A3010', '외장 패널', 'task', '3', 35, null, '2027-07-15', '2027-09-01', null, null, 0, 'on_plan', 0, 0],
  ['A3020', '전기·기계 배관', 'task', '3', 40, null, '2027-06-14', '2027-08-06', null, null, 0, 'on_plan', 18, 0],
  ['A3030', '승강기 설치', 'task', '3', 25, null, '2027-08-09', '2027-09-10', null, null, 0, 'on_plan', 12, 12],
  ['A4010', '내부 마감', 'task', '4', 45, null, '2027-09-02', '2027-11-03', null, null, 0, 'on_plan', 0, 0],
  ['A4030', '준공', 'finish_ms', '4', 0, null, '2027-11-24', '2027-11-24', null, null, 0, 'on_plan', 0, 0],
];

const REL: [string, string, Relation['type'], number][] = [
  ['A1010', 'A1020', 'FS', 0],
  ['A1020', 'A1030', 'FS', 0],
  ['A1030', 'A1040', 'SS', 10],
  ['A1030', 'A2010', 'FS', 0],
  ['A2010', 'A2020', 'FS', 0],
  ['A1040', 'A2020', 'FS', 0],
  ['A2020', 'A3010', 'FS', 0],
  ['A1040', 'A3010', 'FS', 0],
  ['A2020', 'A3020', 'SS', 30],
  ['A2020', 'A3030', 'SS', 20],
  ['A3010', 'A4010', 'FS', 0],
  ['A3020', 'A4010', 'FS', 0],
  ['A4010', 'A4030', 'FS', 0],
];

export function activity([id, name, kind, wbs, od, rd, ps, pf, as, af, progress, status, tf, ff]: Row): Activity {
  return {
    id, name, kind, wbs, od, rd, progress, actual_start: as, actual_finish: af, constraint: null,
    resources: id === 'A2020' ? ['crane'] : [], tags: [], es: ps, ef: pf, plan_start: ps, plan_finish: pf,
    tf, ff, critical: tf === 0, status, weight: kind === 'task' ? Math.round((od / 248) * 10000) / 10000 : 0,
  };
}

/** 가상 일정 「5층 사무동 신축」 버전 1(시안 「스케줄표」의 줄). */
export function makeView(over: Partial<ScheduleView> = {}): ScheduleView {
  const activities = ROWS.map(activity);
  return {
    id: 1, name: '5층 사무동 신축', domain: 'construction', level: 'L3', version: 1,
    data_date: '2027-06-01', finish: '2027-11-24', plan_finish: '2027-11-24',
    wbs: [
      { code: '1', name: '기초', parent: null },
      { code: '2', name: '골조', parent: null },
      { code: '3', name: '외장·설비', parent: null },
      { code: '4', name: '마감', parent: null },
    ],
    activities,
    relations: REL.map(([pred, succ, type, lag]) => ({ pred, succ, type, lag })),
    resources: [{ id: 'crane', name: '타워크레인', unit: '대', capacity: 1 }],
    summary: { critical_count: activities.filter((a) => a.critical).length, negative_float_count: 0, warning_count: 1 },
    ...over,
  };
}

/** 버전·완료일 등 몇 칸만 바뀐 일정. */
export const viewWith = (over: Partial<ScheduleView>) => makeView(over);

type FetchFn = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
export let fetchMock: Mock<FetchFn>;
export let loadSpy: Mock<() => void>;
type Reply = { status: number; body: unknown } | (() => Promise<Response>);
let queued: Reply[] = [];
export const server = { view: makeView(), versions: [] as VersionItem[] };

/** 다음 쓰기(PATCH·PUT·POST·DELETE) 하나의 응답. 일정을 주면 200 그 일정. */
export function mockPatch(statusOrView: number | ScheduleView, body?: unknown) {
  queued.push(typeof statusOrView === 'number' ? { status: statusOrView, body } : { status: 200, body: statusOrView });
}

/** 다음 쓰기를 가중치 방식 PUT 의 성공({mode})으로 받고, 그 뒤 일정 읽기는 view 를 준다(방식은 버전 밖이라 다시 읽는다). */
export function mockWeightMode(mode: string, view: ScheduleView) {
  queued.push(async () => {
    server.view = view;
    return json(200, { mode });
  });
}

/** 다음 쓰기의 응답을 부르는 쪽이 정할 때까지 붙잡아 둔다. */
export function holdNextWrite() {
  let release!: (v: ScheduleView) => void;
  const gate = new Promise<ScheduleView>((ok) => (release = ok));
  queued.push(async () => json(200, await gate));
  return release;
}

const isWrite = (m: string) => m !== 'GET';

async function respond(url: string, method: string): Promise<Response> {
  if (url === '/api/schedules/1' && method === 'GET') {
    loadSpy();
    return json(200, server.view);
  }
  if (url === '/api/schedules/1/versions') return json(200, server.versions);
  const reply = isWrite(method) ? queued.shift() : undefined;
  if (typeof reply === 'function') return reply();
  if (reply) {
    if (reply.status === 200) server.view = reply.body as ScheduleView;
    return json(reply.status, reply.body);
  }
  if (isWrite(method)) {
    server.view = { ...server.view, version: server.view.version + 1 };
    return json(200, server.view);
  }
  return json(404, { code: 'not_found', message: '찾을 수 없습니다.', detail: null });
}

/** 가짜 일정 서버(일정 1) + 로그인(가상 사람) + 창 w1(스케줄)·w2(간트차트). */
export function setup(view: ScheduleView = makeView()) {
  signInAsDemo('admin');
  server.view = view;
  server.versions = [];
  queued = [];
  loadSpy = vi.fn<() => void>();
  fetchMock = vi.fn<FetchFn>((input, init) => respond(String(input), init?.method ?? 'GET'));
  vi.stubGlobal('fetch', fetchMock);
  const win = (id: string, programId: string, title: string, z: number) => ({ id, programId, title, x: 0, y: 48, w: 1600, h: 900, z, minimized: false, maximized: false });
  useWindows.setState({ wins: [win('w1', 'schedule-table', '스케줄', 1), win('w2', 'gantt', '간트차트', 2)] } as never);
}

/** 쓰기 요청들 [메서드, 경로, 본문]. */
export const writes = () =>
  fetchMock.mock.calls
    .filter(([, init]) => (init?.method ?? 'GET') !== 'GET')
    .map(([url, init]) => [init?.method, String(url), init?.body ? JSON.parse(String(init.body)) : undefined] as const);
export const lastBody = () => writes().at(-1)?.[2];


/** 그 일정 저장소의 지금 상태. */
export const schedule = (id = 1) => scheduleStore(id).getState();
