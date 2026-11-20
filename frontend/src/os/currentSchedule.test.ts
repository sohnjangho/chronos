import { afterEach, beforeEach, expect, test, vi } from 'vitest';

async function fresh() {
  vi.resetModules();
  return import('./currentSchedule');
}

beforeEach(() => localStorage.clear());
afterEach(() => vi.restoreAllMocks());

test('the current schedule is stored per user and restored for that user only', async () => {
  const { useCurrentSchedule } = await fresh();
  useCurrentSchedule.getState().load(1);
  expect(useCurrentSchedule.getState().current).toBeNull();
  useCurrentSchedule.getState().setCurrent({ id: 4, name: '5층 사무동 신축' });
  expect(JSON.parse(localStorage.getItem('chronos.schedule.1')!)).toEqual({ id: 4, name: '5층 사무동 신축' });
  useCurrentSchedule.getState().load(2);
  expect(useCurrentSchedule.getState().current).toBeNull();
  useCurrentSchedule.getState().load(1);
  expect(useCurrentSchedule.getState().current).toEqual({ id: 4, name: '5층 사무동 신축' });
  useCurrentSchedule.getState().setCurrent(null);
  expect(localStorage.getItem('chronos.schedule.1')).toBeNull();
  useCurrentSchedule.getState().load(null);
  expect(useCurrentSchedule.getState().current).toBeNull();
});

test('a broken stored value is ignored', async () => {
  localStorage.setItem('chronos.schedule.1', JSON.stringify({ id: 'x' }));
  const { useCurrentSchedule } = await fresh();
  useCurrentSchedule.getState().load(1);
  expect(useCurrentSchedule.getState().current).toBeNull();
});

test('the current schedule works in memory when storage throws', async () => {
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
    throw new Error('denied');
  });
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new Error('denied');
  });
  const { useCurrentSchedule } = await fresh();
  useCurrentSchedule.getState().load(1);
  useCurrentSchedule.getState().setCurrent({ id: 1, name: '가' });
  expect(useCurrentSchedule.getState().current).toEqual({ id: 1, name: '가' });
});
