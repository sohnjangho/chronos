import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest';
import { registerPrograms } from '../programs';
import { json, signInAsDemo, stubFetch } from '../test-helpers';
import { useAiChat } from './aiChat';
import { useContextPanel } from './contextStore';
import { useCurrentSchedule } from './currentSchedule';
import Desktop from './Desktop';
import { useEvidence } from './evidence';
import { useSession } from './session';
import { useUiContext } from './uiContext';
import { useWindows } from './windowStore';
import { resetShellState } from './shellReset';

const panel = () => screen.getByRole('complementary', { name: 'Context 패널' });
const tab = (name: RegExp | string) => within(panel()).getByRole('tab', { name });
const openProgram = (id: string, params?: Record<string, string>) => act(() => void useWindows.getState().open(id, params));
const sse = (text: string) =>
  new Response(
    new ReadableStream<Uint8Array>({
      start(c) {
        c.enqueue(new TextEncoder().encode(text));
        c.close();
      },
    }),
    { status: 200 },
  );

const view = {
  id: 4,
  name: '5층 사무동 신축',
  level: 'L3',
  version: 3,
  data_date: '2027-06-01',
  finish: '2027-11-24',
  plan_finish: '2027-11-30',
  summary: { critical_count: 7, negative_float_count: 0, warning_count: 2 },
  activities: [],
};

let fetchMock: ReturnType<typeof stubFetch>;
beforeAll(() => registerPrograms());
beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal('innerWidth', 1920);
  vi.stubGlobal('innerHeight', 1080);
  signInAsDemo('admin');
  useCurrentSchedule.getState().setCurrent({ id: 4, name: '5층 사무동 신축' });
  fetchMock = stubFetch({
    '/api/approvals/count': { pending: 1 },
    '/api/schedules': [{ id: 4, name: '5층 사무동 신축', level: 'L3' }],
    '/api/schedules/4': view,
    '/api/approvals?status=pending': {
      mode: 'important',
      items: [
        { id: 11, title: '만회 계획', created_at: new Date().toISOString(), schedule_id: 4 },
        { id: 12, title: '다른 현장 건', created_at: new Date().toISOString(), schedule_id: 7 },
      ],
    },
    '/api/chat/sessions': [
      { id: 9, title: '', schedule_id: 4, created_at: 'x' },
      { id: 10, title: '', schedule_id: 7, created_at: 'x' },
    ],
    '/api/workflows/runs': [
      { id: 1, chat_session_id: 9, title: '일정 생성', status: 'done', started_at: new Date().toISOString(), ended_at: null },
      { id: 2, chat_session_id: 10, title: '다른 현장 실행', status: 'done', started_at: new Date().toISOString(), ended_at: null },
    ],
    'POST /api/chat/sessions': () => json(200, { id: 9, title: '', schedule_id: 4, created_at: 'x' }),
    'POST /api/chat/sessions/9/messages': () => sse('event: text\ndata: {"text":"요약입니다"}\n\nevent: done\ndata: {}\n\n'),
  });
});
afterEach(() => {
  resetShellState();
  vi.unstubAllGlobals();
  useWindows.getState().reset();
  useContextPanel.getState().reset();
  useAiChat.getState().reset();
  useEvidence.setState({ byWindow: {} });
  useCurrentSchedule.getState().setCurrent(null);
  useSession.getState().logout();
});

test('the round button and Ctrl+Alt+. toggle a 420px panel that narrows the window area', async () => {
  render(<Desktop />);
  openProgram('schedule-table');
  await userEvent.click(screen.getByRole('button', { name: 'Context 패널 열기 (Ctrl+Alt+.)' }));
  expect(panel()).toHaveStyle({ width: '420px' });
  expect(useWindows.getState().insetRight).toBe(420);
  fireEvent.keyDown(document.body, { code: 'Period', key: '.', ctrlKey: true, altKey: true });
  expect(screen.queryByRole('complementary', { name: 'Context 패널' })).toBeNull();
  expect(useWindows.getState().insetRight).toBe(0);
  expect(screen.getByRole('dialog', { name: '스케줄' })).toHaveFocus();
});

test('the header names the source window, follows the active window and marks a closed one', async () => {
  render(<Desktop />);
  openProgram('schedule-table');
  act(() => useContextPanel.getState().toggle());
  expect(within(panel()).getByRole('button', { name: '출처: 스케줄' })).toBeEnabled();
  openProgram('chat');
  const source = within(panel()).getByRole('button', { name: '출처: 에이전트 대화' });
  act(() => useWindows.getState().focus(useWindows.getState().wins[0].id));
  await userEvent.click(within(panel()).getByRole('button', { name: '출처: 스케줄' }));
  expect(useWindows.getState().activeProgramId()).toBe('schedule-table');
  act(() => useWindows.getState().close(useWindows.getState().wins.find((w) => w.programId === 'schedule-table')!.id));
  expect(source).not.toBeInTheDocument();
  expect(within(panel()).queryByRole('button', { name: /^출처:/ })).toBeNull();
  expect(within(panel()).getByText('닫힌 창: 스케줄')).toBeInTheDocument();
  expect(panel().querySelector('.os-ctx-body')).toHaveClass('is-stale');
});

// 화면 맥락은 창 params 가 아니라 창이 알린 uiContext 에서 온다(Task 16 fix 1).
// 스케줄 창이 먼저 제 맥락(고른 것 없음)을 알린 뒤에 고른 것을 알린다 — 늦게 그려진 창이 시험이 알린 것을 덮지 않게.
async function publishSelected(activity: string) {
  const id = useWindows.getState().wins.find((w) => w.programId === 'schedule-table')!.id;
  await waitFor(() => expect(useUiContext.getState().byWindow[id]).toBeDefined());
  act(() => useUiContext.getState().publish(id, { program: 'schedule-table', schedule_id: 4, selected_activity: activity }));
}

test('the AI tab talks with the source context and can continue in the chat program', async () => {
  render(<Desktop />);
  openProgram('schedule-table');
  act(() => useContextPanel.getState().toggle());
  await publishSelected('A1020');
  await userEvent.type(within(panel()).getByRole('textbox', { name: '에이전트에게 묻기' }), '요약해 줘{Enter}');
  expect(await within(panel()).findByText('요약입니다')).toBeVisible();
  expect(within(panel()).getByText('요약해 줘')).toBeVisible();
  const create = fetchMock.mock.calls.find(([u, i]) => u === '/api/chat/sessions' && i?.method === 'POST')!;
  expect(JSON.parse(String(create[1]?.body))).toEqual({ schedule_id: 4 });
  const send = fetchMock.mock.calls.find(([u]) => u === '/api/chat/sessions/9/messages')!;
  expect(JSON.parse(String(send[1]?.body))).toEqual({ text: '요약해 줘', ui: { program: 'schedule-table', schedule_id: 4, selected_activity: 'A1020' } });
  await userEvent.click(within(panel()).getByRole('button', { name: '전체 화면으로' }));
  const chat = useWindows.getState().wins.find((w) => w.programId === 'chat')!;
  expect(chat).toMatchObject({ params: { session: '9' }, maximized: true });
});

test('the 근거 tab shows the schedule summary for schedule windows and an empty text otherwise', async () => {
  render(<Desktop />);
  openProgram('schedule-table');
  act(() => useContextPanel.getState().toggle());
  await userEvent.click(tab(/^근거/));
  expect(await within(panel()).findByText('크리티컬 액티비티')).toBeVisible();
  expect(within(panel()).getByText('7개')).toBeVisible();
  expect(tab(/^근거/)).toHaveTextContent('6');
  openProgram('chat');
  expect(within(panel()).getByText('이 창이 넘긴 근거가 없습니다.')).toBeVisible();
  act(() => useEvidence.getState().setEvidence(useWindows.getState().wins[1].id, [{ label: '참고 대화', value: '3건' }]));
  expect(within(panel()).getByText('참고 대화')).toBeVisible();
  expect(tab(/^근거/)).toHaveTextContent('1');
});

test('the 활동 tab lists pending approvals and recent runs of the current schedule only', async () => {
  render(<Desktop />);
  openProgram('schedule-table');
  act(() => useContextPanel.getState().toggle());
  await userEvent.click(tab('활동'));
  expect(await within(panel()).findByText('만회 계획')).toBeVisible();
  expect(await within(panel()).findByText('일정 생성')).toBeVisible();
  expect(within(panel()).queryByText('다른 현장 건')).toBeNull();
  expect(within(panel()).queryByText('다른 현장 실행')).toBeNull();
  await userEvent.click(within(panel()).getByRole('button', { name: /만회 계획/ }));
  expect(useWindows.getState().wins.find((w) => w.programId === 'approvals')?.params).toEqual({ id: '11' });
});

test('changing the current schedule clears the AI conversation', async () => {
  render(<Desktop />);
  openProgram('schedule-table');
  act(() => useContextPanel.getState().toggle());
  await userEvent.type(within(panel()).getByRole('textbox', { name: '에이전트에게 묻기' }), '요약해 줘{Enter}');
  await within(panel()).findByText('요약입니다');
  act(() => useCurrentSchedule.getState().setCurrent({ id: 5, name: '물류센터' }));
  expect(within(panel()).queryByText('요약입니다')).toBeNull();
});

test('dragging the left edge resizes the panel within limits', () => {
  render(<Desktop />);
  act(() => useContextPanel.getState().toggle());
  const edge = within(panel()).getByRole('separator', { name: '패널 폭 조절' });
  fireEvent.pointerDown(edge, { clientX: 1500 });
  fireEvent.pointerMove(window, { clientX: 1400, buttons: 1 });
  fireEvent.pointerUp(window);
  expect(panel()).toHaveStyle({ width: '520px' });
  expect(useWindows.getState().insetRight).toBe(520);
  fireEvent.pointerDown(edge, { clientX: 1400 });
  fireEvent.pointerMove(window, { clientX: 1900, buttons: 1 });
  fireEvent.pointerUp(window);
  expect(panel()).toHaveStyle({ width: '320px' });
});

/** 손으로 흘려 보내는 SSE 응답. push 로 조각을, end 로 끝을 보낸다. */
function liveStream() {
  const enc = new TextEncoder();
  let ctrl!: ReadableStreamDefaultController<Uint8Array>;
  const cancel = vi.fn();
  const response = new Response(new ReadableStream<Uint8Array>({ start: (c) => void (ctrl = c), cancel }), { status: 200 });
  return { response, cancel, push: (t: string) => ctrl.enqueue(enc.encode(t)), end: () => ctrl.close() };
}

test('switching tabs mid-reply keeps the conversation and the reply still arrives', async () => {
  const live = liveStream();
  stubFetch({
    '/api/approvals/count': { pending: 0 },
    '/api/schedules': [{ id: 4, name: '5층 사무동 신축', level: 'L3' }],
    '/api/schedules/4': view,
    'POST /api/chat/sessions': () => json(200, { id: 9, title: '', schedule_id: 4, created_at: 'x' }),
    'POST /api/chat/sessions/9/messages': () => live.response,
  });
  render(<Desktop />);
  openProgram('schedule-table');
  act(() => useContextPanel.getState().toggle());
  await userEvent.type(within(panel()).getByRole('textbox', { name: '에이전트에게 묻기' }), '요약해 줘{Enter}');
  await userEvent.click(tab(/^근거/));
  await act(async () => {
    live.push('event: text\ndata: {"text":"늦게 온 답"}\n\n');
    live.end();
  });
  await userEvent.click(tab('AI'));
  expect(await within(panel()).findByText('늦게 온 답')).toBeVisible();
  expect(live.cancel).not.toHaveBeenCalled();
});

test('closing and reopening the panel keeps the same conversation and session', async () => {
  render(<Desktop />);
  openProgram('schedule-table');
  act(() => useContextPanel.getState().toggle());
  await userEvent.type(within(panel()).getByRole('textbox', { name: '에이전트에게 묻기' }), '첫 질문{Enter}');
  await within(panel()).findByText('요약입니다');
  act(() => useContextPanel.getState().toggle());
  act(() => useContextPanel.getState().toggle());
  expect(within(panel()).getByText('첫 질문')).toBeVisible();
  await userEvent.type(within(panel()).getByRole('textbox', { name: '에이전트에게 묻기' }), '둘째 질문{Enter}');
  await within(panel()).findAllByText('요약입니다');
  const creates = fetchMock.mock.calls.filter(([u, i]) => u === '/api/chat/sessions' && i?.method === 'POST');
  expect(creates).toHaveLength(1);
  expect(fetchMock.mock.calls.filter(([u]) => u === '/api/chat/sessions/9/messages')).toHaveLength(2);
});

test('the AI tab sends the published context as it is when sending, not as it was', async () => {
  render(<Desktop />);
  openProgram('schedule-table');
  act(() => useContextPanel.getState().toggle());
  await publishSelected('A1020');
  await publishSelected('A1030');
  await userEvent.type(within(panel()).getByRole('textbox', { name: '에이전트에게 묻기' }), '이것은?{Enter}');
  await within(panel()).findByText('요약입니다');
  const send = fetchMock.mock.calls.find(([u]) => u === '/api/chat/sessions/9/messages')!;
  expect(JSON.parse(String(send[1]?.body)).ui.selected_activity).toBe('A1030');
});

test('changing the schedule stops a running reply', async () => {
  const live = liveStream();
  const calls = stubFetch({
    '/api/approvals/count': { pending: 0 },
    '/api/schedules': [{ id: 4, name: '5층 사무동 신축', level: 'L3' }],
    '/api/schedules/4': view,
    'POST /api/chat/sessions': () => json(200, { id: 9, title: '', schedule_id: 4, created_at: 'x' }),
    'POST /api/chat/sessions/9/messages': () => live.response,
  });
  render(<Desktop />);
  openProgram('schedule-table');
  act(() => useContextPanel.getState().toggle());
  await userEvent.type(within(panel()).getByRole('textbox', { name: '에이전트에게 묻기' }), '요약해 줘{Enter}');
  await vi.waitFor(() => expect(calls.mock.calls.some(([u]) => u === '/api/chat/sessions/9/messages')).toBe(true));
  act(() => useCurrentSchedule.getState().setCurrent({ id: 5, name: '물류센터' }));
  await vi.waitFor(() => expect(live.cancel).toHaveBeenCalled());
  expect(within(panel()).queryByText('요약해 줘')).toBeNull();
});

test('the round button hides with the Dock while a window is maximized', () => {
  render(<Desktop />);
  openProgram('schedule-table');
  // hidden 이면 접근성 이름이 비어 역할로 찾을 수 없다(그래서 class 로 본다).
  const button = () => document.querySelector<HTMLButtonElement>('.os-ctx-open')!;
  expect(screen.getByRole('button', { name: 'Context 패널 열기 (Ctrl+Alt+.)' })).toBe(button());
  expect(button()).toBeVisible();
  act(() => useWindows.getState().toggleMaximize(useWindows.getState().wins[0].id));
  expect(button()).not.toBeVisible();
  fireEvent.keyDown(document.body, { code: 'KeyD', key: 'd', ctrlKey: true, altKey: true });
  expect(button()).toBeVisible();
});

test('windows narrowed by the panel get their width back when it closes, unless resized meanwhile', () => {
  render(<Desktop />);
  openProgram('schedule-table');
  openProgram('chat');
  const win = (p: string) => useWindows.getState().wins.find((w) => w.programId === p)!;
  const chatBefore = { ...win('chat') };
  act(() => useContextPanel.getState().toggle());
  expect(win('chat').x + win('chat').w).toBeLessThanOrEqual(1500);
  expect(win('schedule-table').x + win('schedule-table').w).toBeLessThanOrEqual(1500);
  act(() => useWindows.getState().resize(win('schedule-table').id, 900, 600));
  act(() => useContextPanel.getState().toggle());
  expect(win('chat')).toMatchObject({ x: chatBefore.x, w: chatBefore.w });
  expect(win('schedule-table').w).toBe(900);
});
