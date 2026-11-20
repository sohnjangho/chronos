import { waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { memo, type ComponentType, type ReactNode } from 'react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import type { ScheduleView } from '../../shared/schedule/scheduleApi';
import { forgetSchedules } from '../../shared/schedule/scheduleStore';
import { activity, cell, editCell, makeView, mockPatch, renderSchedule, row, schedule, setup, table } from './testKit';

// R7: 액티비티 행이 몇 번 그려지는지 센다. Row 의 memo 비교는 그대로 두고 그리는 함수만 감싼다.
const renders: string[] = [];
vi.mock('./Row', async (importOriginal) => {
  const mod = await importOriginal<typeof import('./Row')>();
  const original = mod.default as unknown as { type: ComponentType<{ activity: { id: string } }>; compare?: null | ((a: object, b: object) => boolean) };
  const Inner = original.type as unknown as (p: { activity: { id: string } }) => ReactNode;
  const Counting = memo((p: { activity: { id: string } }) => {
    renders.push(p.activity.id);
    return Inner(p);
  }, original.compare ?? undefined);
  return { ...mod, default: Counting };
});

/** 가상 일정 200개 액티비티: WBS 10묶음 × 20, 묶음 안은 앞 액티비티가 선행. */
function bigView(version = 1): ScheduleView {
  const base = makeView({ version });
  const wbs = Array.from({ length: 10 }, (_, g) => ({ code: String(g + 1), name: `${g + 1}공구`, parent: null }));
  const activities = wbs.flatMap((w, g) =>
    Array.from({ length: 20 }, (_, i) =>
      activity([`B${g + 1}${String(i).padStart(3, '0')}`, `${w.name} 작업 ${i + 1}`, 'task', w.code, 5, null, '2027-03-02', '2027-03-08', null, null, 0, 'on_plan', i % 3, 0]),
    ),
  );
  const relations = activities.slice(1).map((a, i) => ({ pred: activities[i].id, succ: a.id, type: 'FS' as const, lag: 0 }));
  return { ...base, wbs, activities, relations };
}

beforeEach(() => {
  localStorage.clear();
  setup(bigView());
});
afterEach(() => {
  forgetSchedules();
  vi.unstubAllGlobals();
});

test('200 activities are all in the table', async () => {
  await renderSchedule();
  expect(within(table()).getAllByRole('row').filter((r) => r.getAttribute('data-key')?.startsWith('B'))).toHaveLength(200);
});

test('editing one cell re-renders only the rows whose data changed', async () => {
  await renderSchedule();
  renders.length = 0;
  const next = bigView(2);
  next.activities[45] = { ...next.activities[45], od: 6 };
  mockPatch(next);
  await editCell('B3005', 'OD', '6');
  await waitFor(() => expect(schedule().view?.version).toBe(2));
  expect(new Set(renders)).toEqual(new Set(['B3005']));
  expect(cell('B3005', 'OD')).toHaveTextContent('6');
});

test('changing the selection re-renders only the two rows involved', async () => {
  await renderSchedule();
  await userEvent.click(row('B1001'));
  renders.length = 0;
  await userEvent.click(row('B5010'));
  expect(new Set(renders)).toEqual(new Set(['B1001', 'B5010']));
});
