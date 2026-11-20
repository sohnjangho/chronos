import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest';
import { registerPrograms } from '../programs';
import { json, signInAs, stubFetch } from '../test-helpers';
import App from './App';
import { useSession } from './session';
import { useWindows } from './windowStore';

const mockLogin = (status: number, body: object) =>
  stubFetch({
    'POST /api/auth/login': () => json(status, body),
    '/api/approvals/count': { pending: 0 },
    '/api/schedules': [],
  });

async function submit(id = 'jhsohn', password = 'pw') {
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
  expect(await screen.findByText('김민지 · 사용자')).toBeVisible();
  expect(JSON.parse(String(fetch.mock.calls[0][1]?.body))).toEqual({ login_id: 'kim', password: 'secret' });
  expect(useSession.getState().session).toMatchObject({ token: 't', loginId: 'kim' });
});

test('logout returns to login and closes windows', async () => {
  mockLogin(200, {});
  signInAs('admin');
  render(<App />);
  await userEvent.click(within(screen.getByRole('navigation', { name: '프로그램 막대' })).getByRole('button', { name: '일정판' }));
  await userEvent.click(screen.getByRole('button', { name: 'ChronOS 메뉴' }));
  await userEvent.click(screen.getByRole('menuitem', { name: '로그아웃' }));
  expect(screen.getByRole('button', { name: '들어가기' })).toBeVisible();
  expect(useSession.getState().session).toBeNull();
  expect(useWindows.getState().wins).toEqual([]);
});

test('a locked session stays locked on load', () => {
  mockLogin(200, {});
  signInAs('admin');
  useSession.getState().lock();
  render(<App />);
  expect(screen.getByRole('dialog', { name: '잠금 화면' })).toBeVisible();
});

test('the lock screen can log out to the login screen', async () => {
  mockLogin(200, {});
  signInAs('admin');
  useSession.getState().lock();
  render(<App />);
  const lock = screen.getByRole('dialog', { name: '잠금 화면' });
  await userEvent.click(within(lock).getByRole('button', { name: '로그아웃' }));
  expect(screen.getByRole('button', { name: '들어가기' })).toBeVisible();
  expect(useSession.getState()).toMatchObject({ session: null, locked: false });
  expect(localStorage.getItem('chronos.session')).toBeNull();
});
