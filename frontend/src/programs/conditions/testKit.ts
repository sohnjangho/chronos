// 조건·규칙 시험 전용 도우미. 화면 코드는 이 파일을 import하지 않는다. 사람·현장은 모두 가상이다.
import { vi } from 'vitest';
import { useWindows } from '../../os/windowStore';
import { json, signInAsDemo, stubFetch } from '../../test-helpers';
import type { Cond, CondView, Moved, Preview, Side, Violation } from './condApi';

type Partial2<T> = { [K in keyof T]?: T[K] };

export const cond = (over: Partial2<Cond> & Pick<Cond, 'id' | 'layer' | 'kind' | 'text'>): Cond => ({
  params: {},
  source: over.layer === 'base' ? '기본 규칙' : over.layer === 'domain' ? '분야 규칙' : over.layer === 'mine' ? '내 규칙' : '프롬프트',
  enabled: true,
  editable: over.layer === 'input',
  state: 'passed',
  message: null,
  overridden_by: null,
  used_by: null,
  evidence: [],
  ...over,
});

const base = (id: string, text: string) => cond({ id: `base.${id}`, layer: 'base', kind: id, text, editable: false });

export function makeView(input: Cond[] = INPUTS): CondView {
  return {
    schedule_id: 1,
    name: '5층 사무동 신축',
    version: 3,
    layers: {
      base: [base('no_cycle', '선후 관계에 고리가 없음'), base('no_dangling', '관계가 있는 액티비티만 가리킴'), base('calendar', '달력에 일할 수 있는 날이 있음'), base('valid', '기간과 ID가 올바름')],
      domain: [
        cond({ id: 'construction.curing', layer: 'domain', kind: 'text_only', text: '슬래브 거푸집 해체는 타설 뒤 7일 이상 습윤 양생을 거친 뒤에 한다', state: 'uncheckable', message: '생성할 때 지침으로만 씁니다.', editable: 'toggle' }),
        cond({ id: 'construction.mep', layer: 'domain', kind: 'text_only', text: '설비 배관은 골조보다 2개 층 아래에서 따라간다', state: 'off', enabled: false, editable: 'toggle' }),
      ],
      mine: [cond({ id: 'my.floor', layer: 'mine', kind: 'max_duration', params: { days: 10 }, text: '층당 골조 10일', editable: false })],
      input: input.map((c) => ({ ...c, params: { ...c.params } })), // 시험마다 고쳐도 INPUTS 는 그대로
    },
    summary: { passed: 8, violated: 0, uncheckable: 2 },
    invalid: [],
    resources: [
      { id: 'tower_crane', name: '타워크레인', unit: '대', capacity: 1 },
      { id: 'rebar_crew', name: '철근공', unit: '명', capacity: 10 },
    ],
  };
}

export const INPUTS: Cond[] = [
  cond({ id: 'in.crane', layer: 'input', kind: 'resource_cap', params: { resource_id: 'tower_crane', capacity: 1 }, text: '타워크레인 1대', used_by: ['A3010', 'A3020'] }),
  cond({ id: 'in.rebar', layer: 'input', kind: 'resource_cap', params: { resource_id: 'rebar_crew', capacity: 10 }, text: '철근공 10명', used_by: ['A3010'] }),
  cond({ id: 'in.finish_by', layer: 'input', kind: 'finish_by', params: { date: '2027-11-30' }, text: '준공 2027.11.30 이전' }),
  cond({ id: 'in.winter', layer: 'input', kind: 'blocked_period', params: { start_md: [12, 1], end_md: [2, 28], tag: '타설' }, text: '12~2월 콘크리트 타설 금지', source: '프롬프트' }),
  cond({ id: 'in.safety', layer: 'input', kind: 'text_only', text: '"안전 우선으로 여유 있게"', state: 'uncheckable', message: '생성할 때 지침으로만 씁니다.' }),
];

export const m = (id: string): Moved => ({
  activity_id: id,
  name: `액티비티 ${id}`,
  before: { start: '2027-06-07', finish: '2027-07-16' },
  after: { start: '2027-04-26', finish: '2027-06-04' },
});

/** 서버(Task 18)와 같은 모양의 미리 보기. conditions 는 위반을 그 조건 줄에도 표시한다. */
type ViolationIn = Pick<Violation, 'condition_id' | 'message'> & Partial2<Violation>;
type PreviewIn = Partial2<Omit<Preview, 'before' | 'after' | 'violations'>> & {
  before?: Partial2<Side>;
  after?: Partial2<Side>;
  violations?: ViolationIn[];
  /** 미리 보기 상태의 조건 값(서버처럼 conditions 의 params 에 넣는다). */
  edits?: Record<string, Record<string, unknown>>;
};

export function mockPreview(input: PreviewIn = {}): Preview {
  const { edits = {}, ...over } = input;
  const violations = over.violations ?? [];
  const view = makeView();
  for (const layer of Object.values(view.layers)) {
    for (const c of layer) {
      const v = violations.find((x) => x.condition_id === c.id);
      if (v) Object.assign(c, { state: 'violated', message: v.message });
      if (edits[c.id]) c.params = { ...c.params, ...edits[c.id] };
    }
  }
  view.summary = { ...view.summary, violated: violations.length };
  return {
    feasible: violations.length === 0,
    moved: [],
    conditions: view,
    view: { id: 1, name: '5층 사무동 신축', domain: 'construction', level: 'L3', version: 3, data_date: null, finish: '2027-11-12', plan_finish: '2027-11-24', wbs: [], activities: [], relations: [], resources: [], summary: { critical_count: 0, negative_float_count: 0, warning_count: 0 } },
    ...over,
    violations: violations.map((v) => ({ ...v, activity_ids: v.activity_ids ?? [], amount: v.amount ?? null })),
    before: { finish: '2027-11-24', critical_count: 9, violated: 0, ...over.before },
    after: { finish: '2027-11-12', critical_count: 9, violated: violations.length, ...over.after },
  };
}

type Routes = Parameters<typeof stubFetch>[0];
export let fetchMock: ReturnType<typeof stubFetch>;
export let openSpy: ReturnType<typeof vi.fn>;
export const URL = '/api/schedules/1/conditions';

/** 로그인(가상 사람) + 가짜 조건 API(일정 1) + 창 store 의 open 엿보기. 창 w1 은 조건 창이다. */
export function setup(routes: Routes = {}, role: 'admin' | 'user' = 'admin') {
  signInAsDemo(role);
  const view = makeView();
  if (role === 'user') view.layers.domain = view.layers.domain.map((c) => ({ ...c, editable: false })); // 서버처럼
  fetchMock = stubFetch({ [URL]: view, '/api/rules?schedule_id=1': [], ...routes }); // 내 규칙 목록(Task 35)은 기본으로 비어 있다
  openSpy = vi.fn(() => 'w9');
  useWindows.setState({
    open: openSpy,
    wins: [{ id: 'w1', programId: 'conditions', title: '조건·규칙', x: 0, y: 48, w: 1400, h: 860, z: 1, minimized: false, maximized: false }],
  } as never);
}

export const respond = (body: unknown, status = 200) => () => json(status, body);

/** 이 경로·메서드로 간 요청의 본문들(보낸 차례). */
export const bodies = (path: string, method = 'POST') =>
  fetchMock.mock.calls
    .filter(([u, init]) => String(u) === path && (init?.method ?? 'GET') === method)
    .map(([, init]) => (init?.body ? JSON.parse(String(init.body)) : null));

/** 시험이 나중에 풀어 주는 응답. resolve(body, status) 를 부를 때까지 기다린다. */
export function deferred() {
  const waiting: ((r: Response) => void)[] = [];
  return {
    route: () => new Promise<Response>((resolve) => waiting.push(resolve)),
    count: () => waiting.length,
    resolve: (n: number, body: unknown, status = 200) => waiting[n](json(status, body)),
  };
}
