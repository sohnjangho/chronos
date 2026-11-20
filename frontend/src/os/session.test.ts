import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import type { Session } from './session';

const KEY = 'chronos.session';
const sample: Session = { token: 't1', loginId: 'kim', user: { id: 3, name: '김민지', role: 'user' } };

async function freshSession() {
  vi.resetModules();
  return import('./session');
}

beforeEach(() => localStorage.clear());
afterEach(() => vi.restoreAllMocks());

test('sign in stores the session under chronos.session', async () => {
  const { useSession, getToken } = await freshSession();
  useSession.getState().signIn(sample);
  expect(getToken()).toBe('t1');
  expect(JSON.parse(localStorage.getItem(KEY)!)).toMatchObject({ token: 't1', loginId: 'kim', locked: false });
});

test('a stored session is restored on load, lock state included', async () => {
  localStorage.setItem(KEY, JSON.stringify({ ...sample, locked: true }));
  const { useSession } = await freshSession();
  expect(useSession.getState().session).toEqual(sample);
  expect(useSession.getState().locked).toBe(true);
});

test('broken stored data means no session', async () => {
  localStorage.setItem(KEY, '{not json');
  const { useSession } = await freshSession();
  expect(useSession.getState().session).toBeNull();
});

test('session works in memory when storage throws', async () => {
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
    throw new Error('denied');
  });
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new Error('denied');
  });
  vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
    throw new Error('denied');
  });
  const { useSession, getToken } = await freshSession();
  expect(useSession.getState().session).toBeNull();
  useSession.getState().signIn(sample);
  expect(getToken()).toBe('t1');
  useSession.getState().lock();
  expect(useSession.getState().locked).toBe(true);
  useSession.getState().logout();
  expect(getToken()).toBeNull();
});

test('lock is persisted and logout clears everything', async () => {
  const { useSession } = await freshSession();
  useSession.getState().signIn(sample);
  useSession.getState().lock();
  expect(JSON.parse(localStorage.getItem(KEY)!).locked).toBe(true);
  useSession.getState().logout();
  expect(localStorage.getItem(KEY)).toBeNull();
  expect(useSession.getState()).toMatchObject({ session: null, locked: false });
});

test('a stored session without loginId is ignored', async () => {
  localStorage.setItem(KEY, JSON.stringify({ token: 't1', user: sample.user, locked: false }));
  const { useSession } = await freshSession();
  expect(useSession.getState().session).toBeNull();
});
