import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test } from 'vitest';
import { json } from '../../test-helpers';
import type { Connection } from './model';
import { ASSIGNMENTS, connection, MODELS, renderAs, resetAll, sent } from './testKit';

const row = (label: string) => screen.getByRole('group', { name: label });
const options = (el: HTMLElement) => Array.from((el as HTMLSelectElement).options).map((o) => o.value);
const ASSIGN = { section: 'assign' };

afterEach(resetAll);

function renderTable(over = {}) {
  return renderAs('admin', ASSIGN, { '/api/llm/connections': [connection()], ...over });
}

test('the four task kinds use the mockup labels', async () => {
  renderTable();
  expect(await screen.findByRole('group', { name: '가벼운 일' })).toHaveTextContent('조건 뽑기, 분야 읽기, 문서에서 변화 뽑기');
  expect(row('보통 일')).toHaveTextContent('대화, 워크플로우 짜기, 보고서 초안');
  expect(row('어려운 일')).toHaveTextContent('WBS·스케줄 생성, 단축안, 위반 고치기');
  expect(row('긴 문서 읽기')).toHaveTextContent('계약서·회의록 통째로');
});

test('models are chosen from the loaded list of the selected connection', async () => {
  renderTable();
  const model = await within(await screen.findByRole('group', { name: '가벼운 일' })).findByRole('combobox', { name: '가벼운 일 모델' });
  await within(row('가벼운 일')).findByRole('option', { name: 'liner-gpt-router' });
  expect(options(model)).toEqual(MODELS);
  expect(model).toHaveValue('liner-claude-router');
  // 연결이 하나면 연결 고르기는 보이지 않는다.
  expect(within(row('가벼운 일')).queryByRole('combobox', { name: '가벼운 일 연결' })).toBeNull();
});

test('routing strategy is shown only for router models', async () => {
  renderTable();
  const light = await screen.findByRole('group', { name: '가벼운 일' });
  expect(within(light).getByRole('combobox', { name: '가벼운 일 기준' })).toHaveValue('cost');
  expect(within(row('긴 문서 읽기')).queryByRole('combobox', { name: '긴 문서 읽기 기준' })).toBeNull();
  await within(light).findByRole('option', { name: 'liner-mark' });
  await userEvent.selectOptions(within(light).getByRole('combobox', { name: '가벼운 일 모델' }), 'liner-mark');
  expect(within(light).queryByRole('combobox', { name: '가벼운 일 기준' })).toBeNull();
  // 라우터로 바꾸면 기준이 다시 보인다(기본 balanced).
  const longdoc = row('긴 문서 읽기');
  await userEvent.selectOptions(within(longdoc).getByRole('combobox', { name: '긴 문서 읽기 모델' }), 'liner-gpt-router');
  expect(within(longdoc).getByRole('combobox', { name: '긴 문서 읽기 기준' })).toHaveValue('balanced');
});

test('saving one row sends a single request with only that row', async () => {
  const { fetchMock } = renderTable({
    'PUT /api/llm/assignments': (init?: RequestInit) => {
      const item = JSON.parse(String(init?.body)).items[0];
      return json(200, { items: [item] });
    },
  });
  const light = await screen.findByRole('group', { name: '가벼운 일' });
  await within(light).findByRole('option', { name: 'liner-mark' });
  await userEvent.selectOptions(within(light).getByRole('combobox', { name: '가벼운 일 모델' }), 'liner-mark');
  await userEvent.selectOptions(within(row('보통 일')).getByRole('combobox', { name: '보통 일 기준' }), 'quality');
  expect(within(light).getByRole('button', { name: '저장' })).toBeEnabled();
  await userEvent.click(within(light).getByRole('button', { name: '저장' }));
  expect(await within(light).findByText('저장했습니다.')).toBeVisible();
  expect(sent(fetchMock, 'PUT /api/llm/assignments')).toEqual([
    { items: [{ purpose: 'light', connection_id: 1, model: 'liner-mark', routing_strategy: null }] },
  ]);
  expect(within(light).queryByRole('button', { name: '저장' })).toBeNull();
  // 다른 줄의 고친 값은 그대로 남아 있다.
  expect(within(row('보통 일')).getByRole('combobox', { name: '보통 일 기준' })).toHaveValue('quality');
  expect(within(row('보통 일')).getByRole('button', { name: '저장' })).toBeEnabled();
});

test('a save error is shown on that row', async () => {
  renderTable({
    'PUT /api/llm/assignments': () =>
      json(422, { code: 'invalid_request', message: '없는 연결을 골랐습니다.', detail: { connection_ids: [1] } }),
  });
  const normal = await screen.findByRole('group', { name: '보통 일' });
  await userEvent.selectOptions(within(normal).getByRole('combobox', { name: '보통 일 기준' }), 'cost');
  await userEvent.click(within(normal).getByRole('button', { name: '저장' }));
  expect(await within(normal).findByText('없는 연결을 골랐습니다.')).toBeVisible();
  expect(within(row('가벼운 일')).queryByText('없는 연결을 골랐습니다.')).toBeNull();
});

test('with two connections a row picks the connection and then a model from its list', async () => {
  const { fetchMock } = renderTable({
    '/api/llm/connections': [connection(), connection({ id: 2, name: '사내 게이트웨이', provider: 'openai_compatible', is_default: false })],
    '/api/llm/connections/2/models': { models: ['gw-large', 'gw-small'] },
    'PUT /api/llm/assignments': (init?: RequestInit) => json(200, JSON.parse(String(init?.body))),
  });
  const light = await screen.findByRole('group', { name: '가벼운 일' });
  await userEvent.selectOptions(within(light).getByRole('combobox', { name: '가벼운 일 연결' }), '2');
  await within(light).findByRole('option', { name: 'gw-small' });
  const model = within(light).getByRole('combobox', { name: '가벼운 일 모델' });
  expect(model).toHaveValue('');
  expect(within(light).getByRole('button', { name: '저장' })).toBeDisabled();
  await userEvent.selectOptions(model, 'gw-small');
  await userEvent.click(within(light).getByRole('button', { name: '저장' }));
  await within(light).findByText('저장했습니다.');
  expect(sent(fetchMock, 'PUT /api/llm/assignments')).toEqual([
    { items: [{ purpose: 'light', connection_id: 2, model: 'gw-small', routing_strategy: null }] },
  ]);
});

test('without connections the table says to add one first', async () => {
  renderAs('admin', ASSIGN, {
    '/api/llm/assignments': {
      items: ['light', 'normal', 'hard', 'longdoc'].map((purpose) => ({ purpose, connection_id: null, model: 'liner-mark', routing_strategy: null })),
    },
  });
  expect(await screen.findByText('연결이 없습니다. 먼저 「LLM 연결」에서 연결을 추가해 주세요.')).toBeVisible();
  expect(screen.queryByRole('combobox', { name: '가벼운 일 모델' })).toBeNull();
});

test('routing strategy options read 비용 우선 · 균형 · 품질 우선 and keep the stored values', async () => {
  renderTable();
  const select = await within(await screen.findByRole('group', { name: '가벼운 일' })).findByRole('combobox', { name: '가벼운 일 기준' });
  const opts = Array.from((select as HTMLSelectElement).options).map((o) => [o.value, o.text]);
  expect(opts).toEqual([
    ['cost', '비용 우선'],
    ['balanced', '균형'],
    ['quality', '품질 우선'],
  ]);
});

test('an unsaved row edit survives a connection reload while untouched rows follow the server', async () => {
  let reloads = 0;
  const { fetchMock } = renderAs('admin', undefined, {
    '/api/llm/connections': [connection()],
    'POST /api/llm/connections/1/test': { ok: true, latency_ms: 300, models: MODELS, error: null },
    '/api/llm/assignments': () => {
      reloads += 1;
      if (reloads === 1) return json(200, ASSIGNMENTS);
      const items = ASSIGNMENTS.items.map((i) => (i.purpose === 'hard' ? { ...i, routing_strategy: 'balanced' } : i));
      return json(200, { items });
    },
  });
  const normal = await screen.findByRole('group', { name: '보통 일' });
  await userEvent.selectOptions(within(normal).getByRole('combobox', { name: '보통 일 기준' }), 'cost');
  await userEvent.click(within(screen.getByRole('article', { name: 'Liner 기본' })).getByRole('button', { name: '연결 테스트' }));
  await waitFor(() => expect(sent(fetchMock, 'GET /api/llm/assignments')).toHaveLength(2));
  await waitFor(() => expect(within(row('어려운 일')).getByRole('combobox', { name: '어려운 일 기준' })).toHaveValue('balanced'));
  expect(within(row('보통 일')).getByRole('combobox', { name: '보통 일 기준' })).toHaveValue('cost');
  expect(within(row('보통 일')).getByRole('button', { name: '저장' })).toBeEnabled();
});

test('a draft pointing at a deleted connection is dropped', async () => {
  const gateway = connection({ id: 2, name: '사내 게이트웨이', provider: 'openai_compatible', is_default: false });
  let conns: Connection[] = [connection(), gateway];
  renderAs('admin', undefined, {
    '/api/llm/connections': () => json(200, conns),
    '/api/llm/connections/2/models': { models: ['gw-small'] },
    'DELETE /api/llm/connections/2': () => {
      conns = [connection()];
      return new Response(null, { status: 204 });
    },
  });
  const light = await screen.findByRole('group', { name: '가벼운 일' });
  await userEvent.selectOptions(within(light).getByRole('combobox', { name: '가벼운 일 연결' }), '2');
  await within(light).findByRole('option', { name: 'gw-small' });
  await userEvent.selectOptions(within(light).getByRole('combobox', { name: '가벼운 일 모델' }), 'gw-small');
  const gw = screen.getByRole('article', { name: '사내 게이트웨이' });
  await userEvent.click(within(gw).getByRole('button', { name: '삭제' }));
  await userEvent.click(within(within(gw).getByRole('group', { name: '연결 삭제 확인' })).getByRole('button', { name: '삭제' }));
  await waitFor(() => expect(within(row('가벼운 일')).getByRole('combobox', { name: '가벼운 일 모델' })).toHaveValue('liner-claude-router'));
  expect(within(row('가벼운 일')).queryByRole('combobox', { name: '가벼운 일 연결' })).toBeNull();
  expect(within(row('가벼운 일')).queryByRole('button', { name: '저장' })).toBeNull();
});

test('a connection without loaded models says to run a test first', async () => {
  renderTable({
    '/api/llm/connections': [connection(), connection({ id: 2, name: '새 연결', is_default: false, status: 'unknown' })],
    '/api/llm/connections/2/models': { models: [] },
  });
  const light = await screen.findByRole('group', { name: '가벼운 일' });
  expect(within(light).queryByText(/불러온 모델이 없습니다/)).toBeNull();
  await userEvent.selectOptions(within(light).getByRole('combobox', { name: '가벼운 일 연결' }), '2');
  expect(await within(light).findByText('이 연결에 불러온 모델이 없습니다. 연결 테스트를 먼저 해 주세요.')).toBeVisible();
});

test('a model list that cannot be loaded shows the server message', async () => {
  renderTable({
    '/api/llm/connections/1/models': () => json(403, { code: 'admin_only', message: '관리자만 할 수 있습니다.', detail: null }),
  });
  const light = await screen.findByRole('group', { name: '가벼운 일' });
  expect(await within(light).findByText('관리자만 할 수 있습니다.')).toBeVisible();
  expect(within(light).getByText('admin_only')).toBeVisible();
});

test('a router row without a stored strategy shows 선택 안 함 and saves what it shows', async () => {
  const { fetchMock } = renderTable({
    '/api/llm/assignments': {
      items: ASSIGNMENTS.items.map((i) => (i.purpose === 'light' ? { ...i, routing_strategy: null } : i)),
    },
    'PUT /api/llm/assignments': (init?: RequestInit) => json(200, JSON.parse(String(init?.body))),
  });
  const light = await screen.findByRole('group', { name: '가벼운 일' });
  const strategy = within(light).getByRole('combobox', { name: '가벼운 일 기준' }) as HTMLSelectElement;
  expect(strategy).toHaveValue('');
  expect(strategy.selectedOptions[0].text).toBe('선택 안 함');
  expect(within(light).queryByRole('button', { name: '저장' })).toBeNull();
  await within(light).findByRole('option', { name: 'liner-gpt-router' });
  await userEvent.selectOptions(within(light).getByRole('combobox', { name: '가벼운 일 모델' }), 'liner-gpt-router');
  const shown = (within(light).getByRole('combobox', { name: '가벼운 일 기준' }) as HTMLSelectElement).value;
  await userEvent.click(within(light).getByRole('button', { name: '저장' }));
  await within(light).findByText('저장했습니다.');
  expect(sent(fetchMock, 'PUT /api/llm/assignments')).toEqual([
    { items: [{ purpose: 'light', connection_id: 1, model: 'liner-gpt-router', routing_strategy: shown === '' ? null : shown }] },
  ]);
});
