// 질문지 시험 전용 도우미. 화면 코드는 이 파일을 import하지 않는다. 사람·현장은 모두 가상이다.
import { vi } from 'vitest';
import { useWindows } from '../../os/windowStore';
import { json, signInAsDemo, stubFetch } from '../../test-helpers';
import type { QOption, QView } from './qApi';

export interface FakeQuestion {
  id: string;
  group: string;
  question: string;
  why: string;
  options: QOption[];
  allow_free: boolean;
  assumption: string;
}

const opt = (value: string, label: string, hint: string | null = null, recommended = false): QOption => ({ value, label, hint, recommended });

/** 범위 2 · 날짜 1 · 달력 2. 착공일 선택지 값은 날짜 그대로다. */
export const QUESTIONS: FakeQuestion[] = [
  {
    id: 'structure',
    group: '범위',
    question: '건물의 구조 형식은 무엇인가요?',
    why: '층당 골조 기간이 구조 형식에 따라 달라집니다.',
    options: [opt('rc', '철근콘크리트', '중층 사무동에 가장 흔합니다.', true), opt('steel', '철골')],
    allow_free: true,
    assumption: '철근콘크리트 구조로 가정합니다.',
  },
  {
    id: 'basement',
    group: '범위',
    question: '지하층이 있나요?',
    why: '흙막이와 터파기 기간이 달라집니다.',
    options: [opt('b1', '지하 1층', null, true), opt('none', '지하층 없음')],
    allow_free: true,
    assumption: '지하 1층으로 가정합니다.',
  },
  {
    id: 'start_date',
    group: '날짜',
    question: '착공일은 언제인가요?',
    why: '',
    options: [opt('2027-03-02', '2027-03-02 (화) 착공'), opt('2027-04-01', '2027-04-01 (목) 착공')],
    allow_free: true,
    assumption: '2027-03-02 에 착공한다고 가정합니다.',
  },
  {
    id: 'work_week',
    group: '달력',
    question: '주 며칠 일하나요?',
    why: '작업 달력을 정합니다.',
    options: [opt('5', '주 5일'), opt('6', '주 6일', '건설 현장 기본', true)],
    allow_free: false,
    assumption: '주 6일로 가정합니다.',
  },
  {
    id: 'holiday_rule',
    group: '달력',
    question: '토요일 작업은 어떻게 하나요?',
    why: '',
    options: [],
    allow_free: true,
    assumption: '토요일은 매주 일하는 것으로 가정합니다.',
  },
];

export const RETAINING_WALL: FakeQuestion = {
  id: 'retaining_wall',
  group: '범위',
  question: '흙막이는 어떤 방식인가요?',
  why: '"지하 1층"이라고 답하셔서 생긴 질문입니다.',
  options: [opt('h_pile', 'H파일 + 토류판', '지하 1층에 흔함', true)],
  allow_free: true,
  assumption: 'H파일 + 토류판으로 가정합니다.',
};

export const PREFILLED = [
  { label: '분야', value: '건설', source: '프롬프트' },
  { label: '정밀도', value: 'L3 관리', source: '분야 지식' },
];

export interface FakeState {
  questions: FakeQuestion[];
  answers: Record<string, string>;
  status: 'open' | 'submitted' | 'closed';
  chat_session_id: number | null;
}

function labelOf(q: FakeQuestion, value: string): string {
  return q.options.find((o) => o.value === value)?.label ?? value;
}

/** 서버(Task 8)와 같은 모양의 보기. 묶음은 질문에 처음 나온 차례. */
export function buildView(s: FakeState, id = 1): QView {
  const groups: QView['groups'] = [];
  for (const q of s.questions) {
    let g = groups.find((x) => x.name === q.group);
    if (!g) groups.push((g = { name: q.group, answered: 0, total: 0, questions: [] }));
    const value = s.answers[q.id];
    const { group: _group, ...rest } = q;
    void _group;
    g.questions.push({ ...rest, answer: value === undefined ? null : { value, label: labelOf(q, value) } });
    g.total += 1;
    g.answered += value === undefined ? 0 : 1;
  }
  const answered = groups.reduce((n, g) => n + g.answered, 0);
  return {
    id,
    title: '5층 사무동 신축 일정 질문지',
    purpose: 'generate',
    status: s.status,
    round: 1,
    chat_session_id: s.chat_session_id,
    progress: { answered, total: s.questions.length },
    prefilled: PREFILLED,
    groups,
  };
}

type Routes = Parameters<typeof stubFetch>[0];
export let fetchMock: ReturnType<typeof stubFetch>;
export let openSpy: ReturnType<typeof vi.fn>;
export let closeSpy: ReturnType<typeof vi.fn>;

/**
 * 가짜 질문지 서버(id 1) + 로그인(가상 사람) + 창 store 의 open·close 엿보기. 창 w1 은 질문지 창이다.
 * onAnswer 는 답을 넣은 뒤 불린다(이어지는 질문을 더하거나 빼는 시험용).
 */
export function setup(over: Partial<FakeState> = {}, extra: Routes = {}, onAnswer?: (s: FakeState) => void) {
  signInAsDemo('admin');
  const state: FakeState = { questions: [...QUESTIONS], answers: {}, status: 'open', chat_session_id: null, ...over };
  const routes: Routes = {
    '/api/questionnaires/1': () => json(200, buildView(state)),
    'PATCH /api/questionnaires/1/answers': (init?: RequestInit) => {
      if (state.status === 'submitted') return json(409, { code: 'questionnaire_closed', message: '이미 제출한 질문지입니다.', detail: null });
      const { question_id, value } = JSON.parse(String(init?.body));
      if (value === null) delete state.answers[question_id];
      else state.answers[question_id] = String(value).trim();
      onAnswer?.(state);
      return json(200, buildView(state));
    },
    'POST /api/questionnaires/1/submit': () => {
      state.status = 'submitted';
      return json(200, { id: 1, status: 'submitted', answers: [], assumed: [] });
    },
    ...extra,
  };
  fetchMock = stubFetch(routes);
  openSpy = vi.fn(() => 'w9');
  closeSpy = vi.fn();
  useWindows.setState({
    open: openSpy,
    close: closeSpy,
    wins: [{ id: 'w1', programId: 'questionnaire', title: '질문지', x: 0, y: 48, w: 1180, h: 860, z: 1, minimized: false, maximized: false }],
  } as never);
  return state;
}

/** 이 경로·메서드로 간 요청들. */
export const callsTo = (url: string, method = 'GET') =>
  fetchMock.mock.calls.filter(([u, init]) => String(u) === url && (init?.method ?? 'GET') === method);

/** 답 PATCH 본문들(보낸 차례). */
export const patches = () => callsTo('/api/questionnaires/1/answers', 'PATCH').map(([, init]) => JSON.parse(String(init!.body)));
