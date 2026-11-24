// 접속 신호: 로그인하면 한 번, 창이 보이는 동안 60초마다 POST /api/me/presence {device_key, kind}. 창이 가려지면 쉬고,
// 한 번에 하나만 보낸다. 관리자가 이 기기를 로그아웃하면(401) 로그인 화면으로 가고 더 보내지 않는다.
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { json, signInAsDemo } from '../test-helpers';
import { deviceKey, PRESENCE_MS, usePresence } from './presence';
import { useSession } from './session';

let fetchMock: ReturnType<typeof vi.fn>;
let reply: () => Response | Promise<Response>;
beforeEach(() => {
  vi.useFakeTimers();
  localStorage.clear();
  reply = () => json(200, { token: null });
  fetchMock = vi.fn(() => Promise.resolve(reply()));
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => {
  setHidden(false);
  vi.useRealTimers();
  vi.unstubAllGlobals();
  useSession.getState().logout();
});

function setHidden(hidden: boolean) {
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => (hidden ? 'hidden' : 'visible') });
  document.dispatchEvent(new Event('visibilitychange'));
}
const later = (ms: number) =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
const beats = () => fetchMock.mock.calls.filter(([url]) => url === '/api/me/presence');

test('the device key is random, kept for this browser and valid for the server', () => {
  const first = deviceKey();
  expect(first).toMatch(/^[A-Za-z0-9_-]{16,64}$/);
  expect(deviceKey()).toBe(first);
  localStorage.clear();
  expect(deviceKey()).not.toBe(first);
});

test('beats once on load and then every 60 seconds with the device key and kind', async () => {
  signInAsDemo('user');
  renderHook(() => usePresence());
  await later(0);
  expect(beats()).toHaveLength(1);
  const [, init] = beats()[0];
  expect(init.method).toBe('POST');
  expect(JSON.parse(String(init.body))).toEqual({ device_key: deviceKey(), kind: expect.stringMatching(/^(desktop|tablet|phone)$/) });
  await later(PRESENCE_MS - 1);
  expect(beats()).toHaveLength(1);
  await later(1);
  expect(PRESENCE_MS).toBe(60_000);
  expect(beats()).toHaveLength(2);
});

test('pauses while the page is hidden and beats again when it comes back', async () => {
  signInAsDemo('user');
  renderHook(() => usePresence());
  await later(0);
  setHidden(true);
  await later(PRESENCE_MS * 3);
  expect(beats()).toHaveLength(1);
  setHidden(false);
  await later(0);
  expect(beats()).toHaveLength(2);
});

test('keeps at most one beat in flight', async () => {
  signInAsDemo('user');
  let release: (r: Response) => void = () => {};
  reply = () => new Promise<Response>((r) => (release = r));
  renderHook(() => usePresence());
  await later(PRESENCE_MS * 3);
  setHidden(false);
  await later(0);
  expect(beats()).toHaveLength(1);
  await act(async () => release(json(200, { token: null })));
  await later(PRESENCE_MS);
  expect(beats()).toHaveLength(2);
});

test('signed out or locked sessions do not beat', async () => {
  renderHook(() => usePresence());
  await later(PRESENCE_MS * 2);
  signInAsDemo('user');
  act(() => useSession.getState().lock());
  await later(PRESENCE_MS * 2);
  expect(beats()).toHaveLength(0);
});

test('a device logged out by an admin goes to the login screen once and stops beating', async () => {
  signInAsDemo('user');
  reply = () => json(401, { code: 'device_logged_out', message: '이 기기는 로그아웃되었습니다. 다시 로그인해 주세요.', detail: null });
  renderHook(() => usePresence());
  await later(0);
  expect(useSession.getState().session).toBeNull();
  await later(PRESENCE_MS * 3);
  expect(beats()).toHaveLength(1);
});

test('a token from before device sessions is swapped for the bound one the server returns, lock state kept', async () => {
  signInAsDemo('user');
  reply = () => json(200, { token: 'bound-tok' });
  renderHook(() => usePresence());
  await later(0);
  expect(useSession.getState().session?.token).toBe('bound-tok');
  expect(JSON.parse(localStorage.getItem('chronos.session')!)).toMatchObject({ token: 'bound-tok', locked: false });
  reply = () => json(200, { token: null });
  await later(PRESENCE_MS);
  const [, init] = beats()[1];
  expect(new Headers(init.headers).get('Authorization')).toBe('Bearer bound-tok');
});
