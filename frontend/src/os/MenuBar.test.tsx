import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest';
import { registerPrograms } from '../programs';
import { json, signInAs, stubFetch } from '../test-helpers';
import { useCurrentSchedule } from './currentSchedule';
import Desktop from './Desktop';
import { useApprovals } from './approvals';
import { useSession } from './session';
import { useWindows } from './windowStore';

const menubar = () => screen.getByRole('banner');
const approvalsButton = () => within(menubar()).getByRole('button', { name: /^승인/ });
const dockApprovals = () =>
  within(screen.getByRole('navigation', { name: '프로그램 막대' })).getByRole('button', { name: '승인함' });
const flush = () => act(() => vi.advanceTimersByTimeAsync(0));
const advance = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms));

const schedules = [
  { id: 4, name: '5층 사무동 신축', domain: 'construction', level: 'L3', version: 2, finish: null, updated_at: 'x' },
  { id: 5, name: '물류센터', domain: 'construction', level: 'L2', version: 1, finish: null, updated_at: 'x' },
];

beforeAll(() => registerPrograms());
beforeEach(() => {
  vi.useFakeTimers();
  signInAs('admin');
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  useWindows.getState().reset();
  useApprovals.setState({ pending: 0 });
  useCurrentSchedule.getState().setCurrent(null);
  useSession.getState().logout();
});

test('approval badge polls every 30 s, hides at 0, keeps the last value on failure', async () => {
  let pending = 2;
  let fail = false;
  stubFetch({
    '/api/approvals/count': () => (fail ? json(500, { code: 'internal_error', message: 'x', detail: null }) : json(200, { pending })),
    '/api/approvals?status=pending': { mode: 'important', items: [] },
    '/api/schedules': [],
  });
  render(<Desktop />);
  await flush();
  expect(approvalsButton()).toHaveTextContent('승인 2');
  expect(dockApprovals()).toHaveTextContent('2');

  pending = 0;
  await advance(29_000);
  expect(approvalsButton()).toHaveTextContent('승인 2');
  await advance(1_000);
  expect(approvalsButton()).toHaveTextContent(/^승인$/);
  expect(dockApprovals()).toHaveTextContent(/^$/);

  pending = 3;
  await advance(30_000);
  expect(approvalsButton()).toHaveTextContent('승인 3');
  fail = true;
  await advance(30_000);
  expect(approvalsButton()).toHaveTextContent('승인 3');
});

test('approval badge refreshes when the tab regains focus', async () => {
  let pending = 0;
  stubFetch({
    '/api/approvals/count': () => json(200, { pending }),
    '/api/approvals?status=pending': { mode: 'important', items: [] },
    '/api/schedules': [],
  });
  render(<Desktop />);
  await flush();
  pending = 7;
  fireEvent.focus(window);
  await flush();
  expect(approvalsButton()).toHaveTextContent('승인 7');
});

test('the clock shows Korean date and time', async () => {
  vi.setSystemTime(new Date(2026, 10, 19, 22, 10));
  stubFetch({ '/api/approvals/count': { pending: 0 }, '/api/schedules': [] });
  render(<Desktop />);
  await flush();
  expect(within(menubar()).getByText('11월 19일 (목) 오후 10:10')).toBeInTheDocument();
  expect(within(menubar()).getByText('손장호 · 관리자')).toBeInTheDocument();
});

test('site selector says 일정 없음 when there is no schedule', async () => {
  stubFetch({ '/api/approvals/count': { pending: 0 }, '/api/schedules': [] });
  render(<Desktop />);
  await flush();
  expect(within(menubar()).getByRole('button', { name: '일정 없음' })).toBeInTheDocument();
});

test('site selector lists schedules with level and sets the current schedule', async () => {
  stubFetch({ '/api/approvals/count': { pending: 0 }, '/api/schedules': schedules });
  render(<Desktop />);
  await flush();
  fireEvent.click(within(menubar()).getByRole('button', { name: '일정 고르기' }));
  await flush();
  fireEvent.click(screen.getByRole('menuitem', { name: '물류센터 · L2' }));
  expect(useCurrentSchedule.getState().current).toEqual({ id: 5, name: '물류센터' });
  expect(within(menubar()).getByRole('button', { name: '물류센터 · L2' })).toBeInTheDocument();
});

test('a current schedule that no longer exists is cleared', async () => {
  useCurrentSchedule.getState().setCurrent({ id: 99, name: '지운 일정' });
  stubFetch({ '/api/approvals/count': { pending: 0 }, '/api/schedules': schedules });
  render(<Desktop />);
  await flush();
  expect(useCurrentSchedule.getState().current).toBeNull();
});
