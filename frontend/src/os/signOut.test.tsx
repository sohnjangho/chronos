// 본인 로그아웃: 서버에 이 기기 닫기(POST /api/auth/logout)를 알리고(실패해도) 곧바로 로그아웃한다.
// 예전 토큰(sid 없음)이 401 session_upgraded 를 받으면 로그인 화면에 부드러운 한 줄.
import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { api } from '../shared/api';
import { json, signInAsDemo, stubFetch } from '../test-helpers';
import { signOut } from './auth';
import Login from './Login';
import { useSession } from './session';

beforeEach(() => localStorage.clear());
afterEach(() => {
  vi.unstubAllGlobals();
  useSession.getState().logout();
});

test('signing out tells the server to close this device with the current token, then clears the session', () => {
  const fetch = stubFetch({ 'POST /api/auth/logout': () => new Response(null, { status: 204 }) });
  signInAsDemo('user');
  signOut();
  expect(useSession.getState().session).toBeNull();
  const [url, init] = fetch.mock.calls[0];
  expect(url).toBe('/api/auth/logout');
  expect(init?.method).toBe('POST');
  expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer tok');
});

test('signing out still clears the session when the server cannot be reached', () => {
  vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new TypeError('network'))));
  signInAsDemo('user');
  signOut();
  expect(useSession.getState().session).toBeNull();
});

test('an old token answered with session_upgraded shows a gentle line on the login screen', async () => {
  stubFetch({ '/api/auth/me': () => json(401, { code: 'session_upgraded', message: '보안 강화로 한 번 다시 로그인해 주세요.', detail: null }) });
  signInAsDemo('user');
  await expect(api('/api/auth/me')).rejects.toMatchObject({ status: 401 });
  expect(useSession.getState().session).toBeNull();
  render(<Login />);
  expect(screen.getByText('보안 강화로 한 번 다시 로그인해 주세요')).toBeVisible();
});

test('an ordinary sign-out shows no such line', () => {
  stubFetch({});
  signInAsDemo('user');
  signOut();
  render(<Login />);
  expect(screen.queryByText('보안 강화로 한 번 다시 로그인해 주세요')).toBeNull();
});
