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

// fix 1 I2: 보낼 값은 차례가 왔을 때의 일정으로 만든다. 409 뒤에는 줄 서 있던 쓰기를 보내지 않는다.
test('a predecessor payload function runs when its turn comes, on the newest view', async () => {
  await store().load(1);
  const release = holdNextWrite();
  const first = store().setPredecessors('A2020', [{ pred: 'A1040', type: 'FS', lag: 0 }]);
  const seen: string[][] = [];
  const second = store().setPredecessors('A2020', (view) => {
    const items = view.relations.filter((r) => r.succ === 'A2020').map(({ pred, type, lag }) => ({ pred, type, lag }));
    seen.push(items.map((i) => i.pred));
    return items.filter((i) => i.pred !== 'A1040');
  });
  await vi.waitFor(() => expect(writes()).toHaveLength(1));
  const next = makeView({ version: 2 });
  next.relations = next.relations.filter((r) => !(r.succ === 'A2020' && r.pred === 'A2010'));
  release(next);
  expect(await first).toBe(true);
  expect(await second).toBe(true);
  expect(seen).toEqual([['A1040']]);
  expect(writes()[1][2]).toEqual({ items: [], base_version: 2 });
});

test('a payload function may return null to send nothing', async () => {
  await store().load(1);
  expect(await store().setPredecessors('A2020', () => null)).toBe(false);
  expect(writes()).toEqual([]);
});

test('after a 409 the writes queued behind it are dropped and the notice stays', async () => {
  await store().load(1);
  server.view = makeView({ version: 4 });
  mockPatch(409, { code: 'version_conflict', message: 'x', detail: { current: 4 } });
  const first = store().patchActivity('A2020', { od: 52 });
  const second = store().patchActivity('A3010', { od: 36 });
  expect(await first).toBe(false);
  expect(await second).toBe(false);
  expect(writes()).toHaveLength(1);
  expect(store().notice).toEqual({ tone: 'info', text: '그 사이 일정이 바뀌어 다시 불러왔습니다' });
  expect(await store().patchActivity('A3010', { od: 36 })).toBe(true); // 다시 불러온 뒤의 새 고침은 간다
  expect(writes()[1][2]).toEqual({ od: 36, base_version: 4 });
});

// fix 1 I3: 여러 단계 되돌리기·다시 하기.
test('two edits can be undone twice and redone twice', async () => {
  await store().load(1);
  await store().patchActivity('A2020', { od: 52 }); // 1 → 2
  await store().patchActivity('A3010', { od: 36 }); // 2 → 3
  expect(await store().undoLast()).toBe(true); // 3 → 4 (= 2)
  expect(await store().undoLast()).toBe(true); // 4 → 5 (= 1)
  expect(await store().redoLast()).toBe(true); // 5 → 6 (= 2)
  expect(await store().redoLast()).toBe(true); // 6 → 7 (= 3)
  const restores = writes().filter(([, url]) => url.includes('/restore')).map(([, url, body]) => [url, body]);
  expect(restores).toEqual([
    ['/api/schedules/1/versions/2/restore', { base_version: 3 }],
    ['/api/schedules/1/versions/1/restore', { base_version: 4 }],
    ['/api/schedules/1/versions/4/restore', { base_version: 5 }],
    ['/api/schedules/1/versions/3/restore', { base_version: 6 }],
  ]);
  expect(store().redo).toEqual([]);
  expect(await store().undoLast()).toBe(true); // 다시 되돌릴 수 있다(7 → 8)
});

test('undo still refuses when someone else changed the schedule in between', async () => {
  await store().load(1);
  await store().patchActivity('A2020', { od: 52 }); // 1 → 2
  server.view = makeView({ version: 5 });
  await store().load(1); // 다른 사람이 고침 → 5
  expect(await store().undoLast()).toBe(false);
  expect(writes().filter(([, url]) => url.includes('/restore'))).toEqual([]);
});
