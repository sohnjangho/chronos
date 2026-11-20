import { beforeEach, expect, test } from 'vitest';
import { resetShellState } from './shellReset';
import { useSchedulePreview, type PreviewView, type SchedulePreview } from './schedulePreview';

const view = (id: number): PreviewView => ({
  id,
  name: '5층 사무동 신축',
  domain: 'construction',
  level: 'L3',
  version: 3,
  data_date: null,
  finish: '2027-11-12',
  plan_finish: '2027-11-24',
  wbs: [],
  activities: [],
  relations: [],
  resources: [],
  summary: { critical_count: 0, negative_float_count: 0, warning_count: 0 },
});

const preview = (scheduleId: number): SchedulePreview => ({
  scheduleId,
  view: view(scheduleId),
  moved: [{ activity_id: 'A3010', name: '지상 골조', before: { start: '2027-06-07', finish: '2027-07-16' }, after: { start: '2027-04-26', finish: '2027-06-04' } }],
  source: 'conditions',
});

beforeEach(() => useSchedulePreview.getState().reset());

test('set keeps one preview per schedule and clear removes only that schedule', () => {
  const s = useSchedulePreview.getState();
  s.set(preview(1));
  s.set(preview(2));
  expect(useSchedulePreview.getState().previews[1]?.moved[0].activity_id).toBe('A3010');
  useSchedulePreview.getState().clear(1);
  expect(useSchedulePreview.getState().previews[1]).toBeUndefined();
  expect(useSchedulePreview.getState().previews[2]?.view.id).toBe(2);
});

test('a newer preview of the same schedule replaces the older one', () => {
  useSchedulePreview.getState().set(preview(1));
  useSchedulePreview.getState().set({ ...preview(1), moved: [] });
  expect(useSchedulePreview.getState().previews[1]?.moved).toEqual([]);
});

test('clearing a schedule without a preview changes nothing', () => {
  useSchedulePreview.getState().set(preview(2));
  const before = useSchedulePreview.getState().previews;
  useSchedulePreview.getState().clear(9);
  expect(useSchedulePreview.getState().previews).toBe(before);
});

test('logout (resetShellState) drops every preview', () => {
  useSchedulePreview.getState().set(preview(1));
  resetShellState();
  expect(useSchedulePreview.getState().previews).toEqual({});
});

test('the delay window can hold a preview too and its source says so', () => {
  useSchedulePreview.getState().set({ ...preview(1), source: 'delays' });
  expect(useSchedulePreview.getState().previews[1]?.source).toBe('delays');
});
