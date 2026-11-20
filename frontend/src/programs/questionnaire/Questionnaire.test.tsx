import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { StrictMode, Suspense } from 'react';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { useWindows } from '../../os/windowStore';
import { json } from '../../test-helpers';
import manifest from './index';
import Questionnaire from './Questionnaire';
import { buildView, callsTo, closeSpy, fetchMock, openSpy, patches, QUESTIONS, RETAINING_WALL, setup } from './testKit';

const PARAMS = { id: '1', session: '7' };

async function renderQ(params: Record<string, string> = PARAMS) {
  const view = render(<Questionnaire windowId="w1" params={params} />);
  await screen.findByRole('navigation', { name: '질문 목차' });
  return view;
}

const question = () => screen.getByRole('heading', { level: 2 });
const freeInput = () => screen.getByRole('textbox', { name: '직접 입력' });
const submitBtn = () => screen.getByRole('button', { name: /^제출하고 생성/ });
const nav = () => screen.getByRole('navigation', { name: '질문 목차' });
const options = () => screen.getByRole('group', { name: '선택지' });

async function goTo(questionText: string) {
  const target = QUESTIONS.find((q) => q.question === questionText)!;
  await userEvent.click(within(nav()).getByRole('button', { name: new RegExp(`^${target.group}`) }));
  while (question().textContent !== questionText) await userEvent.click(screen.getByRole('button', { name: '다음 질문' }));
}

beforeEach(() => localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

describe('지시서 시험(v2 로 맞춤)', () => {
  test('the progress line counts answered questions and the rest as assumptions', async () => {
    setup({ answers: { structure: 'rc', work_week: '6' } });
    await renderQ();
    expect(screen.getByText('질문 5개 중 2개 답함 · 나머지 3개는 가정으로')).toBeVisible();
    expect(screen.getByRole('progressbar', { name: '답한 질문' })).toHaveAttribute('aria-valuenow', '2');
  });

  test('choosing an option patches at once and re-renders from the returned view (a follow-up appears)', async () => {
    setup({}, {}, (s) => {
      const has = s.questions.some((q) => q.id === RETAINING_WALL.id);
      if (s.answers.basement === 'b1' && !has) s.questions.splice(2, 0, RETAINING_WALL);
    });
    await renderQ();
    await userEvent.click(within(nav()).getByRole('button', { name: /지하층이 있나요/ }));
    await userEvent.click(within(options()).getByRole('button', { name: /지하 1층/ }));
    expect(patches()).toEqual([{ question_id: 'basement', value: 'b1' }]);
    expect(await within(nav()).findByRole('button', { name: /흙막이는 어떤 방식인가요/ })).toBeVisible();
    expect(screen.getByText('질문 6개 중 1개 답함 · 나머지 5개는 가정으로')).toBeVisible();
    expect(within(options()).getByRole('button', { name: /지하 1층/ })).toHaveAttribute('aria-pressed', 'true');
  });

  test('free input is sent on Enter, not on every keystroke', async () => {
    setup();
    await renderQ();
    await goTo('토요일 작업은 어떻게 하나요?');
    await userEvent.type(freeInput(), '격주 토요일만 작업');
    expect(patches()).toEqual([]);
    await userEvent.keyboard('{Enter}');
    await waitFor(() => expect(patches()).toEqual([{ question_id: 'holiday_rule', value: '격주 토요일만 작업' }]));
    await userEvent.tab(); // 같은 글로 칸을 나가도 다시 보내지 않는다
    expect(patches()).toHaveLength(1);
  });

  test('[가정대로 두기] clears the answer with null', async () => {
    setup({ answers: { structure: 'steel' } });
    await renderQ();
    await userEvent.click(within(nav()).getByRole('button', { name: /건물의 구조 형식/ }));
    await userEvent.click(screen.getByRole('button', { name: '가정대로 두기' }));
    await waitFor(() => expect(patches()).toEqual([{ question_id: 'structure', value: null }]));
    expect(await screen.findByText('질문 5개 중 0개 답함 · 나머지 5개는 가정으로')).toBeVisible();
  });

  test('submit is always enabled and its label counts answers and assumptions', async () => {
    setup({ answers: { structure: 'rc' } });
    await renderQ();
    expect(screen.getByRole('button', { name: '제출하고 생성 (답 1개 · 가정 4개)' })).toBeEnabled();
  });

  test('filled items show their source, and [고치기] goes to that question', async () => {
    setup({ answers: { structure: 'rc' } });
    await renderQ();
    const filled = screen.getByRole('region', { name: '이미 채운 것' });
    expect(within(filled).getByText('프롬프트')).toBeVisible();
    expect(within(filled).getByText('고치려면 대화로 말해 주세요')).toBeVisible();
    expect(within(filled).getByText('철근콘크리트')).toBeVisible();
    await userEvent.click(within(filled).getAllByRole('button', { name: '고치기' })[0]);
    expect(question()).toHaveTextContent('건물의 구조 형식은 무엇인가요?');
    expect(freeInput()).toHaveFocus();
  });

  test('submit resumes the chat on the same session, closes this window and brings the chat forward', async () => {
    setup();
    await renderQ();
    await userEvent.click(submitBtn());
    await waitFor(() => expect(closeSpy).toHaveBeenCalledWith('w1'));
    expect(callsTo('/api/questionnaires/1/submit', 'POST')).toHaveLength(1);
    expect(openSpy).toHaveBeenCalledWith('chat', { session: '7', resume_questionnaire: '1' });
  });
});

describe('R1 · R4 한 질문씩', () => {
  test('the question shows why it is asked, the recommended mark, hints and the assumption', async () => {
    setup();
    await renderQ();
    expect(question()).toHaveTextContent('건물의 구조 형식은 무엇인가요?');
    expect(screen.getByText('층당 골조 기간이 구조 형식에 따라 달라집니다.')).toBeVisible();
    const rc = within(options()).getByRole('button', { name: /철근콘크리트/ });
    expect(within(rc).getByText('추천')).toBeVisible();
    expect(within(rc).getByText('중층 사무동에 가장 흔합니다.')).toBeVisible();
    expect(screen.getByText('답하지 않으면: 철근콘크리트 구조로 가정합니다.')).toBeVisible();
    expect(screen.getByText('범위 · 1번째 질문 (2개 중)')).toBeVisible();
  });

  test('no free input when the question does not take one', async () => {
    setup();
    await renderQ();
    await goTo('주 며칠 일하나요?');
    expect(screen.queryByRole('textbox', { name: '직접 입력' })).toBeNull();
  });

  test('free input is also sent when leaving the field', async () => {
    setup();
    await renderQ();
    await goTo('토요일 작업은 어떻게 하나요?');
    await userEvent.type(freeInput(), '  매주 오전만  ');
    await userEvent.tab();
    await waitFor(() => expect(patches()).toEqual([{ question_id: 'holiday_rule', value: '매주 오전만' }]));
  });

  test('Enter while composing Korean does not send', async () => {
    setup();
    await renderQ();
    await goTo('토요일 작업은 어떻게 하나요?');
    fireEvent.change(freeInput(), { target: { value: '격주' } });
    fireEvent.keyDown(freeInput(), { key: 'Enter', isComposing: true });
    await act(() => new Promise((r) => setTimeout(r, 30))); // 보냈다면 이 사이에 PATCH 가 나간다
    expect(patches()).toEqual([]);
    fireEvent.keyDown(freeInput(), { key: 'Enter' });
    await waitFor(() => expect(patches()).toEqual([{ question_id: 'holiday_rule', value: '격주' }]));
  });

  test('date options are shown and sent as written', async () => {
    setup();
    await renderQ();
    await goTo('착공일은 언제인가요?');
    await userEvent.click(within(options()).getByRole('button', { name: '2027-04-01 (목) 착공' }));
    await waitFor(() => expect(patches()).toEqual([{ question_id: 'start_date', value: '2027-04-01' }]));
  });

  test('a rejected answer shows the server message', async () => {
    setup({}, {
      'PATCH /api/questionnaires/1/answers': () => json(422, { code: 'invalid_answer', message: '답은 1~500자로 적어 주세요.', detail: null }),
    });
    await renderQ();
    await userEvent.click(within(options()).getByRole('button', { name: /철골/ }));
    expect(await screen.findByRole('alert')).toHaveTextContent('답은 1~500자로 적어 주세요.');
  });

  test('answers are sent one after another, never two at once', async () => {
    let release!: () => void;
    const first = new Promise<void>((r) => (release = r));
    let calls = 0;
    const state = setup({}, {
      'PATCH /api/questionnaires/1/answers': async (init?: RequestInit) => {
        calls += 1;
        const { question_id, value } = JSON.parse(String(init?.body));
        if (calls === 1) await first;
        state.answers[question_id] = value;
        return json(200, buildView(state));
      },
    });
    await renderQ();
    await userEvent.click(within(options()).getByRole('button', { name: /철골/ }));
    await userEvent.click(within(options()).getByRole('button', { name: /철근콘크리트/ }));
    expect(calls).toBe(1);
    await act(async () => release());
    await waitFor(() => expect(calls).toBe(2));
    expect(patches().map((p) => p.value)).toEqual(['steel', 'rc']);
  });
});

describe('R1 목차 · 이동', () => {
  test('groups are green when all answered and grey while questions remain', async () => {
    setup({ answers: { structure: 'rc', basement: 'none' } });
    await renderQ();
    expect(within(nav()).getByRole('button', { name: /^범위 · 모두 답함 · 2 \/ 2/ })).toHaveAttribute('data-state', 'done');
    expect(within(nav()).getByRole('button', { name: /^날짜 · 남은 질문 있음 · 0 \/ 1/ })).toHaveAttribute('data-state', 'open');
  });

  test('[이전]·[다음 질문] walk every question across groups; a group opens at its first unanswered question', async () => {
    setup({ answers: { work_week: '6' } });
    await renderQ();
    expect(screen.getByRole('button', { name: '이전' })).toBeDisabled();
    const seen = [question().textContent];
    for (let i = 0; i < 4; i++) {
      await userEvent.click(screen.getByRole('button', { name: '다음 질문' }));
      seen.push(question().textContent);
    }
    expect(seen).toEqual(QUESTIONS.map((q) => q.question));
    expect(screen.getByRole('button', { name: '다음 질문' })).toBeDisabled();
    await userEvent.click(within(nav()).getByRole('button', { name: /^달력/ }));
    expect(question()).toHaveTextContent('토요일 작업은 어떻게 하나요?');
  });

  test('the window title carries the questionnaire title', async () => {
    setup();
    await renderQ();
    await waitFor(() => expect(useWindows.getState().wins[0].title).toBe('질문지 — 5층 사무동 신축 일정 질문지'));
  });

  test('a new id in the params loads that questionnaire', async () => {
    setup({}, { '/api/questionnaires/2': () => json(404, { code: 'not_found', message: '질문지를 찾을 수 없습니다.', detail: null }) });
    const view = await renderQ();
    await waitFor(() => expect(useWindows.getState().wins[0].title).toBe('질문지 — 5층 사무동 신축 일정 질문지'));
    view.rerender(<Questionnaire windowId="w1" params={{ id: '2' }} />);
    expect(await screen.findByText('질문지를 찾을 수 없습니다.')).toBeVisible();
    expect(useWindows.getState().wins[0].title).toBe('질문지');
  });
});

describe('R3 · R10 대화로 · 제출', () => {
  test('[대화로 답하기] brings the chat forward on the same session', async () => {
    setup();
    await renderQ();
    await userEvent.click(screen.getByRole('button', { name: '대화로 답하기' }));
    expect(openSpy).toHaveBeenCalledWith('chat', { session: '7' });
  });

  test('without a session anywhere, [대화로 답하기] just brings the chat forward', async () => {
    setup();
    await renderQ({ id: '1' });
    await userEvent.click(screen.getByRole('button', { name: '대화로 답하기' }));
    expect(openSpy).toHaveBeenCalledWith('chat', undefined);
  });

  test('opened without a session, submit resumes the chat the questionnaire came from', async () => {
    setup({ chat_session_id: 42 });
    await renderQ({ id: '1' });
    await userEvent.click(submitBtn());
    await waitFor(() => expect(openSpy).toHaveBeenCalledWith('chat', { session: '42', resume_questionnaire: '1' }));
    expect(closeSpy).toHaveBeenCalledWith('w1');
  });

  test('with no chat to resume, submit stays here and says so', async () => {
    setup({ answers: { structure: 'rc' } });
    await renderQ({ id: '1' });
    await userEvent.click(submitBtn());
    expect(await screen.findByText('제출했습니다. 대화창에서 이어서 요청해 주세요.')).toBeVisible();
    expect(screen.getByText('제출됨')).toBeVisible();
    expect(openSpy).not.toHaveBeenCalled();
    expect(closeSpy).not.toHaveBeenCalled();
  });

  test('a free answer typed just before submit is saved first', async () => {
    setup();
    await renderQ();
    await goTo('토요일 작업은 어떻게 하나요?');
    await userEvent.type(freeInput(), '격주');
    await userEvent.click(submitBtn());
    await waitFor(() => expect(closeSpy).toHaveBeenCalled());
    expect(writes()).toEqual(['PATCH /api/questionnaires/1/answers', 'POST /api/questionnaires/1/submit']);
    expect(patches()).toEqual([{ question_id: 'holiday_rule', value: '격주' }]);
  });
});

describe('R5 제출됨 · 없음', () => {
  test('a submitted questionnaire is read-only with the answer and assumption summary', async () => {
    setup({ status: 'submitted', answers: { structure: 'rc', start_date: '2027-03-02' } });
    render(<Questionnaire windowId="w1" params={PARAMS} />);
    expect(await screen.findByText('제출됨')).toBeVisible();
    expect(screen.getByText('답 2개 · 가정 3개')).toBeVisible();
    const answers = screen.getByRole('region', { name: '답한 것' });
    expect(within(answers).getByText('2027-03-02 (화) 착공')).toBeVisible();
    const assumed = screen.getByRole('region', { name: '가정으로 둔 것' });
    expect(within(assumed).getByText('주 6일로 가정합니다.')).toBeVisible();
    expect(screen.queryByRole('button', { name: /^제출하고 생성/ })).toBeNull();
    expect(screen.queryByRole('textbox')).toBeNull();
  });

  test('409 on an answer turns the screen read-only', async () => {
    const state = setup();
    await renderQ();
    state.status = 'submitted'; // 다른 곳에서 제출됨
    await userEvent.click(within(options()).getByRole('button', { name: /철골/ }));
    expect(await screen.findByText('제출됨')).toBeVisible();
    expect(screen.queryByRole('navigation', { name: '질문 목차' })).toBeNull();
  });

  test('404 says the questionnaire is not found inside the window', async () => {
    setup({}, { '/api/questionnaires/1': () => json(404, { code: 'not_found', message: '질문지를 찾을 수 없습니다.', detail: null }) });
    render(<Questionnaire windowId="w1" params={PARAMS} />);
    expect(await screen.findByText('질문지를 찾을 수 없습니다.')).toBeVisible();
  });
});

describe('R6 프로그램', () => {
  test('the manifest opens this screen at 1180×860', async () => {
    setup();
    expect(manifest.defaultSize).toEqual({ w: 1180, h: 860 });
    const Screen = manifest.component;
    render(
      <StrictMode>
        <Suspense fallback={null}>
          <Screen windowId="w1" params={PARAMS} />
        </Suspense>
      </StrictMode>,
    );
    expect(await screen.findByRole('navigation', { name: '질문 목차' })).toBeVisible();
  });
});

/** GET 을 뺀 요청들(보낸 차례). */
function writes(): string[] {
  return fetchMock.mock.calls.map(([u, init]) => `${init?.method ?? 'GET'} ${String(u)}`).filter((x) => !x.startsWith('GET'));
}
