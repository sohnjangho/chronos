// 일정 도구 프로그램끼리(스케줄 ↔ 간트차트): 같은 일정을 보는 창은 저장소 하나를 함께 쓴다 —
// 고침·되돌리기·쓰기 줄·고른 액티비티. 프로그램 폴더는 서로 import하지 않으므로 이 시험은 programs 바로 아래에 둔다.
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { useUiContext } from '../os/uiContext';
import { useWindows } from '../os/windowStore';
import { forgetSchedules } from '../shared/schedule/scheduleStore';
import Gantt from './gantt/Gantt';
import { bar, leftRow, setupGantt } from './gantt/testKit';
import ScheduleTable from './schedule-table/ScheduleTable';
import { cell, editCell, loadSpy, makeView, mockPatch, row, rowOrNull, schedule, table, writes } from './schedule-table/testKit';

beforeEach(() => {
  localStorage.clear();
  setupGantt();
});
afterEach(() => {
  forgetSchedules();
  useUiContext.getState().reset();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const ganttTools = () => screen.getByRole('toolbar', { name: '간트 도구' });
const titleOf = (id: string) => useWindows.getState().wins.find((w) => w.id === id)?.title;

/** 스케줄(w1)과 간트차트(w2)를 나란히, 같은 일정 1 로. */
async function openBoth() {
  const table = render(<ScheduleTable windowId="w1" params={{ id: '1' }} />);
  const gantt = render(<Gantt windowId="w2" params={{ id: '1' }} />);
  await screen.findByRole('table', { name: '스케줄표' });
  await screen.findByRole('toolbar', { name: '간트 도구' });
  return { table, gantt };
}

test('both windows read the schedule once and carry their own program name in the title', async () => {
  await openBoth();
  expect(loadSpy).toHaveBeenCalledTimes(1);
  expect(titleOf('w1')).toBe('스케줄 — 5층 사무동 신축');
  expect(titleOf('w2')).toBe('간트차트 — 5층 사무동 신축');
});

test('an edit in the table shows in the gantt without reading the schedule again', async () => {
  await openBoth();
  const next = makeView({ version: 2 });
  next.activities = next.activities.map((a) => (a.id === 'A3010' ? { ...a, od: 40, ef: '2027-09-08', plan_finish: '2027-09-08' } : a));
  const before = Number(bar('A3010')!.getAttribute('width'));
  mockPatch(next);
  await editCell('A3010', 'OD', '40');
  await waitFor(() => expect(within(leftRow('A3010')!).getByText('40')).toBeInTheDocument());
  expect(Number(bar('A3010')!.getAttribute('width'))).toBeGreaterThan(before);
  expect(loadSpy).toHaveBeenCalledTimes(1);
});

test('undo in the gantt undoes the edit made in the table (one history per schedule)', async () => {
  await openBoth();
  mockPatch(makeView({ version: 2 }));
  await editCell('A3010', 'OD', '40');
  const undo = within(ganttTools()).getByRole('button', { name: '되돌리기' });
  await waitFor(() => expect(undo).toBeEnabled());
  await userEvent.click(undo);
  await waitFor(() => expect(writes().at(-1)).toEqual(['POST', '/api/schedules/1/versions/1/restore', { base_version: 2 }]));
  expect(within(screen.getByRole('toolbar', { name: '스케줄표 도구' })).getByRole('button', { name: '다시 하기' })).toBeEnabled();
});

test('picking in the gantt selects, unfolds and scrolls to the row in the table without taking focus', async () => {
  const scroll = vi.fn();
  Element.prototype.scrollIntoView = scroll;
  await openBoth();
  await userEvent.click(within(table()).getByRole('button', { name: '4 마감' }));
  expect(rowOrNull('A4010')).toBeNull();
  await userEvent.click(leftRow('A4010')!);
  expect(leftRow('A4010')).toHaveFocus();
  expect(schedule()).toMatchObject({ selected: 'A4010', selectedBy: 'w2' });
  await waitFor(() => expect(row('A4010')).toHaveAttribute('aria-current', 'true'));
  await waitFor(() => expect(scroll.mock.contexts.at(-1)).toBe(row('A4010')));
  expect(leftRow('A4010')).toHaveFocus();
});

test('picking in the table highlights and unfolds the row in the gantt; the table keeps its own scroll', async () => {
  const scroll = vi.fn();
  Element.prototype.scrollIntoView = scroll;
  await openBoth();
  await userEvent.click(within(leftRow('3')!).getByRole('button', { name: '3 외장·설비' }));
  expect(leftRow('A3020')).toBeNull();
  await userEvent.click(row('A3020'));
  await waitFor(() => expect(leftRow('A3020')).toHaveAttribute('aria-selected', 'true'));
  expect(document.querySelector('[data-sel="A3020"]')).toBeInTheDocument();
  expect(row('A3020')).toHaveFocus();
  expect(scroll).not.toHaveBeenCalled(); // 고른 창은 제 줄로 스크롤하지 않는다(이미 보이는 줄)
});

test('every window publishes the shared selection under its own program id', async () => {
  await openBoth();
  await userEvent.click(row('A2020'));
  await waitFor(() => expect(useUiContext.getState().byWindow.w2).toEqual({ program: 'gantt', schedule_id: 1, selected_activity: 'A2020' }));
  expect(useUiContext.getState().byWindow.w1).toEqual({ program: 'schedule-table', schedule_id: 1, selected_activity: 'A2020' });
});

test('closing the gantt keeps the table, its edits and its history', async () => {
  const { gantt } = await openBoth();
  mockPatch(makeView({ version: 2 }));
  await editCell('A3010', 'OD', '40');
  await waitFor(() => expect(schedule().undo).toHaveLength(1));
  gantt.unmount();
  expect(schedule().view?.version).toBe(2);
  expect(schedule().undo).toHaveLength(1);
  expect(cell('A3010', 'OD')).toBeInTheDocument();
});

// 16b 리뷰 minor 1: 창 안의 동작에서 난 안내(오늘이 기간 밖·선행 칸 틀림 등)는 그 창에만, 서버가 거절한 것은 그 일정의 모든 창에.
test('a notice from an action in one window shows only there; a server rejection shows in every window', async () => {
  const { table: t, gantt: g } = await openBoth();
  await userEvent.click(within(ganttTools()).getByRole('button', { name: '오늘' }));
  expect(within(g.container).getByRole('status')).toHaveTextContent('이 일정 기간 밖입니다');
  expect(within(t.container).queryByRole('status')).toBeNull();
  await editCell('A3010', '선행', 'Z9999');
  expect(within(t.container).getByRole('alert')).toHaveTextContent('Z9999');
  expect(within(g.container).queryByRole('alert')).toBeNull();
  mockPatch(422, { code: 'invalid_activity', message: '실제 종료일이 실제 시작일보다 앞설 수 없습니다.', detail: null });
  await editCell('A3010', 'OD', '40');
  await waitFor(() => expect(within(g.container).getByRole('alert')).toHaveTextContent('실제 종료일이'));
  expect(within(t.container).getByRole('alert')).toHaveTextContent('실제 종료일이');
});

// 16b 리뷰 minor 2: 다른 창에서 같은 액티비티를 다시 고르면 다시 따라간다.
test('picking the same activity again in the other window follows again', async () => {
  const scroll = vi.fn();
  Element.prototype.scrollIntoView = scroll;
  await openBoth();
  await userEvent.click(leftRow('A4010')!);
  await waitFor(() => expect(scroll.mock.contexts.at(-1)).toBe(row('A4010')));
  scroll.mockClear();
  await userEvent.click(leftRow('A4010')!);
  await waitFor(() => expect(scroll).toHaveBeenCalled());
  expect(scroll.mock.contexts.at(-1)).toBe(row('A4010'));
});
