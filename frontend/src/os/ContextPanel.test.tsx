import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest';
import { registerPrograms } from '../programs';
import { json, signInAs, stubFetch } from '../test-helpers';
import { useContextPanel } from './contextStore';
import { useCurrentSchedule } from './currentSchedule';
import Desktop from './Desktop';
import { useEvidence } from './evidence';
import { useSession } from './session';
import { useWindows } from './windowStore';

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
  signInAs('admin');
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
  vi.unstubAllGlobals();
  useWindows.getState().reset();
  useContextPanel.getState().reset();
  useEvidence.setState({ byWindow: {} });
  useCurrentSchedule.getState().setCurrent(null);
  useSession.getState().logout();
});

test('the round button and Ctrl+Alt+. toggle a 420px panel that narrows the window area', async () => {
  render(<Desktop />);
  openProgram('schedule');
  await userEvent.click(screen.getByRole('button', { name: 'Context 패널 열기 (Ctrl+Alt+.)' }));
  expect(panel()).toHaveStyle({ width: '420px' });
  expect(useWindows.getState().insetRight).toBe(420);
  fireEvent.keyDown(document.body, { code: 'Period', key: '.', ctrlKey: true, altKey: true });
  expect(screen.queryByRole('complementary', { name: 'Context 패널' })).toBeNull();
  expect(useWindows.getState().insetRight).toBe(0);
  expect(screen.getByRole('dialog', { name: '일정판' })).toHaveFocus();
});

test('the header names the source window, follows the active window and marks a closed one', async () => {
  render(<Desktop />);
  openProgram('schedule');
  act(() => useContextPanel.getState().toggle());
  expect(within(panel()).getByRole('button', { name: '출처: 일정판' })).toBeEnabled();
  openProgram('chat');
  const source = within(panel()).getByRole('button', { name: '출처: 에이전트 대화' });
  act(() => useWindows.getState().focus(useWindows.getState().wins[0].id));
  await userEvent.click(within(panel()).getByRole('button', { name: '출처: 일정판' }));
  expect(useWindows.getState().activeProgramId()).toBe('schedule');
  act(() => useWindows.getState().close(useWindows.getState().wins.find((w) => w.programId === 'schedule')!.id));
  expect(source).toBeDefined();
  expect(within(panel()).getByText('닫힌 창: 일정판')).toBeInTheDocument();
  expect(panel().querySelector('.os-ctx-body')).toHaveClass('is-stale');
});

test('the AI tab talks with the source context and can continue in the chat program', async () => {
  render(<Desktop />);
  openProgram('schedule', { activity: 'A1020' });
  act(() => useContextPanel.getState().toggle());
  await userEvent.type(within(panel()).getByRole('textbox', { name: '에이전트에게 묻기' }), '요약해 줘{Enter}');
  expect(await within(panel()).findByText('요약입니다')).toBeVisible();
  expect(within(panel()).getByText('요약해 줘')).toBeVisible();
  const create = fetchMock.mock.calls.find(([u, i]) => u === '/api/chat/sessions' && i?.method === 'POST')!;
  expect(JSON.parse(String(create[1]?.body))).toEqual({ schedule_id: 4 });
  const send = fetchMock.mock.calls.find(([u]) => u === '/api/chat/sessions/9/messages')!;
  expect(JSON.parse(String(send[1]?.body))).toEqual({ text: '요약해 줘', ui: { program: 'schedule', schedule_id: 4, selected_activity: 'A1020' } });
  await userEvent.click(within(panel()).getByRole('button', { name: '전체 화면으로' }));
  const chat = useWindows.getState().wins.find((w) => w.programId === 'chat')!;
  expect(chat).toMatchObject({ params: { session: '9' }, maximized: true });
});

test('the 근거 tab shows the schedule summary for schedule windows and an empty text otherwise', async () => {
  render(<Desktop />);
  openProgram('schedule');
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
  openProgram('schedule');
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
  openProgram('schedule');
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
