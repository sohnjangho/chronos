// CPM 시험 전용 도우미. 화면 코드는 이 파일을 import하지 않는다. 일정·사람은 모두 가상이다.
import { render, screen } from '@testing-library/react';
import type { Activity, Relation, RelType, ScheduleView } from '../../shared/schedule/scheduleApi';
import { fetchMock, makeView, setup } from '../../shared/schedule/testKit';
import { json } from '../../test-helpers';
import Cpm from './Cpm';

export * from '../../shared/schedule/testKit';

/** 액티비티 하나(이름 「작업 <id>」, 크리티컬, 계획 내). over 로 몇 칸만 바꾼다. 날짜는 서버 값처럼 넣기만 한다. */
export function a(id: string, over: Partial<Activity> = {}): Activity {
  const es = over.es ?? '2027-03-01';
  return {
    id, name: `작업 ${id}`, kind: 'task', wbs: '1', od: 3, rd: null, progress: 0, actual_start: null, actual_finish: null,
    constraint: null, resources: [], tags: [], es, ef: es, ls: es, lf: es, plan_start: es, plan_finish: es,
    tf: 0, ff: 0, critical: true, status: 'on_plan', weight: 0, ...over,
  };
}

export const r = (pred: string, succ: string, type: RelType = 'FS', lag = 0): Relation => ({ pred, succ, type, lag });

/** 가상 일정 「5층 사무동 신축」 모양에 액티비티·관계만 바꾼 것. */
export function view(activities: Activity[], relations: Relation[], over: Partial<ScheduleView> = {}): ScheduleView {
  return makeView({
    activities, relations,
    summary: { critical_count: activities.filter((x) => x.critical).length, negative_float_count: 0, warning_count: 0 },
    ...over,
  });
}

/** 시험 기본 그물: A → B → C, A → D → C(SS+15). D 만 크리티컬이 아니다. */
export const small = () =>
  view(
    [a('A', { es: '2027-03-01' }), a('B', { es: '2027-03-04' }), a('D', { es: '2027-03-04', critical: false, tf: 3 }), a('C', { es: '2027-03-08' })],
    [r('A', 'B'), r('A', 'D'), r('B', 'C'), r('D', 'C', 'SS', 15)],
  );

/** n 개 노드(열 20개 × 줄 n/20, 앞 열의 같은 줄·다음 줄로 FS). 날짜는 차례로 미룬 모양만(계산 아님). */
export function bigView(n = 200): ScheduleView {
  const day = (i: number) => new Date(Date.UTC(2027, 2, 2 + i)).toISOString().slice(0, 10);
  const rows = Math.ceil(n / 20);
  const id = (i: number) => `N${String(i + 1).padStart(4, '0')}`;
  const acts = Array.from({ length: n }, (_, i) => a(id(i), { name: `가상 공정 ${i + 1}`, es: day(Math.floor(i / rows) * 3), critical: i % rows === 0 }));
  const rels: Relation[] = [];
  for (let i = rows; i < n; i += 1) {
    rels.push(r(id(i - rows), id(i)));
    if (i % rows !== rows - 1) rels.push(r(id(i - rows + 1), id(i)));
  }
  return view(acts, rels);
}

type Reply = { status: number; body: unknown };
let progressReply: Reply = { status: 200, body: { cpm: { plan_compliance: null, critical_variance: null, finish_variance: null } } };
let scenariosReply: Reply = { status: 200, body: [] };

/** 진행 API(Task 24) 응답. 다음 읽기부터. */
export function mockProgress(body: unknown, status = 200) {
  progressReply = { status, body };
}

/** 반영된 복사본 목록(Task 26, 새것부터). */
export function mockScenarios(list: unknown[], status = 200) {
  scenariosReply = { status, body: list };
}

/** 일정 시험 서버 + 진행·복사본 읽기. */
export function setupCpm(v: ScheduleView = small()) {
  setup(v);
  progressReply = { status: 200, body: { cpm: { plan_compliance: null, critical_variance: null, finish_variance: null } } };
  scenariosReply = { status: 200, body: [] };
  const inner = fetchMock.getMockImplementation()!;
  fetchMock.mockImplementation(async (input, init) => {
    const url = String(input);
    if (url === '/api/schedules/1/progress') return json(progressReply.status, progressReply.body);
    if (url === '/api/schedules/1/scenarios?status=applied') return json(scenariosReply.status, scenariosReply.body);
    return inner(input, init);
  });
}

/** CPM 창(w1). */
export async function renderCpm(params: Record<string, string> = { id: '1' }) {
  const out = render(<Cpm windowId="w1" params={params} />);
  await screen.findByRole('toolbar', { name: 'CPM 도구' });
  return out;
}

const q = <T extends Element>(sel: string) => document.querySelector<T>(sel);
/** 카드(SVG g). within() 이 HTMLElement 를 받으므로 그 모양으로 돌려준다. */
export const card = (aid: string) => q<SVGGElement>(`[data-node="${aid}"]`) as unknown as HTMLElement;
export const edge = (from: string, to: string) => q<SVGGElement>(`[data-edge^="${from}>${to}:"]`) as unknown as HTMLElement;
export const networkSvg = () => q<SVGSVGElement>('svg[data-network]')!;
export const canvas = () => q<HTMLDivElement>('.cpm-canvas')!;
export const nodeIds = () => [...document.querySelectorAll('[data-node]')].map((n) => n.getAttribute('data-node'));
/** 카드의 자리(transform 의 translate). */
export function at(aid: string): [number, number] {
  const m = /translate\(([-\d.]+)[ ,]+([-\d.]+)\)/.exec(card(aid).getAttribute('transform') ?? '');
  return [Number(m![1]), Number(m![2])];
}
