import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { useSession } from '../os/session';
import { json, signInAs, stubFetch } from '../test-helpers';
import { api, ApiError, publicApi } from './api';

beforeEach(() => signInAs());
afterEach(() => {
  vi.unstubAllGlobals();
  useSession.getState().logout();
});

const headerOf = (init: RequestInit | undefined, name: string) => new Headers(init?.headers).get(name);

test('api adds token and maps errors', async () => {
  const fetch = stubFetch({
    '/x': () => json(422, { code: 'must_missing', message: '필수 칸이 없습니다.', detail: { field: 'name' } }),
  });
  const err = await api('/x').catch((e: unknown) => e);
  expect(err).toBeInstanceOf(ApiError);
  expect(err).toMatchObject({ code: 'must_missing', status: 422, message: '필수 칸이 없습니다.', detail: { field: 'name' } });
  expect(headerOf(fetch.mock.calls[0][1], 'Authorization')).toBe('Bearer tok');
});

test('api returns the JSON body and sends JSON', async () => {
  const fetch = stubFetch({ 'POST /y': { ok: 1 } });
  await expect(api<{ ok: number }>('/y', { method: 'POST', body: JSON.stringify({ a: 1 }) })).resolves.toEqual({ ok: 1 });
  expect(headerOf(fetch.mock.calls[0][1], 'Content-Type')).toBe('application/json');
});

test('api returns undefined for 204', async () => {
  stubFetch({ 'DELETE /z': () => new Response(null, { status: 204 }) });
  await expect(api('/z', { method: 'DELETE' })).resolves.toBeUndefined();
});

test('401 logs out', async () => {
  stubFetch({ '/me': () => json(401, { code: 'unauthorized', message: '다시 로그인해 주세요.', detail: null }) });
  await expect(api('/me')).rejects.toMatchObject({ status: 401, code: 'unauthorized' });
  expect(useSession.getState().session).toBeNull();
});

test('an error without a JSON body still becomes ApiError', async () => {
  stubFetch({ '/x': () => new Response('<html>bad gateway</html>', { status: 502 }) });
  await expect(api('/x')).rejects.toMatchObject({ status: 502, code: 'http_error', message: '요청을 처리할 수 없습니다.' });
});

test('network failure becomes ApiError with status 0', async () => {
  vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new TypeError('Failed to fetch'))));
  await expect(api('/x')).rejects.toMatchObject({ status: 0, code: 'network_error', message: '서버에 연결할 수 없습니다.' });
});

test('publicApi sends no token and does not log out on 401', async () => {
  const fetch = stubFetch({
    'POST /api/auth/login': () => json(401, { code: 'bad_credentials', message: '아이디 또는 비밀번호가 맞지 않습니다.', detail: null }),
  });
  await expect(publicApi('/api/auth/login', { method: 'POST', body: '{}' })).rejects.toMatchObject({ code: 'bad_credentials' });
  expect(headerOf(fetch.mock.calls[0][1], 'Authorization')).toBeNull();
  expect(useSession.getState().session).not.toBeNull();
});
