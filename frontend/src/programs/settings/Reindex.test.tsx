// 임베딩 모델 바꾸기 확인 창과 다시 넣기 상태(GET/POST /api/files/reindex).
import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';
import { json } from '../../test-helpers';
import { ASSIGNMENTS, connection, info, MODELS, renderAs, resetAll, sent } from './testKit';

afterEach(() => {
  vi.useRealTimers();
  resetAll();
});

const SMALL = { ...info('embedco/vector-small', 'Embed: Vector Small', 'embedco', 8192, false), price: { kind: 'model' as const, as_of: '2026-11-18', input: 0.02, output: 0, cached_input: 0 } };
const LARGE = { ...info('embedco/vector-large', 'Embed: Vector Large', 'embedco', 8192, false), price: { kind: 'model' as const, as_of: '2026-11-18', input: 0.13, output: 0, cached_input: 0 } };
const EMBEDDINGS = [SMALL, LARGE];
const EMBED_ROW = { purpose: 'embedding', connection_id: 1, model: SMALL.id, routing_strategy: null };
const SIX = {
  items: [...ASSIGNMENTS.items, { purpose: 'vision', connection_id: 1, model: 'liner-mark', routing_strategy: null }, EMBED_ROW],
};

type Job = { id: number; model: string; status: 'running' | 'done' | 'failed'; total: number; done: number; started_at: string; finished_at: string | null };
const job = (over: Partial<Job> = {}): Job => ({
  id: 7, model: SMALL.id, status: 'done', total: 5830, done: 5830, started_at: '2026-11-20T09:00:00', finished_at: '2026-11-20T09:07:00', ...over,
});
const state = (active: string, assigned: string, j: Job | null) => ({ active_model: active, assigned_model: assigned, job: j });
const SETTLED = state(SMALL.id, SMALL.id, job());

function renderSix(over = {}) {
  return renderAs('admin', { section: 'assign' }, {
    '/api/llm/connections': [connection()],
    '/api/llm/connections/1/models': { models: [...MODELS, ...EMBEDDINGS] },
    '/api/llm/models?for=embedding': { connections: [{ connection_id: 1, name: 'Liner 기본', is_default: true, models: EMBEDDINGS }] },
    '/api/llm/assignments': SIX,
    '/api/files/reindex': SETTLED,
    ...over,
  });
}

const panel = () => screen.findByRole('region', { name: '임베딩 다시 넣기' });
const statusCalls = (fetchMock: ReturnType<typeof renderSix>['fetchMock']) => sent(fetchMock, 'GET /api/files/reindex').length;

async function pickLarge() {
  const emb = await screen.findByRole('group', { name: '임베딩' });
  const model = await within(emb).findByRole('combobox', { name: '임베딩 모델' });
  await waitFor(() => expect(within(model).getByRole('option', { name: /Vector Large/ })).toBeInTheDocument());
  await userEvent.selectOptions(model, LARGE.id);
  await userEvent.click(within(emb).getByRole('button', { name: '저장' }));
  return emb;
}

// ── 확인 창 ──

test('saving a new embedding model asks first and sends nothing until confirmed', async () => {
  const { fetchMock } = renderSix();
  await pickLarge();
  const dialog = screen.getByRole('alertdialog', { name: '임베딩 모델을 바꿀까요?' });
  // 자료·조각 수를 주는 API 가 없어 수는 빼고 말한다.
  expect(dialog).toHaveTextContent('자료를 새 모델로 다시 넣습니다.');
  expect(dialog).not.toHaveTextContent(/자료 \d+개/);
  expect(dialog).toHaveTextContent(SMALL.id);
  expect(dialog).toHaveTextContent(LARGE.id);
  expect(dialog).toHaveTextContent('입력 $0.13 / 출력 $0 (1M 토큰)');
  expect(dialog).toHaveTextContent('Liner 공개 가격표(2026-11-18)');
  expect(sent(fetchMock, 'PUT /api/llm/assignments')).toEqual([]);
  await userEvent.click(within(dialog).getByRole('button', { name: '취소' }));
  expect(screen.queryByRole('alertdialog')).toBeNull();
  expect(sent(fetchMock, 'PUT /api/llm/assignments')).toEqual([]);
});

test('confirming puts the assignment and reloads the re-index state', async () => {
  let status: object = SETTLED;
  const { fetchMock } = renderSix({
    '/api/files/reindex': () => json(200, status),
    'PUT /api/llm/assignments': () => {
      status = state(SMALL.id, LARGE.id, job({ id: 8, model: LARGE.id, status: 'running', total: 5830, done: 0, finished_at: null }));
      return json(200, { items: SIX.items.map((i) => (i.purpose === 'embedding' ? { ...i, model: LARGE.id } : i)), reindex: { job_id: 8, total: 5830 } });
    },
  });
  await pickLarge();
  await userEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: '다시 넣기 시작' }));
  await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
  expect(sent(fetchMock, 'PUT /api/llm/assignments')).toEqual([{ items: [{ ...EMBED_ROW, model: LARGE.id }] }]);
  expect(await within(await panel()).findByRole('progressbar', { name: '다시 넣기 진행' })).toBeVisible();
});

test('a 409 while re-indexing says so', async () => {
  renderSix({
    'PUT /api/llm/assignments': () => json(409, { code: 'already_running', message: '이미 다시 넣는 중이라 임베딩 모델을 바꾸지 않았습니다. 끝난 뒤 다시 해 주세요.', detail: null }),
  });
  const emb = await pickLarge();
  await userEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: '다시 넣기 시작' }));
  expect(await within(emb).findByText(/이미 다시 넣는 중입니다/)).toBeVisible();
});

test('a 503 on save is a state line, not an error', async () => {
  renderSix({
    'PUT /api/llm/assignments': () => json(503, { code: 'reindex_unavailable', message: '다시 넣기를 시작할 수 없어 임베딩 모델을 바꾸지 않았습니다.', detail: null }),
  });
  const emb = await pickLarge();
  await userEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: '다시 넣기 시작' }));
  const line = await within(emb).findByText(/뜻 검색 서버가 꺼져 있어 낱말 검색만 씁니다/);
  expect(line.closest('[role="alert"]')).toBeNull();
  expect(line.closest('[role="status"]')).not.toBeNull();
});

test('other rows still save without asking', async () => {
  const { fetchMock } = renderSix({ 'PUT /api/llm/assignments': { items: SIX.items } });
  const vision = await screen.findByRole('group', { name: '그림 읽기' });
  const model = await within(vision).findByRole('combobox', { name: '그림 읽기 모델' });
  await userEvent.selectOptions(model, 'liner-gpt-router');
  await userEvent.click(within(vision).getByRole('button', { name: '저장' }));
  expect(screen.queryByRole('alertdialog')).toBeNull();
  await waitFor(() => expect(sent(fetchMock, 'PUT /api/llm/assignments')).toHaveLength(1));
});

// ── 다시 넣기 상태 ──

test('the state shows the model in use and the assigned model', async () => {
  renderSix({ '/api/files/reindex': state(SMALL.id, LARGE.id, null) });
  const box = await panel();
  expect(await within(box).findByText(SMALL.id)).toBeVisible();
  expect(within(box).getByText(LARGE.id)).toBeVisible();
  expect(within(box).getByText('지금 찾기 모델')).toBeVisible();
  expect(within(box).getByText('배정한 모델')).toBeVisible();
});

test('a running job shows progress, polls every 3 seconds and stops when done', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const answers = [
    state(SMALL.id, LARGE.id, job({ model: LARGE.id, status: 'running', total: 200, done: 50, finished_at: null })),
    state(SMALL.id, LARGE.id, job({ model: LARGE.id, status: 'running', total: 200, done: 150, finished_at: null })),
    state(LARGE.id, LARGE.id, job({ model: LARGE.id, status: 'done', total: 200, done: 200 })),
  ];
  let n = 0;
  const { fetchMock } = renderSix({ '/api/files/reindex': () => json(200, answers[Math.min(n++, answers.length - 1)]) });
  const box = await panel();
  const bar = await within(box).findByRole('progressbar', { name: '다시 넣기 진행' });
  expect(bar).toHaveAttribute('aria-valuenow', '50');
  expect(bar).toHaveAttribute('aria-valuemax', '200');
  expect(box).toHaveTextContent('50 / 200 조각');
  expect(box).toHaveTextContent('25%');
  expect(within(box).queryByRole('button', { name: '다시 시작' })).toBeNull();
  const first = statusCalls(fetchMock);

  await act(() => vi.advanceTimersByTimeAsync(2900));
  expect(statusCalls(fetchMock)).toBe(first);
  await act(() => vi.advanceTimersByTimeAsync(200));
  await waitFor(() => expect(within(box).getByRole('progressbar')).toHaveAttribute('aria-valuenow', '150'));
  expect(statusCalls(fetchMock)).toBe(first + 1);

  await act(() => vi.advanceTimersByTimeAsync(3000));
  await waitFor(() => expect(within(box).queryByRole('progressbar')).toBeNull());
  const finished = statusCalls(fetchMock);
  await act(() => vi.advanceTimersByTimeAsync(9000));
  expect(statusCalls(fetchMock)).toBe(finished);
  expect(within(box).queryByRole('button', { name: '다시 시작' })).toBeNull();
});

test('a running job names the four steps', async () => {
  renderSix({ '/api/files/reindex': state(SMALL.id, LARGE.id, job({ model: LARGE.id, status: 'running', total: 200, done: 50, finished_at: null })) });
  const steps = await within(await panel()).findByRole('list', { name: '다시 넣기 단계' });
  expect(within(steps).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
    expect.stringContaining('새 모음 만들기'),
    expect.stringContaining('다시 넣기'),
    expect.stringContaining('찾기를 새 모델로'),
    expect.stringContaining('옛 모음 지우기'),
  ]);
});

test('restart shows for a failed job and posts', async () => {
  let status: object = state(SMALL.id, LARGE.id, job({ model: LARGE.id, status: 'failed', total: 200, done: 80 }));
  const { fetchMock } = renderSix({
    '/api/files/reindex': () => json(200, status),
    'POST /api/files/reindex': () => {
      status = state(SMALL.id, LARGE.id, job({ id: 9, model: LARGE.id, status: 'running', total: 200, done: 0, finished_at: null }));
      return json(202, { job_id: 9, total: 200 });
    },
  });
  const box = await panel();
  expect(await within(box).findByText(/다시 넣기에 실패했습니다/)).toBeVisible();
  await userEvent.click(within(box).getByRole('button', { name: '다시 시작' }));
  expect(sent(fetchMock, 'POST /api/files/reindex')).toHaveLength(1);
  expect(await within(box).findByRole('progressbar', { name: '다시 넣기 진행' })).toBeVisible();
});

test('restart shows when the assigned model is not in use and nothing runs', async () => {
  renderSix({ '/api/files/reindex': state(SMALL.id, LARGE.id, job()) });
  expect(await within(await panel()).findByRole('button', { name: '다시 시작' })).toBeVisible();
});

test('no restart when the assigned model is in use', async () => {
  renderSix();
  const box = await panel();
  await within(box).findByText('지금 찾기 모델');
  expect(within(box).queryByRole('button', { name: '다시 시작' })).toBeNull();
});

test('restart 503 is a state line, not an error', async () => {
  renderSix({
    '/api/files/reindex': state(SMALL.id, LARGE.id, null),
    'POST /api/files/reindex': () => json(503, { code: 'reindex_unavailable', message: '뜻 검색이 꺼져 있습니다.', detail: null }),
  });
  const box = await panel();
  await userEvent.click(await within(box).findByRole('button', { name: '다시 시작' }));
  const line = await within(box).findByText('뜻 검색 서버가 꺼져 있어 낱말 검색만 씁니다.');
  expect(line.closest('[role="status"]')).not.toBeNull();
  expect(within(box).queryByRole('alert')).toBeNull();
});

test('restart 409 says it is already running', async () => {
  renderSix({
    '/api/files/reindex': state(SMALL.id, LARGE.id, null),
    'POST /api/files/reindex': () => json(409, { code: 'already_running', message: '이미 다시 넣는 중입니다.', detail: null }),
  });
  const box = await panel();
  await userEvent.click(await within(box).findByRole('button', { name: '다시 시작' }));
  expect(await within(box).findByText(/이미 다시 넣는 중입니다/)).toBeVisible();
});

test('without the embedding row there is no re-index state', async () => {
  const { fetchMock } = renderAs('admin', { section: 'assign' }, { '/api/llm/connections': [connection()] });
  await screen.findByRole('group', { name: '가벼운 일' });
  expect(screen.queryByRole('region', { name: '임베딩 다시 넣기' })).toBeNull();
  expect(statusCalls(fetchMock)).toBe(0);
});
