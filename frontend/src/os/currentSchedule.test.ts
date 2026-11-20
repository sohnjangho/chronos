import { afterEach, beforeEach, expect, test, vi } from 'vitest';

const KEY = 'chronos.schedule';

async function fresh() {
  vi.resetModules();
  return import('./currentSchedule');
}

beforeEach(() => localStorage.clear());
afterEach(() => vi.restoreAllMocks());

test('current schedule is persisted and restored', async () => {
  const first = await fresh();
  expect(first.useCurrentSchedule.getState().current).toBeNull();
  first.useCurrentSchedule.getState().setCurrent({ id: 4, name: '5층 사무동 신축' });
  const again = await fresh();
  expect(again.useCurrentSchedule.getState().current).toEqual({ id: 4, name: '5층 사무동 신축' });
  again.useCurrentSchedule.getState().setCurrent(null);
  expect(localStorage.getItem(KEY)).toBeNull();
});

test('current schedule works in memory when storage throws', async () => {
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
    throw new Error('denied');
  });
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new Error('denied');
  });
  const { useCurrentSchedule } = await fresh();
  useCurrentSchedule.getState().setCurrent({ id: 1, name: '가' });
  expect(useCurrentSchedule.getState().current).toEqual({ id: 1, name: '가' });
});
