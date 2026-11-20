import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeAll, beforeEach, describe, expect, test, vi } from 'vitest';
import { useCurrentSchedule } from '../../os/currentSchedule';
import { useChat } from './chatStore';
import { json } from '../../test-helpers';
import { callsTo, feed, lastBody, openSpy, registerFakePrograms, renderAt, routes, send, SESSION, setup, SID } from './testKit';

// 실제 서버가 내는 모양(Task 9·10·11). 사람·현장은 가상.
const APPROVAL = {
  id: 5,
  title: '5층 사무동 신축 일정',
  reasons: ['finish_changed', 'condition_violated'],
  summary: {
    finish: { before: '2027-11-24', after: '2027-11-28', delta_days: 4 },
    critical: { before_count: 7, after_count: 8, path_changed: true },
    conditions_changed: [{ id: 'in.resource_cap.crane', name: '타워크레인', before: '1대', after: '2대' }],
    changed_count: 4,
    check: { passed: 9, violations: [{ condition_id: 'in.finish_by', message: '준공이 기한보다 1일 늦습니다.', activity_ids: ['A9000'], amount: 1 }], uncheckable: 2, invalid: 0 },
    finish_float: { before: 5, after: 1 },
  },
};
const RESULT = {
  kind: 'generation_result',
  ok: true,
  draft_id: 12,
  finish: '2027-11-24',
  activity_count: 62,
  critical_count: 7,
  assumptions: [{ label: '콘크리트 양생', value: '7일', source: '가정' }],
  violations: [],
  uncheckable_count: 1,
  invalid_count: 0,
  conflict: [],
  reason: null,
};
const MINI = {
  kind: 'mini_questions',
  title: '두 가지만 확인할게요',
  questions: [
    { id: 'floors', group: '범위', question: '지상 몇 층인가요?', why: '골조 기간을 정합니다.', options: [{ value: '5', label: '5층', hint: null, recommended: true }, { value: '10', label: '10층', hint: null, recommended: false }], allow_free: true, assumption: '5층으로 가정합니다.' },
    { id: 'crane', group: '자원', question: '크레인은 몇 대인가요?', why: '', options: [], allow_free: true, assumption: '1대로 가정합니다.' },
  ],
};

beforeAll(() => registerFakePrograms());
beforeEach(() => {
  localStorage.clear();
  useCurrentSchedule.getState().setCurrent(null);
  setup();
});
afterEach(() => {
  useChat.getState().reset();
  vi.unstubAllGlobals();
});

describe('R2 · every card kind the backend sends', () => {
  beforeEach(() => void renderAt(1560));

  test('generation stages collapse into one live card', async () => {
    const r1 = [{ n: 1, activity_count: 40, violations: -1 }];
    feed([
      ['card', { kind: 'generation', stage: 'wbs', rounds: [] }],
      ['card', { kind: 'generation', stage: 'schedule', rounds: [] }],
      ['card', { kind: 'generation', stage: 'compute', rounds: r1 }],
      ['done', {}],
    ]);
    await send('공정표 만들어 줘');
    expect(screen.getAllByRole('region', { name: '일정 만들기' })).toHaveLength(1);
    expect(screen.getByText(/1회차 깨짐/)).toBeVisible();
    expect(screen.getByText('날짜 계산')).toHaveAttribute('aria-current', 'step');
  });

  test('result card: finish, counts, assumptions and unchecked conditions (never shown as passed)', async () => {
    feed([['card', RESULT], ['done', {}]]);
    await send('q');
    const card = screen.getByRole('region', { name: '결과' });
    expect(card).toHaveTextContent('준공 2027.11.24');
    expect(card).toHaveTextContent('액티비티 62개 · 크리티컬 7개');
    expect(card).toHaveTextContent('콘크리트 양생 7일');
    expect(card).toHaveTextContent('자동 점검 안 됨 1개');
    expect(card).not.toHaveTextContent('통과');
  });

  test('a result that did not meet the conditions says why', async () => {
    const violation = { condition_id: 'in.finish_by', message: '준공이 기한보다 3일 늦습니다.', activity_ids: ['A9000'], amount: 3 };
    feed([['card', { ...RESULT, ok: false, violations: [violation], conflict: ['in.finish_by'], reason: '조건을 모두 맞추지 못했습니다.' }], ['done', {}]]);
    await send('q');
    const card = screen.getByRole('region', { name: '결과' });
    expect(card).toHaveTextContent('조건을 모두 맞추지 못했습니다.');
    expect(card).toHaveTextContent('준공이 기한보다 3일 늦습니다.');
  });

  test('auto_applied card shows the version and the summary numbers', async () => {
    feed([['card', { kind: 'auto_applied', schedule_id: 1, version: 4, count: 2, summary: APPROVAL.summary }], ['done', {}]]);
    await send('q');
    const card = screen.getByRole('region', { name: '자동 적용' });
    expect(card).toHaveTextContent('자동으로 저장했습니다 · 버전 4 · 바뀐 액티비티 2개');
    expect(card).toHaveTextContent('2027.11.24 → 2027.11.28 (+4일)');
  });

  test('answers_filled card can open the questionnaire', async () => {
    feed([['card', { kind: 'answers_filled', questionnaire_id: 7, count: 2 }], ['done', {}]]);
    await send('10층이야');
    expect(screen.getByText('질문지 7에 답 2개를 채웠습니다.')).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: '질문지 열기' }));
    expect(openSpy).toHaveBeenCalledWith('questionnaire', { id: '7', session: String(SID) });
  });

  test('mini questions are answered in the chat as one message', async () => {
    feed([['card', MINI], ['done', {}]]);
    await send('공정표 만들어 줘');
    const card = screen.getByRole('region', { name: '두 가지만 확인할게요' });
    expect(within(card).getByText('권장')).toBeVisible();
    await userEvent.click(within(card).getByRole('button', { name: /10층/ }));
    expect(within(card).getByRole('button', { name: /10층/ })).toHaveAttribute('aria-pressed', 'true');
    feed([['text', { text: '알겠습니다.' }], ['done', {}]]);
    await userEvent.click(within(card).getByRole('button', { name: '답 보내기' }));
    expect(await screen.findByText('알겠습니다.')).toBeVisible();
    expect(lastBody().text).toBe('카드 질문에 답합니다.\n- 지상 몇 층인가요?: 10층\n- 크레인은 몇 대인가요?: 답하지 않음 (가정: 1대로 가정합니다.)');
    expect(within(card).getByRole('button', { name: '보냈습니다' })).toBeDisabled();
  });

  test('m9 · a typed answer equal to an option label stays typed', async () => {
    feed([['card', MINI], ['done', {}]]);
    await send('공정표 만들어 줘');
    const card = screen.getByRole('region', { name: '두 가지만 확인할게요' });
    const free = within(card).getByRole('textbox', { name: '지상 몇 층인가요? 직접 입력' });
    await userEvent.type(free, '10층');
    expect(free).toHaveValue('10층');
    expect(within(card).getByRole('button', { name: /10층/ })).toHaveAttribute('aria-pressed', 'false');
    await userEvent.click(within(card).getByRole('button', { name: /5층/ }));
    expect(free).toHaveValue('');
    expect(within(card).getByRole('button', { name: /5층/ })).toHaveAttribute('aria-pressed', 'true');
  });

  test('an unknown card kind renders a neutral one-line card and the thread keeps going', async () => {
    feed([['card', { kind: 'brand_new_kind', x: 1 }], ['text', { text: '계속합니다' }], ['done', {}]]);
    await send('q');
    expect(screen.getByText('이 화면에서 보일 수 없는 카드입니다 (brand_new_kind)')).toBeVisible();
    expect(screen.getByText('계속합니다')).toBeVisible();
  });

  test('long tool names and ids wrap instead of overflowing', async () => {
    const long = 'generate.extract_conditions_with_a_very_long_name_that_never_breaks_anywhere_at_all';
    feed([
      ['tool_start', { run_id: 1, n: 1, call_id: 'c1', tool: long, program: null, arguments: '{}' }],
      ['tool_end', { run_id: 1, n: 1, call_id: 'c1', tool: long, ok: false, ms: 12000, error: '없는 도구입니다' }],
      ['done', {}],
    ]);
    await send('q');
    await userEvent.click(screen.getByRole('button', { name: /도구 1개 · 12초/ }));
    expect(screen.getByText(long)).toHaveClass('ch-wrap');
    expect(screen.getByText('없는 도구입니다')).toBeVisible();
  });
});

describe('R5 · approvals and re-plan requests', () => {
  test('approval card: title, reasons as badges, numbers and a link to the inbox', async () => {
    renderAt(1560);
    feed([['approval', APPROVAL], ['done', {}]]);
    await send('저장해 줘');
    const card = screen.getByRole('region', { name: '승인 요청' });
    expect(card).toHaveTextContent('5층 사무동 신축 일정');
    expect(within(card).getByText('준공 변경')).toHaveClass('ui-badge');
    expect(within(card).getByText('조건 위반')).toHaveClass('ui-badge');
    expect(card).toHaveTextContent('2027.11.24 → 2027.11.28 (+4일)');
    expect(card).toHaveTextContent('7 → 8개 · 경로 바뀜');
    expect(card).toHaveTextContent('통과 9 · 위반 1 · 자동 점검 안 됨 2');
    expect(card).toHaveTextContent('타워크레인 1대 → 2대');
    await userEvent.click(within(card).getByRole('button', { name: '승인함에서 보기' }));
    expect(openSpy).toHaveBeenCalledWith('approvals', { id: '5' });
  });

  test('pending re-plan requests show who and why and start the retry with approval_id', async () => {
    routes['/api/chat/sessions'] = [{ ...SESSION, title: '공정표', pending_retries: 1 }];
    routes[`/api/chat/sessions/${SID}`] = {
      ...SESSION,
      title: '공정표',
      running: false,
      messages: [],
      pending_retries: [{ approval_id: 5, title: '5층 사무동 신축 일정', note: '준공은 그대로 두고 다시', decided_by_name: '이도윤', decided_at: '2026-11-20T02:00:00Z' }],
    };
    renderAt(1560, { session: String(SID) });
    const list = screen.getByRole('complementary', { name: '대화 목록' });
    expect(await within(list).findByText('다시 짜기 1')).toBeVisible();
    const card = await screen.findByRole('region', { name: '다시 짜기 요청' });
    expect(card).toHaveTextContent('이도윤님이 거부했습니다: 준공은 그대로 두고 다시');
    feed([['text', { text: '다시 짜겠습니다.' }], ['done', {}]]);
    await userEvent.click(within(card).getByRole('button', { name: '다시 짜기 시작' }));
    expect(await screen.findByText('다시 짜겠습니다.')).toBeVisible();
    expect(lastBody()).toMatchObject({ approval_id: 5 });
    expect(screen.queryByRole('region', { name: '다시 짜기 요청' })).toBeNull();
    expect(screen.getByText(/승인 거부 · 5층 사무동 신축 일정/)).toBeVisible();
  });

  test('m1 · a refused re-plan resume gives the 「다시 짜기 요청」 card back', async () => {
    const retry = { approval_id: 5, title: '5층 사무동 신축 일정', note: '준공은 그대로', decided_by_name: '이도윤', decided_at: '2026-11-20T02:00:00Z' };
    routes[`/api/chat/sessions/${SID}`] = { ...SESSION, running: false, messages: [], pending_retries: [retry] };
    routes[`POST /api/chat/sessions/${SID}/messages`] = () =>
      json(422, { code: 'invalid_approval', message: '이미 이어서 처리한 승인 건입니다.', detail: null });
    renderAt(480, { session: String(SID) });
    const card = await screen.findByRole('region', { name: '다시 짜기 요청' });
    await userEvent.click(within(card).getByRole('button', { name: '다시 짜기 시작' }));
    expect(await screen.findByText('이미 이어서 처리한 승인 건입니다.')).toBeVisible();
    expect(screen.getByRole('region', { name: '다시 짜기 요청' })).toBeVisible();
    expect(screen.queryByText(/승인 거부 ·/)).toBeNull();
  });

  test('m9 · a reopened approval card shows the decision made since', async () => {
    routes['/api/approvals/5'] = { id: 5, status: 'approved', decided_by: '이도윤', retry: false, decided_at: '2026-11-20T03:00:00Z' };
    routes[`/api/chat/sessions/${SID}`] = {
      ...SESSION, running: false, pending_retries: [],
      messages: [{ id: 1, role: 'event', content: { type: 'approval', data: APPROVAL }, created_at: 'x' }],
    };
    renderAt(1560, { session: String(SID) });
    const card = await screen.findByRole('region', { name: '승인 요청' });
    expect(await within(card).findByText('승인됨 · 이도윤')).toBeVisible();
    expect(card).not.toHaveTextContent('결정을 기다립니다');
  });

  test('params.resume_approval continues the chat (approvals inbox flow)', async () => {
    feed([['text', { text: '이유를 반영합니다.' }], ['done', {}]]);
    renderAt(480, { session: String(SID), resume_approval: '5' });
    expect(await screen.findByText('이유를 반영합니다.')).toBeVisible();
    expect(lastBody()).toMatchObject({ approval_id: 5 });
  });
});

test('m4 · broken answers in a stored questionnaire submission do not break the thread', async () => {
  routes[`/api/chat/sessions/${SID}`] = {
    ...SESSION, running: false, pending_retries: [],
    messages: [
      { id: 1, role: 'user', content: { kind: 'questionnaire_submitted', questionnaire_id: 9, answers: [null, 'x', { question: '지상 몇 층인가요?', label: '5층' }], assumed: [7] }, created_at: 'x' },
      { id: 2, role: 'assistant', content: { kind: 'text', text: '계속합니다.' }, created_at: 'x' },
    ],
  };
  renderAt(480, { session: String(SID) });
  expect(await screen.findByText('계속합니다.')).toBeVisible();
  expect(screen.getByText('질문지 9 제출 · 답 3개 · 가정 1개')).toBeVisible();
  expect(screen.getByText('지상 몇 층인가요?: 5층')).toBeInTheDocument();
});

describe('R3 · a reopened session shows the same cards', () => {
  test('persisted events, tool calls and system messages', async () => {
    routes[`/api/chat/sessions/${SID}`] = {
      ...SESSION,
      title: '공정표',
      running: false,
      pending_retries: [],
      messages: [
        { id: 1, role: 'user', content: { kind: 'text', text: '공정표 만들어 줘' }, created_at: 'x' },
        { id: 2, role: 'assistant', content: { kind: 'tool_calls', text: '만들겠습니다.', tool_calls: [{ id: 'c1', name: 'generate.run', arguments: {} }] }, created_at: 'x' },
        { id: 3, role: 'event', content: { type: 'card', data: { kind: 'generation', stage: 'check', rounds: [{ n: 1, activity_count: 40, violations: 2 }, { n: 2, activity_count: 41, violations: 0 }] } }, created_at: 'x' },
        { id: 4, role: 'event', content: { type: 'card', data: RESULT }, created_at: 'x' },
        { id: 5, role: 'tool', content: { kind: 'tool_result', tool_call_id: 'c1', name: 'generate.run', ok: true, content: '{}' }, created_at: 'x' },
        { id: 6, role: 'event', content: { type: 'approval', data: APPROVAL }, created_at: 'x' },
        { id: 7, role: 'event', content: { type: 'questionnaire', data: { id: 9 } }, created_at: 'x' },
        { id: 8, role: 'user', content: { kind: 'questionnaire_submitted', questionnaire_id: 9, answers: [{ question_id: 'floors', question: '지상 몇 층인가요?', value: '10', label: '10층' }], assumed: [{ question_id: 'crane', question: '크레인은 몇 대인가요?', assumption: '1대로 가정합니다.' }] }, created_at: 'x' },
        { id: 9, role: 'user', content: { kind: 'approval_rejected', approval_id: 5, title: '5층 사무동 신축 일정', note: '준공은 그대로' }, created_at: 'x' },
        { id: 10, role: 'assistant', content: { kind: 'text', text: '다시 냈습니다.' }, created_at: 'x' },
      ],
    };
    renderAt(1560, { session: String(SID) });
    expect(await screen.findByText(/1회차 위반 2 → 2회차 0/)).toBeVisible();
    expect(screen.getByRole('region', { name: '결과' })).toBeVisible();
    expect(screen.getByRole('region', { name: '승인 요청' })).toBeVisible();
    expect(screen.getByRole('button', { name: /도구 1개/ })).toBeVisible();
    expect(screen.getByText('질문지 9 제출 · 답 1개 · 가정 1개')).toBeVisible();
    expect(screen.getByText(/승인 거부 · 5층 사무동 신축 일정/)).toBeVisible();
    expect(screen.getByText('이유: 준공은 그대로')).toBeVisible();
    expect(screen.getByText('다시 냈습니다.')).toBeVisible();
    // 다시 연 대화의 질문지 카드도 같은 대화로 연다
    await userEvent.click(screen.getByRole('button', { name: '질문지 열기' }));
    expect(openSpy).toHaveBeenCalledWith('questionnaire', { id: '9', session: String(SID) });
    expect(callsTo(`/api/chat/sessions/${SID}`)).toHaveLength(1);
  });
});
