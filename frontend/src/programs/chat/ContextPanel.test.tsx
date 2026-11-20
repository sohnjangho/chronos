import { act, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest';
import { useCurrentSchedule } from '../../os/currentSchedule';
import { useUiContext } from '../../os/uiContext';
import { useChat } from './chatStore';
import { feed, feedPending, openOther, openSpy, registerFakePrograms, renderAt, routes, send, setup, SID } from './testKit';

const panel = () => screen.getByRole('complementary', { name: '대화 정보' });
const workflow = (status: string, steps: [string, string][]) =>
  ['workflow', { run_id: 3, status, steps: steps.map(([tool, s], i) => ({ n: i + 1, tool, program: null, status: s })) }] as [string, unknown];

beforeAll(() => registerFakePrograms());
beforeEach(() => {
  localStorage.clear();
  useCurrentSchedule.getState().setCurrent({ id: 1, name: '5층 사무동 신축' });
  setup();
});
afterEach(() => {
  useChat.getState().reset();
  useUiContext.getState().reset();
  vi.unstubAllGlobals();
});

test('지금 다루는 것: the target schedule with domain and level, and what the user is looking at', async () => {
  renderAt(1560);
  act(() => openOther('schedule', { program: 'schedule', schedule_id: 1, selected_activity: 'A2020' }));
  const p = panel();
  expect(await within(p).findByText('5층 사무동 신축')).toBeVisible();
  expect(within(p).getByText('건설 · L3 · 버전 3')).toBeVisible();
  expect(await within(p).findByText('일정판 · A2020 지상 1~5층 골조')).toBeVisible();
});

test('I2 · a reopened conversation shows — for usage until this window receives a usage event', async () => {
  routes[`/api/chat/sessions/${SID}`] = { id: SID, title: '공정표', schedule_id: 1, created_at: 'x', running: false, messages: [], pending_retries: [] };
  renderAt(1560, { session: String(SID) });
  const p = panel();
  expect(await within(p).findByText('이 창에서 받은 사용량')).toBeVisible();
  const row = (label: string) => within(p).getByText(label).closest('div')!;
  expect(row('토큰')).toHaveTextContent('—');
  expect(row('호출')).toHaveTextContent('—');
  expect(row('비용')).toHaveTextContent('—');
  expect(within(p).queryByText(/입력 0/)).toBeNull();
});

test('R8 · usage adds up every usage event; cost shows — when null', async () => {
  renderAt(1560);
  feed([['usage', { input_tokens: 48200, output_tokens: 9600, cost: null, calls: 3 }], ['done', {}]]);
  await send('하나');
  feed([['usage', { input_tokens: 800, output_tokens: 400, cost: null, calls: 2 }], ['done', {}]]);
  await send('둘');
  const p = panel();
  expect(within(p).getByText('입력 49K · 출력 10K')).toBeVisible();
  expect(within(p).getByText('5회')).toBeVisible();
  expect(within(p).getByText('—')).toBeVisible();
});

test('a reported cost is summed and shown', async () => {
  renderAt(1560);
  feed([['usage', { input_tokens: 10, output_tokens: 5, cost: 0.12, calls: 1 }], ['done', {}]]);
  await send('하나');
  feed([['usage', { input_tokens: 10, output_tokens: 5, cost: null, calls: 1 }], ['done', {}]]);
  await send('둘');
  expect(within(panel()).getByText('$0.12')).toBeVisible();
});

test('workflow steps follow the live workflow events and open the workflow program', async () => {
  renderAt(1560);
  const live = feedPending();
  await send('공정표 만들어 줘');
  act(() => live.push([workflow('running', [['generate.extract_conditions', 'done'], ['generate.run', 'running']])]));
  const steps = await within(panel()).findByRole('list', { name: '워크플로우 단계' });
  expect(within(steps).getAllByRole('listitem').map((li) => li.textContent)).toEqual(['① 조건 뽑기 · 끝남', '② 일정 만들기 · 진행 중']);
  act(() => live.push([workflow('done', [['generate.extract_conditions', 'done'], ['generate.run', 'done']]), ['done', {}]]));
  act(() => live.close());
  expect(await within(steps).findByText('② 일정 만들기 · 끝남')).toBeVisible();
  await userEvent.click(within(panel()).getByRole('button', { name: '워크플로우 창에서 보기' }));
  expect(openSpy).toHaveBeenCalledWith('workflow', { run: '3' });
});

test('활동 lists the runs of this conversation only', async () => {
  routes['/api/workflows/runs'] = [
    { id: 3, chat_session_id: SID, title: '공정표 만들어 줘', status: 'done', started_at: new Date().toISOString(), ended_at: null, tokens: 1200, cost: null, step_count: 2 },
    { id: 4, chat_session_id: 99, title: '다른 대화 실행', status: 'done', started_at: new Date().toISOString(), ended_at: null, tokens: 5, cost: null, step_count: 1 },
  ];
  routes[`/api/chat/sessions/${SID}`] = { id: SID, title: '공정표', schedule_id: 1, created_at: 'x', running: false, messages: [], pending_retries: [] };
  renderAt(1560, { session: String(SID) });
  await userEvent.click(screen.getByRole('tab', { name: '활동' }));
  const run = await within(panel()).findByRole('button', { name: /공정표 만들어 줘/ });
  expect(run).toHaveTextContent('끝남 · 단계 2개');
  expect(within(panel()).queryByText('다른 대화 실행')).toBeNull();
  await userEvent.click(run);
  expect(openSpy).toHaveBeenCalledWith('workflow', { run: '3' });
});
