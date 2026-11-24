import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest';
import { registerPrograms } from '../programs';
import { json, signInAsDemo, stubFetch } from '../test-helpers';
import App from './App';
import { useAiChat } from './aiChat';
import { useCurrentSchedule } from './currentSchedule';
import { useContextPanel } from './contextStore';
import { useEvidence } from './evidence';
import { useSession } from './session';
import { useShell } from './shell';
import { useWindows } from './windowStore';

const mockLogin = (status: number, body: object) =>
  stubFetch({
    'POST /api/auth/login': () => json(status, body),
    '/api/approvals/count': { pending: 0 },
    '/api/schedules': [],
  });

async function submit(id = 'demo-admin', password = 'pw') {
  await userEvent.type(screen.getByLabelText('아이디'), id);
  await userEvent.type(screen.getByLabelText('비밀번호'), password);
  await userEvent.click(screen.getByRole('button', { name: '들어가기' }));
}

beforeAll(() => registerPrograms());
beforeEach(() => localStorage.clear());
afterEach(() => {
  vi.unstubAllGlobals();
  useWindows.getState().reset();
  useSession.getState().logout();
});

test('login success shows the desktop with the user name and role', async () => {
  const fetch = mockLogin(200, { token: 't', user: { id: 2, name: '김민지', role: 'user' } });
  render(<App />);
  await submit('kim', 'secret');
  expect(await screen.findByRole('button', { name: '김민지 사용자' })).toBeVisible();
  expect(JSON.parse(String(fetch.mock.calls[0][1]?.body))).toEqual({
    login_id: 'kim',
    password: 'secret',
    device_key: expect.stringMatching(/^[A-Za-z0-9_-]{16,64}$/),
    kind: expect.stringMatching(/^(desktop|tablet|phone)$/),
  });
  expect(useSession.getState().session).toMatchObject({ token: 't', loginId: 'kim' });
});

test('logout returns to login and closes windows', async () => {
  mockLogin(200, {});
  signInAsDemo('admin');
  render(<App />);
  await userEvent.click(within(screen.getByRole('toolbar', { name: '프로그램 막대' })).getByRole('button', { name: /^스케줄/ }));
  await userEvent.click(screen.getByRole('button', { name: 'ChronOS 메뉴' }));
  await userEvent.click(screen.getByRole('menuitem', { name: '로그아웃' }));
  expect(screen.getByRole('button', { name: '들어가기' })).toBeVisible();
  expect(useSession.getState().session).toBeNull();
  expect(useWindows.getState().wins).toEqual([]);
});

test('a locked session stays locked on load', () => {
  mockLogin(200, {});
  signInAsDemo('admin');
  useSession.getState().lock();
  render(<App />);
  expect(screen.getByRole('dialog', { name: '잠금 화면' })).toBeVisible();
});

test('the lock screen can log out to the login screen', async () => {
  mockLogin(200, {});
  signInAsDemo('admin');
  useSession.getState().lock();
  render(<App />);
  const lock = screen.getByRole('dialog', { name: '잠금 화면' });
  await userEvent.click(within(lock).getByRole('button', { name: '로그아웃' }));
  expect(screen.getByRole('button', { name: '들어가기' })).toBeVisible();
  expect(useSession.getState()).toMatchObject({ session: null, locked: false });
  expect(localStorage.getItem('chronos.session')).toBeNull();
});

test('logging out and in as someone else leaves nothing of the previous user', () => {
  mockLogin(200, {});
  signInAsDemo('admin');
  render(<App />);
  act(() => {
    const id = useWindows.getState().open('schedule-table');
    useContextPanel.getState().toggle();
    useEvidence.getState().setEvidence(id, [{ label: '비밀 근거', value: '1' }]);
    useAiChat.setState({ scheduleId: null, lines: [{ who: 'me', text: '앞 사람 질문' }], sessionId: 9 });
    useShell.getState().setDialog({ kind: 'about' });
    useShell.getState().setDrawer('edit');
    useShell.getState().setPalette(true);
  });
  act(() => useSession.getState().logout());
  act(() => signInAsDemo('user', '박서준', 'demo-user', 2));
  expect(useContextPanel.getState()).toMatchObject({ open: false, source: null });
  expect(useEvidence.getState().byWindow).toEqual({});
  expect(useAiChat.getState()).toMatchObject({ lines: [], sessionId: null });
  expect(useShell.getState()).toMatchObject({ dialog: null, drawer: 'closed', palette: false });
  act(() => void useWindows.getState().open('schedule-table'));
  expect(useWindows.getState().wins[0].id).toBe('w1');
  expect(useEvidence.getState().byWindow.w1).toBeUndefined();
});

test('a different user signing in over a session also clears the previous state', () => {
  mockLogin(200, {});
  signInAsDemo('admin');
  render(<App />);
  act(() => useShell.getState().setDialog({ kind: 'shortcuts' }));
  act(() => signInAsDemo('user', '박서준', 'demo-user', 2));
  expect(useShell.getState().dialog).toBeNull();
});

test('the next user never sees the previous user\'s site, not even in the first frame', () => {
  mockLogin(200, {});
  localStorage.setItem('chronos.schedule.2', JSON.stringify({ id: 5, name: '박서준의 물류센터' }));
  signInAsDemo('admin');
  render(<App />);
  act(() => useCurrentSchedule.getState().setCurrent({ id: 4, name: '김하늘의 사무동' }));
  const seen: (string | undefined)[] = [];
  const stop = useCurrentSchedule.subscribe((s) => seen.push(s.current?.name));
  act(() => useSession.getState().logout());
  expect(useCurrentSchedule.getState().current).toBeNull();
  act(() => signInAsDemo('user', '박서준', 'demo-user', 2));
  expect(useCurrentSchedule.getState().current).toEqual({ id: 5, name: '박서준의 물류센터' });
  expect(seen).not.toContain('김하늘의 사무동');
  stop();
  act(() => useSession.getState().logout());
  act(() => signInAsDemo('admin'));
  expect(useCurrentSchedule.getState().current).toEqual({ id: 4, name: '김하늘의 사무동' });
});

test('a user without a stored site sees 일정 고르기 after someone else used the browser', async () => {
  stubFetch({
    '/api/approvals/count': { pending: 0 },
    '/api/schedules': [
      { id: 4, name: '김하늘의 사무동', level: 'L3' },
      { id: 5, name: '물류센터', level: 'L2' },
    ],
  });
  signInAsDemo('admin');
  render(<App />);
  act(() => useCurrentSchedule.getState().setCurrent({ id: 4, name: '김하늘의 사무동' }));
  act(() => useSession.getState().logout());
  act(() => signInAsDemo('user', '박서준', 'demo-user', 2));
  expect(await screen.findByRole('button', { name: '일정 고르기' })).toBeVisible();
  expect(screen.queryByText(/김하늘의 사무동/)).toBeNull();
});
