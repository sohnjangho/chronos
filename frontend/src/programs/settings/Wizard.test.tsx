import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import Desktop from '../../os/Desktop';
import { register } from '../../os/registry';
import { useSession } from '../../os/session';
import { useWindows } from '../../os/windowStore';
import { json, signInAs, stubFetch } from '../../test-helpers';
import manifest from './index';
import type { Connection } from './model';
import { connection, FAKE_SECRET, LINER_URL, renderAs, resetAll, routes, sent } from './testKit';

const OK_PROBE = { ok: true, latency_ms: 398, models: ['liner-mark'], error: null };
const BAD_KEY = { ok: false, latency_ms: 120, models: [], error: { code: 'bad_key', message: 'API 키가 맞지 않습니다.' } };

const wizard = () => screen.getByRole('region', { name: '연결 추가' });
const urlInput = () => within(wizard()).getByLabelText('URL');
const nameInput = () => within(wizard()).getByLabelText('이름');
const keyInput = () => within(wizard()).getByLabelText(/^API 키/);
const testBtn = () => within(wizard()).getByRole('button', { name: /^(연결 테스트|다시 테스트)$/ });
const saveBtn = () => within(wizard()).getByRole('button', { name: '저장' });

async function openWizard(provider: RegExp = /^Liner/) {
  await userEvent.click(await screen.findByRole('button', { name: '+ 연결 추가' }));
  await userEvent.click(within(wizard()).getByRole('button', { name: provider }));
}

beforeEach(() => {
  vi.stubGlobal('innerWidth', 1920);
  vi.stubGlobal('innerHeight', 1080);
});
afterEach(resetAll);

test('liner provider prefills the url', async () => {
  renderAs('admin');
  await openWizard();
  expect(urlInput()).toHaveValue('https://platform.liner.com/api/v1');
  expect(nameInput()).toHaveValue('Liner');
  await userEvent.click(within(wizard()).getByRole('button', { name: /^직접 URL/ }));
  expect(urlInput()).toHaveValue('');
});

test('save is disabled until the test passes', async () => {
  const { fetchMock } = renderAs('admin', undefined, { 'POST /api/llm/connections/test': OK_PROBE });
  await openWizard();
  await userEvent.type(keyInput(), FAKE_SECRET);
  expect(saveBtn()).toBeDisabled();
  await userEvent.click(testBtn());
  expect(await screen.findByText(/모델 1개/)).toBeVisible();
  expect(saveBtn()).toBeEnabled();
  expect(screen.getByText(/응답 398ms/)).toBeVisible();
  expect(within(wizard()).getByText('liner-mark')).toBeVisible();
  expect(sent(fetchMock, 'POST /api/llm/connections/test')).toEqual([
    { provider: 'liner', base_url: LINER_URL, secret: FAKE_SECRET },
  ]);
  // 테스트한 뒤 키를 바꾸면 다시 테스트해야 저장할 수 있다.
  await userEvent.type(keyInput(), 'x');
  expect(saveBtn()).toBeDisabled();
});

test('test failure shows the reason', async () => {
  renderAs('admin', undefined, { 'POST /api/llm/connections/test': BAD_KEY });
  await openWizard();
  await userEvent.type(keyInput(), FAKE_SECRET);
  await userEvent.click(testBtn());
  expect(await screen.findByText('API 키가 맞지 않습니다.')).toBeVisible();
  expect(screen.getByText('bad_key')).toBeVisible();
  // 코드도 글꼴 토큰을 따른다(<code> 는 브라우저의 고정폭 글꼴을 쓴다).
  expect(screen.getByText('bad_key').tagName).toBe('SPAN');
  expect(saveBtn()).toBeDisabled();
});

test('a refused test request shows the server message and code', async () => {
  renderAs('admin', undefined, {
    'POST /api/llm/connections/test': () =>
      json(422, { code: 'invalid_secret', message: 'API 키에 쓸 수 없는 문자가 있습니다.', detail: null }),
  });
  await openWizard();
  await userEvent.type(keyInput(), FAKE_SECRET);
  await userEvent.click(testBtn());
  expect(await screen.findByText('API 키에 쓸 수 없는 문자가 있습니다.')).toBeVisible();
  expect(screen.getByText('invalid_secret')).toBeVisible();
  expect(saveBtn()).toBeDisabled();
});

test('key input is a password field and is cleared after save', async () => {
  let conns: Connection[] = [];
  const { fetchMock } = renderAs('admin', undefined, {
    '/api/llm/connections': () => json(200, conns),
    'POST /api/llm/connections/test': OK_PROBE,
    'POST /api/llm/connections': () => {
      conns = [connection({ secret_last4: '5678', model_count: 1 })];
      return json(201, { ...conns[0], error: null });
    },
  });
  await openWizard();
  expect(keyInput()).toHaveAttribute('type', 'password');
  expect(keyInput()).toHaveAttribute('autocomplete', 'new-password');
  await userEvent.clear(nameInput());
  await userEvent.type(nameInput(), 'Liner 기본');
  await userEvent.type(keyInput(), FAKE_SECRET);
  await userEvent.click(testBtn());
  await screen.findByText(/모델 1개/);
  await userEvent.click(saveBtn());
  expect(await screen.findByText(/5678$/)).toBeVisible();
  expect(screen.queryByDisplayValue(FAKE_SECRET)).toBeNull();
  expect(screen.queryByRole('region', { name: '연결 추가' })).toBeNull();
  expect(sent(fetchMock, 'POST /api/llm/connections')).toEqual([
    { name: 'Liner 기본', provider: 'liner', base_url: LINER_URL, secret: FAKE_SECRET },
  ]);
});

test('the key goes only into request bodies: never a URL, storage, a store or the console', async () => {
  const logged = (['log', 'info', 'warn', 'error', 'debug'] as const).map((k) =>
    vi.spyOn(console, k).mockImplementation(() => {}),
  );
  let conns: Connection[] = [];
  const { fetchMock } = renderAs('admin', undefined, {
    '/api/llm/connections': () => json(200, conns),
    'POST /api/llm/connections/test': OK_PROBE,
    'POST /api/llm/connections': () => {
      conns = [connection({ secret_last4: '5678' })];
      return json(201, { ...conns[0], error: null });
    },
  });
  await openWizard();
  await userEvent.type(keyInput(), FAKE_SECRET);
  await userEvent.click(testBtn());
  await screen.findByText(/모델 1개/);
  await userEvent.click(saveBtn());
  await screen.findByText(/5678$/);

  const withKey = fetchMock.mock.calls.filter(([, init]) => String(init?.body ?? '').includes(FAKE_SECRET));
  expect(withKey.map(([url, init]) => `${init?.method} ${url}`)).toEqual([
    'POST /api/llm/connections/test',
    'POST /api/llm/connections',
  ]);
  for (const [url] of fetchMock.mock.calls) expect(String(url)).not.toContain(FAKE_SECRET);
  const dump = (s: Storage) => Array.from({ length: s.length }, (_, i) => s.getItem(s.key(i) ?? '')).join('|');
  expect(dump(localStorage) + dump(sessionStorage)).not.toContain(FAKE_SECRET);
  expect(JSON.stringify(useWindows.getState()) + JSON.stringify(useSession.getState())).not.toContain(FAKE_SECRET);
  for (const spy of logged) expect(JSON.stringify(spy.mock.calls)).not.toContain(FAKE_SECRET);
});

test('cancel clears the key', async () => {
  renderAs('admin');
  await openWizard();
  await userEvent.type(keyInput(), FAKE_SECRET);
  await userEvent.click(within(wizard()).getByRole('button', { name: '취소' }));
  expect(screen.queryByRole('region', { name: '연결 추가' })).toBeNull();
  expect(screen.queryByDisplayValue(FAKE_SECRET)).toBeNull();
  await openWizard();
  expect(keyInput()).toHaveValue('');
});

test('closing the settings window clears the key', async () => {
  register(manifest);
  signInAs('admin');
  stubFetch(routes({ '/api/approvals/count': { pending: 0 }, '/api/schedules': [] }));
  render(<Desktop />);
  act(() => void useWindows.getState().open('settings'));
  await openWizard();
  await userEvent.type(keyInput(), FAKE_SECRET);
  await userEvent.click(within(screen.getByRole('dialog', { name: '설정' })).getByRole('button', { name: '닫기' }));
  expect(screen.queryByDisplayValue(FAKE_SECRET)).toBeNull();
  act(() => void useWindows.getState().open('settings'));
  await openWizard();
  expect(keyInput()).toHaveValue('');
});
