// 관리자가 이 기기를 로그아웃하면: 다음 요청(접속 신호)이 401 → 로그인 화면 한 번, 그 뒤로 요청을 되풀이하지 않는다.
import { render, screen } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest';
import { registerPrograms } from '../programs';
import { json, signInAsDemo, stubFetch } from '../test-helpers';
import App from './App';
import { useSession } from './session';
import { useWindows } from './windowStore';

beforeAll(() => registerPrograms());
beforeEach(() => localStorage.clear());
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  useWindows.getState().reset();
  useSession.getState().logout();
});

test('a device logged out by an admin shows the login screen on its next request and does not loop', async () => {
  const fetch = stubFetch({
    '/api/approvals/count': { pending: 0 },
    '/api/schedules': [],
    'POST /api/me/presence': () =>
      json(401, { code: 'device_logged_out', message: '이 기기는 로그아웃되었습니다. 다시 로그인해 주세요.', detail: null }),
  });
  signInAsDemo('user');
  render(<App />);
  expect(await screen.findByRole('button', { name: '들어가기' })).toBeVisible();
  expect(useSession.getState().session).toBeNull();
  const calls = fetch.mock.calls.length;
  await new Promise((r) => setTimeout(r, 50));
  expect(fetch.mock.calls.length).toBe(calls);
  expect(fetch.mock.calls.filter(([url]) => url === '/api/me/presence')).toHaveLength(1);
});
