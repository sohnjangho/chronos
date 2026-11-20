import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { json, signInAsDemo } from '../test-helpers';
import { useAiChat } from './aiChat';
import { useUiContext } from './uiContext';
import { useWindows, type Win } from './windowStore';

// Context 패널 AI 탭의 ui 는 창 params 가 아니라 OS 화면 맥락(uiContext)에서 온다(Task 16 fix 1, 컨트롤러 판단).
const win = (id: string, programId: string, z: number, params?: Record<string, string>): Win => ({
  id, programId, title: programId, x: 0, y: 48, w: 800, h: 600, z, minimized: false, maximized: false, params,
});
const done = () => new Response('event: done\ndata: {}\n\n', { status: 200 });
let sent: unknown[] = [];

beforeEach(() => {
  signInAsDemo('admin');
  sent = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/chat/sessions') return json(200, { id: 9 });
      sent.push(JSON.parse(String(init?.body)).ui);
      return done();
    }),
  );
  useAiChat.getState().reset();
  useAiChat.getState().bindSchedule(4);
});
afterEach(() => {
  useUiContext.getState().reset();
  useWindows.getState().reset();
  vi.unstubAllGlobals();
});

test('the source window context comes from what it published, not from its params', async () => {
  useWindows.setState({ wins: [win('w1', 'schedule', 1, { activity: 'A9999' })] } as never);
  useUiContext.getState().publish('w1', { program: 'schedule', schedule_id: 4, selected_activity: 'A2020' });
  await useAiChat.getState().ask('이거 당겨 줘', { id: 'w1', programId: 'schedule', title: '일정판', params: { activity: 'A9999' } });
  expect(sent).toEqual([{ program: 'schedule', schedule_id: 4, selected_activity: 'A2020' }]);
});

test('it is read when sending, so a later selection is sent', async () => {
  useWindows.setState({ wins: [win('w1', 'schedule', 1)] } as never);
  useUiContext.getState().publish('w1', { program: 'schedule', schedule_id: 4, selected_activity: 'A1020' });
  useUiContext.getState().publish('w1', { program: 'schedule', schedule_id: 4, selected_activity: 'A1030' });
  await useAiChat.getState().ask('이것은?', { id: 'w1', programId: 'schedule', title: '일정판' });
  expect(sent).toEqual([{ program: 'schedule', schedule_id: 4, selected_activity: 'A1030' }]);
});

test('a window that published nothing sends only its program and the bound schedule', async () => {
  useWindows.setState({ wins: [win('w1', 'questionnaire', 1, { activity: 'A1020' })] } as never);
  await useAiChat.getState().ask('질문', { id: 'w1', programId: 'questionnaire', title: '질문지' });
  expect(sent).toEqual([{ program: 'questionnaire', schedule_id: 4 }]);
});

test('when the source is the chat window, the front-most other publisher is used (same rule as the chat program)', async () => {
  useWindows.setState({ wins: [win('w1', 'schedule', 1), win('w2', 'chat', 2)] } as never);
  useUiContext.getState().publish('w1', { program: 'schedule', schedule_id: 4, selected_activity: 'A2020' });
  await useAiChat.getState().ask('질문', { id: 'w2', programId: 'chat', title: '에이전트 대화' });
  expect(sent).toEqual([{ program: 'schedule', schedule_id: 4, selected_activity: 'A2020' }]);
});
