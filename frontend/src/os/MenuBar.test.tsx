import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest';
import { registerPrograms } from '../programs';
import { json, signInAs, stubFetch } from '../test-helpers';
import { useApprovals } from './approvals';
import { useCurrentSchedule } from './currentSchedule';
import Desktop from './Desktop';
import { useSession } from './session';
import { useTheme } from './theme';
import { useWindows } from './windowStore';

const menubar = () => screen.getByRole('banner');
const approvalsButton = () => within(menubar()).getByRole('button', { name: /^승인함 — 대기/ });
const dockApprovals = () =>
  within(screen.getByRole('toolbar', { name: '프로그램 막대' })).getByRole('button', { name: /^승인함/ });
const flush = () => act(() => vi.advanceTimersByTimeAsync(0));
const advance = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms));

const schedules = [
  { id: 4, name: '5층 사무동 신축', domain: 'construction', level: 'L3', version: 2, finish: null, updated_at: 'x' },
  { id: 5, name: '물류센터', domain: 'construction', level: 'L2', version: 1, finish: null, updated_at: 'x' },
];

beforeAll(() => registerPrograms());
beforeEach(() => {
  vi.useFakeTimers();
  localStorage.clear();
  signInAs('admin');
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  useWindows.getState().reset();
  useApprovals.setState({ pending: 0 });
  useCurrentSchedule.getState().setCurrent(null);
  useTheme.getState().load(null);
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
  expect(approvalsButton()).toHaveAccessibleName('승인함 — 대기 2건');
  expect(approvalsButton()).toHaveTextContent('2');
  expect(dockApprovals()).toHaveTextContent('2');

  pending = 0;
  await advance(29_000);
  expect(approvalsButton()).toHaveTextContent('2');
  await advance(1_000);
  expect(approvalsButton()).toHaveTextContent(/^$/);
  expect(dockApprovals()).toHaveTextContent(/^$/);

  pending = 3;
  await advance(30_000);
  expect(approvalsButton()).toHaveTextContent('3');
  fail = true;
  await advance(30_000);
  expect(approvalsButton()).toHaveTextContent('3');
});

test('the corner badge caps at 99+ and the Dock badge shows the full number', async () => {
  stubFetch({ '/api/approvals/count': { pending: 120 }, '/api/approvals?status=pending': { mode: 'x', items: [] }, '/api/schedules': [] });
  render(<Desktop />);
  await flush();
  expect(approvalsButton()).toHaveTextContent('99+');
  expect(approvalsButton()).toHaveAttribute('data-tip', '승인 대기 120건');
  expect(dockApprovals()).toHaveTextContent('120');
  fireEvent.click(approvalsButton());
  expect(useWindows.getState().activeProgramId()).toBe('approvals');
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
  expect(approvalsButton()).toHaveTextContent('7');
});

test('search, bell and theme are 32px icon buttons; the bell has no badge at 0', async () => {
  stubFetch({ '/api/approvals/count': { pending: 0 }, '/api/schedules': [] });
  render(<Desktop />);
  await flush();
  expect(within(menubar()).getByRole('button', { name: '검색 (Ctrl+K)' })).toBeInTheDocument();
  expect(within(menubar()).getByRole('button', { name: '알림 0건' })).toHaveTextContent(/^$/);
  expect(within(menubar()).getByRole('button', { name: '어두운 테마로' })).toBeInTheDocument();
});

test('the theme button toggles data-theme and remembers it per user', async () => {
  stubFetch({ '/api/approvals/count': { pending: 0 }, '/api/schedules': [] });
  render(<Desktop />);
  await flush();
  fireEvent.click(within(menubar()).getByRole('button', { name: '어두운 테마로' }));
  expect(document.documentElement).toHaveAttribute('data-theme', 'dark');
  expect(localStorage.getItem('chronos.theme.1')).toBe('"dark"');
  expect(within(menubar()).getByRole('button', { name: '밝은 테마로' })).toBeInTheDocument();
  act(() => useTheme.getState().load(2));
  expect(document.documentElement).toHaveAttribute('data-theme', 'light');
  act(() => useTheme.getState().load(1));
  expect(document.documentElement).toHaveAttribute('data-theme', 'dark');
});

test('the user button opens a menu with name, login id, role, settings and logout', async () => {
  stubFetch({ '/api/approvals/count': { pending: 0 }, '/api/schedules': [] });
  render(<Desktop />);
  await flush();
  const user = within(menubar()).getByRole('button', { name: '손장호 관리자' });
  fireEvent.click(user);
  const menu = screen.getByRole('menu', { name: '손장호 관리자' });
  expect(within(menu).getByRole('menuitem', { name: /손장호/ })).toBeDisabled();
  expect(within(menu).getByText('jhsohn')).toBeInTheDocument();
  expect(within(menu).getByText('등급')).toBeInTheDocument();
  expect(within(menu).getByRole('menuitem', { name: '관리자' })).toBeDisabled();
  fireEvent.click(within(menu).getByRole('menuitem', { name: '로그아웃' }));
  expect(useSession.getState().session).toBeNull();
});

test('the clock shows Korean date and time', async () => {
  vi.setSystemTime(new Date(2026, 10, 19, 22, 10));
  stubFetch({ '/api/approvals/count': { pending: 0 }, '/api/schedules': [] });
  render(<Desktop />);
  await flush();
  expect(within(menubar()).getByText('11월 19일 (목) 오후 10:10')).toBeInTheDocument();
});

test('site selector says 일정 없음 when there is no schedule', async () => {
  stubFetch({ '/api/approvals/count': { pending: 0 }, '/api/schedules': [] });
  render(<Desktop />);
  await flush();
  expect(within(menubar()).getByText('일정 없음')).toBeInTheDocument();
});

test('site selector lists schedules with a search box and sets the current schedule', async () => {
  stubFetch({ '/api/approvals/count': { pending: 0 }, '/api/schedules': schedules });
  render(<Desktop />);
  await flush();
  const button = within(menubar()).getByRole('button', { name: '일정 고르기' });
  expect(button).toHaveTextContent('▾');
  fireEvent.click(button);
  await flush();
  const box = screen.getByRole('combobox', { name: '일정 찾기' });
  expect(box).toHaveFocus();
  expect(screen.getAllByRole('option')).toHaveLength(2);
  fireEvent.change(box, { target: { value: '물류' } });
  expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual(['물류센터 · L2']);
  fireEvent.keyDown(box, { key: 'Enter' });
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
