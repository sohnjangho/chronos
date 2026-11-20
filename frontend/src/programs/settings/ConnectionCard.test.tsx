import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';
import { json } from '../../test-helpers';
import type { Connection } from './model';
import { connection, FAKE_SECRET, info, LINER_URL, renderAs, resetAll, sent } from './testKit';

const HOST_MESSAGE = '다른 서버 주소로 바꾸면 API 키를 다시 넣어 주세요.';
const card = () => screen.getByRole('article', { name: 'Liner 기본' });
const action = async (name: string) => userEvent.click(within(await screen.findByRole('article', { name: 'Liner 기본' })).getByRole('button', { name }));

afterEach(resetAll);

test('a card shows name, provider, default, status, url, last four, check and actions', async () => {
  const checked = new Date();
  checked.setHours(9, 5, 0, 0);
  renderAs('admin', undefined, {
    '/api/llm/connections': [connection({ checked_at: checked.toISOString() })],
  });
  const c = await screen.findByRole('article', { name: 'Liner 기본' });
  for (const text of ['Liner', '기본 연결', '연결됨 · 모델 3개', LINER_URL, '오늘 09:05 · 응답 412ms']) {
    expect(within(c).getByText(text)).toBeVisible();
  }
  expect(within(c).getByText(/4f2a$/)).toBeVisible();
  for (const name of ['연결 테스트', 'URL 수정', '키 교체', '삭제']) {
    expect(within(c).getByRole('button', { name })).toBeVisible();
  }
});

test('a card test shows a summary line and the models grouped by vendor', async () => {
  renderAs('admin', undefined, {
    '/api/llm/connections': [connection()],
    'POST /api/llm/connections/1/test': {
      ok: true,
      latency_ms: 377,
      models: [info('liner-mark', 'Liner: Liner Mark', 'liner', 1048576), info('liner-claude-router', 'Liner: Claude Router', 'liner', 200000)],
      error: null,
    },
  });
  await action('연결 테스트');
  expect(await within(card()).findByText('연결됨 · 377ms · 모델 2개 (대화용 2개) · 업체 1곳')).toBeVisible();
  await userEvent.click(within(card()).getByRole('button', { name: 'Liner 2개' }));
  expect(within(card()).getByText('liner-claude-router')).toBeVisible();
});

test('a long model list is searchable', async () => {
  const models = Array.from({ length: 40 }, (_, i) => info(`v/model-${i}`, `Vendor: Model ${i}`, 'v', 8192)).concat([
    info('liner-mark', 'Liner: Liner Mark', 'liner', 1048576),
  ]);
  renderAs('admin', undefined, {
    '/api/llm/connections': [connection()],
    'POST /api/llm/connections/1/test': { ok: true, latency_ms: 300, models, error: null },
  });
  await action('연결 테스트');
  const search = await within(card()).findByRole('searchbox', { name: '모델 찾기' });
  await userEvent.type(search, 'mark');
  expect(within(card()).getByText('liner-mark')).toBeVisible();
  expect(within(card()).queryByText('v/model-1')).toBeNull();
});

test('a failed card test shows the server message and code', async () => {
  renderAs('admin', undefined, {
    '/api/llm/connections': [connection()],
    'POST /api/llm/connections/1/test': () =>
      json(409, { code: 'secret_unreadable', message: '저장된 키를 읽을 수 없습니다. 키를 다시 넣어 주세요.', detail: null }),
  });
  await action('연결 테스트');
  expect(await screen.findByText('저장된 키를 읽을 수 없습니다. 키를 다시 넣어 주세요.')).toBeVisible();
  expect(screen.getByText('secret_unreadable')).toBeVisible();
});

test('changing host asks for the key again', async () => {
  renderAs('admin', undefined, {
    '/api/llm/connections': [connection()],
    'PATCH /api/llm/connections/1': () => json(422, { code: 'secret_required', message: HOST_MESSAGE, detail: null }),
  });
  await action('URL 수정');
  const url = within(card()).getByLabelText('URL');
  await userEvent.clear(url);
  await userEvent.type(url, 'https://other.example/v1');
  await userEvent.click(within(card()).getByRole('button', { name: '저장' }));
  expect(await screen.findByText(HOST_MESSAGE)).toBeVisible();
});

test('secret_required reveals the key field and the next save sends the key once', async () => {
  let conns: Connection[] = [connection()];
  const { fetchMock } = renderAs('admin', undefined, {
    '/api/llm/connections': () => json(200, conns),
    'PATCH /api/llm/connections/1': (init?: RequestInit) => {
      const body = JSON.parse(String(init?.body));
      if (!body.secret) return json(422, { code: 'secret_required', message: HOST_MESSAGE, detail: null });
      conns = [connection({ base_url: body.base_url, secret_last4: '5678' })];
      return json(200, { ...conns[0], error: null });
    },
  });
  await action('URL 수정');
  expect(within(card()).queryByLabelText(/API 키/)).toBeNull();
  const url = within(card()).getByLabelText('URL');
  await userEvent.clear(url);
  await userEvent.type(url, 'https://other.example/v1');
  await userEvent.click(within(card()).getByRole('button', { name: '저장' }));
  const key = await within(card()).findByLabelText(/API 키/);
  expect(key).toHaveAttribute('type', 'password');
  expect(key).toHaveAttribute('autocomplete', 'new-password');
  await userEvent.type(key, FAKE_SECRET);
  await userEvent.click(within(card()).getByRole('button', { name: '저장' }));
  expect(await within(card()).findByText('https://other.example/v1')).toBeVisible();
  expect(within(card()).getByText(/5678$/)).toBeVisible();
  expect(screen.queryByDisplayValue(FAKE_SECRET)).toBeNull();
  expect(sent(fetchMock, 'PATCH /api/llm/connections/1')).toEqual([
    { base_url: 'https://other.example/v1' },
    { base_url: 'https://other.example/v1', secret: FAKE_SECRET },
  ]);
});

test('replacing the key sends only the key, clears the field and shows the new last four', async () => {
  let conns: Connection[] = [connection()];
  const { fetchMock } = renderAs('admin', undefined, {
    '/api/llm/connections': () => json(200, conns),
    'PATCH /api/llm/connections/1': () => {
      conns = [connection({ secret_last4: '5678' })];
      return json(200, { ...conns[0], error: null });
    },
  });
  await action('키 교체');
  const key = within(card()).getByLabelText(/API 키/);
  expect(key).toHaveAttribute('type', 'password');
  await userEvent.type(key, FAKE_SECRET);
  await userEvent.click(within(card()).getByRole('button', { name: '저장' }));
  expect(await within(card()).findByText(/5678$/)).toBeVisible();
  expect(screen.queryByDisplayValue(FAKE_SECRET)).toBeNull();
  expect(sent(fetchMock, 'PATCH /api/llm/connections/1')).toEqual([{ secret: FAKE_SECRET }]);
});

test('cancelling a key replacement clears the key', async () => {
  renderAs('admin', undefined, { '/api/llm/connections': [connection()] });
  await action('키 교체');
  await userEvent.type(within(card()).getByLabelText(/API 키/), FAKE_SECRET);
  await userEvent.click(within(card()).getByRole('button', { name: '취소' }));
  expect(screen.queryByDisplayValue(FAKE_SECRET)).toBeNull();
  await action('키 교체');
  expect(within(card()).getByLabelText(/API 키/)).toHaveValue('');
});

test('delete asks in the app, says assignments go back to defaults, then deletes', async () => {
  const confirm = vi.fn(() => true);
  const alert = vi.fn();
  vi.stubGlobal('confirm', confirm);
  vi.stubGlobal('alert', alert);
  let conns: Connection[] = [connection()];
  const { fetchMock } = renderAs('admin', undefined, {
    '/api/llm/connections': () => json(200, conns),
    'DELETE /api/llm/connections/1': () => {
      conns = [];
      return new Response(null, { status: 204 });
    },
  });
  await action('삭제');
  const panel = within(card()).getByRole('group', { name: '연결 삭제 확인' });
  expect(panel).toHaveTextContent('「Liner 기본」 연결을 지울까요?');
  expect(panel).toHaveTextContent('이 연결을 쓰던 작업별 모델 배정은 기본값으로 돌아갑니다.');
  expect(sent(fetchMock, 'DELETE /api/llm/connections/1')).toHaveLength(0);
  await userEvent.click(within(panel).getByRole('button', { name: '삭제' }));
  await waitFor(() => expect(screen.queryByRole('article', { name: 'Liner 기본' })).toBeNull());
  expect(sent(fetchMock, 'DELETE /api/llm/connections/1')).toHaveLength(1);
  expect(confirm).not.toHaveBeenCalled();
  expect(alert).not.toHaveBeenCalled();
});

test('cancelling the delete panel deletes nothing', async () => {
  const { fetchMock } = renderAs('admin', undefined, { '/api/llm/connections': [connection()] });
  await action('삭제');
  await userEvent.click(within(card()).getByRole('button', { name: '취소' }));
  expect(within(card()).queryByRole('group', { name: '연결 삭제 확인' })).toBeNull();
  expect(sent(fetchMock, 'DELETE /api/llm/connections/1')).toHaveLength(0);
});

const GATEWAY = connection({ id: 2, name: '사내 게이트웨이', provider: 'openai_compatible', base_url: 'https://gw.example/v1', is_default: false });

test('기본으로 지정 shows only on a non-default card and sends is_default', async () => {
  let conns: Connection[] = [connection(), GATEWAY];
  const { fetchMock } = renderAs('admin', undefined, {
    '/api/llm/connections': () => json(200, conns),
    '/api/llm/connections/2/models': { models: [] },
    'PATCH /api/llm/connections/2': () => {
      conns = [connection({ is_default: false }), { ...GATEWAY, is_default: true }];
      return json(200, { ...conns[1], error: null });
    },
  });
  const liner = await screen.findByRole('article', { name: 'Liner 기본' });
  const gateway = screen.getByRole('article', { name: '사내 게이트웨이' });
  expect(within(liner).getByText('기본 연결')).toBeVisible();
  expect(within(liner).queryByRole('button', { name: '기본으로 지정' })).toBeNull();
  expect(within(gateway).queryByText('기본 연결')).toBeNull();
  await userEvent.click(within(gateway).getByRole('button', { name: '기본으로 지정' }));
  expect(await within(gateway).findByText('기본 연결')).toBeVisible();
  expect(within(liner).getByRole('button', { name: '기본으로 지정' })).toBeVisible();
  expect(sent(fetchMock, 'PATCH /api/llm/connections/2')).toEqual([{ is_default: true }]);
});

test('an open edit form locks the other card buttons, also while its request is in flight', async () => {
  renderAs('admin', undefined, {
    '/api/llm/connections': [connection()],
    'PATCH /api/llm/connections/1': () => new Promise<Response>(() => {}),
  });
  await action('URL 수정');
  const url = within(card()).getByLabelText('URL');
  await userEvent.type(url, '/');
  for (const name of ['연결 테스트', 'URL 수정', '키 교체', '삭제']) {
    expect(within(card()).getByRole('button', { name })).toBeDisabled();
  }
  await userEvent.click(within(card()).getByRole('button', { name: '저장' }));
  expect(within(card()).getByRole('button', { name: '키 교체' })).toBeDisabled();
  expect(within(card()).getByRole('group', { name: 'URL 수정' })).toBeVisible();
  expect(within(card()).getByLabelText('URL')).toHaveValue(`${LINER_URL}/`);
});

test('secret_required moves focus to the revealed key field; cancel clears that key', async () => {
  renderAs('admin', undefined, {
    '/api/llm/connections': [connection()],
    'PATCH /api/llm/connections/1': () => json(422, { code: 'secret_required', message: HOST_MESSAGE, detail: null }),
  });
  await action('URL 수정');
  const url = within(card()).getByLabelText('URL');
  await userEvent.clear(url);
  await userEvent.type(url, 'https://other.example/v1');
  await userEvent.click(within(card()).getByRole('button', { name: '저장' }));
  const key = await within(card()).findByLabelText(/API 키/);
  expect(key).toHaveFocus();
  await userEvent.type(key, FAKE_SECRET);
  await userEvent.click(within(card()).getByRole('button', { name: '취소' }));
  expect(screen.queryByDisplayValue(FAKE_SECRET)).toBeNull();
  await action('URL 수정');
  expect(within(card()).queryByLabelText(/API 키/)).toBeNull();
});
