import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { useSchedule } from './scheduleStore';
import { holdNextWrite, loadSpy, makeView, mockPatch, server, setup, writes } from './testKit';

const store = () => useSchedule.getState();

beforeEach(() => setup());
afterEach(() => {
  store().reset();
  vi.unstubAllGlobals();
});

test('load keeps the view and patchActivity replaces it with the server response', async () => {
  await store().load(1);
  expect(store().view?.version).toBe(1);
  mockPatch(makeView({ version: 2, finish: '2027-11-26' }));
  expect(await store().patchActivity('A2020', { od: 52 })).toBe(true);
  expect(store().view).toMatchObject({ version: 2, finish: '2027-11-26' });
});

test('activities that did not change keep their object so their rows need not re-render', async () => {
  await store().load(1);
  const before = store().view!.activities;
  const next = makeView({ version: 2 });
  next.activities[5] = { ...next.activities[5], od: 52 };
  mockPatch(next);
  await store().patchActivity('A2020', { od: 52 });
  const after = store().view!.activities;
  expect(after[5]).not.toBe(before[5]);
  expect(after.filter((a, i) => a === before[i])).toHaveLength(before.length - 1);
});

test('a 422 keeps the view and leaves the server message as an error notice', async () => {
  await store().load(1);
  mockPatch(422, { code: 'invalid_activity', message: '실제 종료일이 실제 시작일보다 앞설 수 없습니다.', detail: null });
  expect(await store().patchActivity('A2020', { actual_finish: '2027-01-01' })).toBe(false);
  expect(store().view?.version).toBe(1);
  expect(store().notice).toEqual({ tone: 'error', text: '실제 종료일이 실제 시작일보다 앞설 수 없습니다.' });
});

test('a 409 reloads with the notice', async () => {
  await store().load(1);
  server.view = makeView({ version: 4 });
  mockPatch(409, { code: 'version_conflict', message: 'x', detail: { current: 4 } });
  expect(await store().setPredecessors('A2020', [{ pred: 'A2010', type: 'FS', lag: 0 }])).toBe(false);
  expect(loadSpy).toHaveBeenCalledTimes(2);
  expect(store().view?.version).toBe(4);
  expect(store().notice).toEqual({ tone: 'info', text: '그 사이 일정이 바뀌어 다시 불러왔습니다' });
});

test('writes queued before reset are dropped', async () => {
  await store().load(1);
  const release = holdNextWrite();
  const first = store().patchActivity('A2020', { od: 52 });
  const second = store().patchActivity('A3010', { od: 36 });
  await vi.waitFor(() => expect(writes()).toHaveLength(1)); // 첫 요청은 가는 중
  store().reset();
  release(makeView({ version: 2 }));
  expect(await first).toBe(false);
  expect(await second).toBe(false);
  expect(writes()).toHaveLength(1);
  expect(store().view).toBeNull();
});

test('an old load answer does not replace a newer schedule', async () => {
  let answer!: (r: Response) => void;
  const slow = new Promise<Response>((ok) => (answer = ok));
  const other = makeView({ id: 2, name: '물류센터 증축' });
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => (url === '/api/schedules/1' ? slow : Promise.resolve(new Response(JSON.stringify(other), { status: 200 })))),
  );
  const first = store().load(1);
  await store().load(2);
  answer(new Response(JSON.stringify(makeView()), { status: 200 }));
  await first;
  expect(store().view?.name).toBe('물류센터 증축');
});

test('selecting an activity that is deleted clears the selection', async () => {
  await store().load(1);
  store().select('A3030');
  const next = makeView({ version: 2 });
  next.activities = next.activities.filter((a) => a.id !== 'A3030');
  mockPatch(next);
  await store().deleteActivity('A3030');
  expect(store().selected).toBeNull();
});
