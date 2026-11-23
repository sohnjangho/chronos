import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { forgetSchedules, holdSchedule, scheduleStore } from './scheduleStore';
import { holdNextWrite, loadSpy, makeView, mockPatch, mockWeightMode, server, setup, writes } from './testKit';

const store = () => scheduleStore(1).getState();

beforeEach(() => setup());
afterEach(() => {
  forgetSchedules();
  vi.unstubAllGlobals();
});

test('load keeps the view and patchActivity replaces it with the server response', async () => {
  await store().load();
  expect(store().view?.version).toBe(1);
  mockPatch(makeView({ version: 2, finish: '2027-11-26' }));
  expect(await store().patchActivity('A2020', { od: 52 })).toBe(true);
  expect(store().view).toMatchObject({ version: 2, finish: '2027-11-26' });
});

test('activities that did not change keep their object so their rows need not re-render', async () => {
  await store().load();
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
  await store().load();
  mockPatch(422, { code: 'invalid_activity', message: '실제 종료일이 실제 시작일보다 앞설 수 없습니다.', detail: null });
  expect(await store().patchActivity('A2020', { actual_finish: '2027-01-01' })).toBe(false);
  expect(store().view?.version).toBe(1);
  expect(store().notice).toEqual({ tone: 'error', text: '실제 종료일이 실제 시작일보다 앞설 수 없습니다.' });
});

test('a 409 reloads with the notice', async () => {
  await store().load();
  server.view = makeView({ version: 4 });
  mockPatch(409, { code: 'version_conflict', message: 'x', detail: { current: 4 } });
  expect(await store().setPredecessors('A2020', [{ pred: 'A2010', type: 'FS', lag: 0 }])).toBe(false);
  expect(loadSpy).toHaveBeenCalledTimes(2);
  expect(store().view?.version).toBe(4);
  expect(store().notice).toEqual({ tone: 'info', text: '그 사이 일정이 바뀌어 다시 불러왔습니다' });
});

test('writes queued before reset are dropped', async () => {
  await store().load();
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

// 일정 저장소는 일정 id 마다 하나다. 같은 일정을 보는 창들(스케줄·간트차트·…)이 고침·되돌리기·쓰기 줄을 함께 쓴다.
test('every schedule id has one store of its own', async () => {
  expect(scheduleStore(1)).toBe(scheduleStore(1));
  expect(scheduleStore(2)).not.toBe(scheduleStore(1));
  expect(scheduleStore(2).getState().scheduleId).toBe(2);
  await store().load();
  store().select('A2020', 'w1');
  expect(scheduleStore(2).getState()).toMatchObject({ view: null, selected: null });
});

test('a store held by two windows lives on when one lets go and is emptied when the last one does', async () => {
  const s = scheduleStore(1);
  const releaseTable = holdSchedule(s, 'w1');
  const releaseGantt = holdSchedule(s, 'w2');
  await s.getState().load();
  releaseTable();
  expect(scheduleStore(1)).toBe(s);
  expect(await s.getState().patchActivity('A2020', { od: 52 })).toBe(true);
  expect(s.getState().undo).toHaveLength(1);
  const release = holdNextWrite();
  const queued = s.getState().patchActivity('A3010', { od: 36 });
  await vi.waitFor(() => expect(writes()).toHaveLength(2));
  releaseGantt();
  release(makeView({ version: 3 }));
  expect(await queued).toBe(false);
  expect(s.getState().view).toBeNull();
  expect(scheduleStore(1)).not.toBe(s);
});

test('holding again with the same store keeps it (StrictMode runs effects twice)', () => {
  const s = scheduleStore(1);
  holdSchedule(s, 'w1')();
  const release = holdSchedule(s, 'w1');
  expect(scheduleStore(1)).toBe(s);
  release();
});

test('select remembers which window chose, so the other windows can follow', () => {
  store().select('A2020', 'w2');
  expect(store()).toMatchObject({ selected: 'A2020', selectedBy: 'w2' });
  store().revealActivity('A3010', 'w1');
  expect(store()).toMatchObject({ selected: 'A3010', selectedBy: 'w1', reveal: { aid: 'A3010', by: 'w1' } });
  store().select(null);
  expect(store()).toMatchObject({ selected: null, selectedBy: null });
});

test('selecting an activity that is deleted clears the selection', async () => {
  await store().load();
  store().select('A3030');
  const next = makeView({ version: 2 });
  next.activities = next.activities.filter((a) => a.id !== 'A3030');
  mockPatch(next);
  await store().deleteActivity('A3030');
  expect(store().selected).toBeNull();
});

// fix 1 I2: 보낼 값은 차례가 왔을 때의 일정으로 만든다. 409 뒤에는 줄 서 있던 쓰기를 보내지 않는다.
test('a predecessor payload function runs when its turn comes, on the newest view', async () => {
  await store().load();
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
  await store().load();
  expect(await store().setPredecessors('A2020', () => null)).toBe(false);
  expect(writes()).toEqual([]);
});

test('after a 409 the writes queued behind it are dropped and the notice stays', async () => {
  await store().load();
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
  await store().load();
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
  await store().load();
  await store().patchActivity('A2020', { od: 52 }); // 1 → 2
  server.view = makeView({ version: 5 });
  await store().load(); // 다른 사람이 고침 → 5
  expect(await store().undoLast()).toBe(false);
  expect(writes().filter(([, url]) => url.includes('/restore'))).toEqual([]);
});

test('setDataDate patches the schedule with base_version and can be undone like any change', async () => {
  await store().load();
  mockPatch(makeView({ version: 2, data_date: '2027-06-08' }));
  expect(await store().setDataDate('2027-06-08')).toBe(true);
  expect(writes().at(-1)).toEqual(['PATCH', '/api/schedules/1', { data_date: '2027-06-08', base_version: 1 }]);
  expect(store().view?.data_date).toBe('2027-06-08');
  expect(store().undo).toEqual([{ restore: 1, expect: 2, note: '' }]);
});

test('setWeightMode puts the mode and reads the schedule again (the version does not move)', async () => {
  await store().load();
  mockWeightMode('manual', makeView({ weight_mode: 'manual', summary: { critical_count: 8, negative_float_count: 0, warning_count: 1, weight_missing: 2 } }));
  expect(await store().setWeightMode('manual')).toBe(true);
  expect(writes().at(-1)).toEqual(['PUT', '/api/schedules/1/weight-mode', { mode: 'manual' }]);
  expect(loadSpy).toHaveBeenCalledTimes(2);
  expect(store().view).toMatchObject({ version: 1, weight_mode: 'manual', summary: { weight_missing: 2 } });
});

test('a refused weight mode leaves the server message', async () => {
  await store().load();
  mockPatch(422, { code: 'invalid_request', message: '입력이 올바르지 않습니다.', detail: null });
  expect(await store().setWeightMode('manual')).toBe(false);
  expect(store().notice).toEqual({ tone: 'error', text: '입력이 올바르지 않습니다.' });
  expect(loadSpy).toHaveBeenCalledTimes(1);
});

test('a write that moves the version is kept as the last change (with the edited activity)', async () => {
  await store().load();
  const before = store().view;
  mockPatch(makeView({ version: 2 }));
  await store().patchActivity('A2020', { progress: 0.2 });
  expect(store().lastChange).toMatchObject({ before, after: { version: 2 }, aid: 'A2020' });
  mockPatch(makeView({ version: 3, data_date: '2027-06-08' }));
  await store().setDataDate('2027-06-08');
  expect(store().lastChange).toMatchObject({ after: { version: 3 }, aid: null });
});

test('a reload takes the last change away (409 refetch or a version from elsewhere)', async () => {
  await store().load();
  mockPatch(makeView({ version: 2 }));
  await store().patchActivity('A2020', { progress: 0.2 });
  expect(store().lastChange).not.toBeNull();
  server.view = makeView({ version: 5 });
  await store().load();
  expect(store().lastChange).toBeNull();
  mockPatch(makeView({ version: 6 }));
  await store().patchActivity('A2020', { progress: 0.3 });
  mockPatch(409, { code: 'version_conflict', message: 'x', detail: { current: 7 } });
  await store().patchActivity('A2020', { progress: 0.4 });
  expect(store().lastChange).toBeNull();
});

// 리뷰 W1: 늦게 온 읽기 답이 이미 가진 것보다 낮은 버전이면 버린다(새 버전을 옛 것으로 덮지 않는다).
test('a read answer older than the held version is ignored', async () => {
  await store().load();
  scheduleStore(1).setState({ view: makeView({ version: 3, finish: '2027-10-29' }) }); // 그 사이 쓰기가 버전 3을 돌려줬다
  server.view = makeView({ version: 2 });
  await store().load();
  expect(store().view).toMatchObject({ version: 3, finish: '2027-10-29' });
});
