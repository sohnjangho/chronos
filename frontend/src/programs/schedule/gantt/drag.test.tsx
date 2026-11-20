// 직접 고치기(R8): 막대 끝 끌기 → OD, 막대 끌기 → SNET, 두 번 누르기 → 표와 같은 칸 편집기. 모두 일정판 쓰기 줄로.
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test } from 'vitest';
import { useSchedulePreview } from '../../../os/schedulePreview';
import { CONFLICT_NOTICE, useSchedule } from '../scheduleStore';
import { holdNextWrite, makeView, mockPatch, writes } from '../testKit';
import { bar, handle, leftRow, pxPerDay, renderGantt, setupGantt } from './testKit';

beforeEach(() => setupGantt());
afterEach(() => {
  useSchedule.getState().reset();
  useSchedulePreview.getState().reset();
});

/** 요소를 누르고 dx 만큼 옮겨 놓는다(중간에 한 번 멈춤). */
function drag(el: Element | null, dx: number) {
  fireEvent.pointerDown(el!, { clientX: 400, button: 0 });
  fireEvent.pointerMove(document.body, { clientX: 400 + dx / 2 });
  fireEvent.pointerMove(document.body, { clientX: 400 + dx });
  fireEvent.pointerUp(document.body, { clientX: 400 + dx });
}

const withActivity = (aid: string, over: object) =>
  makeView({ activities: makeView().activities.map((a) => (a.id === aid ? { ...a, ...over } : a)) });

test('dragging the right edge sets OD in whole workdays (this bar’s workdays per day) through the queue', async () => {
  await renderGantt();
  drag(handle('A3010'), 14 * pxPerDay()); // A3010: OD 35 = 7.15~9.01(49일) → 14일 = 10 근무일
  await waitFor(() => expect(writes()).toEqual([['PATCH', '/api/schedules/1/activities/A3010', { od: 45, base_version: 1 }]]));
});

test('while dragging the edge the new OD and a dashed outline are shown; release without change sends nothing', async () => {
  await renderGantt();
  fireEvent.pointerDown(handle('A3010')!, { clientX: 400, button: 0 });
  fireEvent.pointerMove(document.body, { clientX: 400 + 7 * pxPerDay() });
  expect(screen.getByText('OD 35 → 40')).toBeInTheDocument();
  expect(document.querySelector('[data-drag="A3010"]')).toBeInTheDocument();
  // 끄는 동안 그 막대의 이름은 숨겨 새 OD 글과 겹치지 않게
  expect([...document.querySelectorAll('.gt-rows .gantt-label')].map((t) => t.textContent)).not.toContain('외장 패널');
  fireEvent.pointerMove(document.body, { clientX: 400 });
  fireEvent.pointerUp(document.body, { clientX: 400 });
  expect(document.querySelector('[data-drag]')).toBeNull();
  expect(writes()).toEqual([]);
});

test('dragging the bar later sets a start floor (SNET) at the date under the new start', async () => {
  await renderGantt();
  fireEvent.pointerDown(bar('A3010')!, { clientX: 400, button: 0 });
  fireEvent.pointerMove(document.body, { clientX: 400 + 7 * pxPerDay() });
  expect(screen.getByText('SNET 2027.07.22')).toBeInTheDocument();
  fireEvent.pointerUp(document.body, { clientX: 400 + 7 * pxPerDay() });
  await waitFor(() =>
    expect(writes()).toEqual([['PATCH', '/api/schedules/1/activities/A3010', { constraint: { type: 'SNET', date: '2027-07-22' }, base_version: 1 }]]),
  );
});

test('dragging earlier than the logic allows without a SNET explains instead of sending', async () => {
  await renderGantt();
  drag(bar('A3010'), -3 * pxPerDay());
  expect(writes()).toEqual([]);
  expect(screen.getByRole('status')).toHaveTextContent('SNET 제약은 시작을 늦추기만 합니다');
});

test('an existing SNET can be moved earlier', async () => {
  setupGantt(withActivity('A3010', { constraint: { type: 'SNET', date: '2027-07-15' } }));
  await renderGantt();
  drag(bar('A3010'), -3 * pxPerDay());
  await waitFor(() => expect(writes()[0][2]).toEqual({ constraint: { type: 'SNET', date: '2027-07-12' }, base_version: 1 }));
});

test('a bar with an FNLT constraint is not moved (that would replace FNLT) but its OD can be dragged', async () => {
  setupGantt(withActivity('A3010', { constraint: { type: 'FNLT', date: '2027-09-10' } }));
  await renderGantt();
  expect(bar('A3010')!.closest('[data-movable]')).toBeNull();
  drag(bar('A3010'), 7 * pxPerDay());
  expect(writes()).toEqual([]);
  drag(handle('A3010'), 7 * pxPerDay());
  await waitFor(() => expect(writes()[0][2]).toEqual({ od: 40, base_version: 1 }));
});

test('started and finished activities and milestones have no OD handle; started ones do not move', async () => {
  await renderGantt();
  expect(handle('A2020')).toBeNull(); // 진행 중
  expect(handle('A1020')).toBeNull(); // 끝남
  expect(handle('A4030')).toBeNull(); // 마일스톤
  expect(handle('A3010')).toBeInTheDocument();
  drag(bar('A2020'), 7 * pxPerDay());
  expect(writes()).toEqual([]);
});

test('pressing a bar does not start a text selection or focus change in the chart', async () => {
  await renderGantt();
  const down = new PointerEvent('pointerdown', { bubbles: true, cancelable: true, clientX: 400, button: 0 });
  bar('A3010')!.dispatchEvent(down);
  expect(down.defaultPrevented).toBe(true);
  fireEvent.pointerUp(document.body, { clientX: 400 });
});

test('a press without moving only selects', async () => {
  await renderGantt();
  drag(bar('A3010'), 2);
  expect(useSchedule.getState().selected).toBe('A3010');
  expect(writes()).toEqual([]);
});

test('double-clicking a bar opens the same OD editor as the table; Enter sends it', async () => {
  await renderGantt();
  fireEvent.doubleClick(bar('A3010')!);
  const box = within(leftRow('A3010')!).getByRole('textbox', { name: 'A3010 OD' });
  expect(box).toHaveValue('35');
  await userEvent.clear(box);
  await userEvent.type(box, '40{Enter}');
  await waitFor(() => expect(writes()).toEqual([['PATCH', '/api/schedules/1/activities/A3010', { od: 40, base_version: 1 }]]));
});

test('double-clicking a left grid cell edits that cell; wrong text is not sent', async () => {
  await renderGantt();
  await userEvent.dblClick(within(leftRow('A3010')!).getByText('외장 패널'));
  const box = within(leftRow('A3010')!).getByRole('textbox', { name: 'A3010 이름' });
  await userEvent.clear(box);
  await userEvent.type(box, '외장 패널 시공{Enter}');
  await waitFor(() => expect(writes()[0][2]).toEqual({ name: '외장 패널 시공', base_version: 1 }));
  await userEvent.dblClick(within(leftRow('A3010')!).getByText('35'));
  const od = within(leftRow('A3010')!).getByRole('textbox', { name: 'A3010 OD' });
  await userEvent.clear(od);
  await userEvent.type(od, '3.5{Enter}');
  expect(writes()).toHaveLength(1);
  expect(screen.getByRole('alert')).toHaveTextContent('OD는 0 이상 정수로 넣어 주세요.');
});

test('the server answer redraws the bar; a 422 shows the server message and keeps the bar', async () => {
  await renderGantt();
  const x0 = Number(bar('A3010')!.getAttribute('x'));
  mockPatch(422, { code: 'schedule_invalid', message: '관계가 고리를 이룹니다: A3010 → A3010', detail: null });
  drag(bar('A3010'), 7 * pxPerDay());
  expect(await screen.findByRole('alert')).toHaveTextContent('관계가 고리를 이룹니다');
  expect(Number(bar('A3010')!.getAttribute('x'))).toBeCloseTo(x0, 1);
  mockPatch({ ...withActivity('A3010', { es: '2027-07-22', ef: '2027-09-08' }), version: 2 });
  drag(bar('A3010'), 7 * pxPerDay());
  await waitFor(() => expect(Number(bar('A3010')!.getAttribute('x'))).toBeCloseTo(x0 + 7 * pxPerDay(), 1));
});

test('a 409 reloads with the conflict notice', async () => {
  await renderGantt();
  mockPatch(409, { code: 'version_conflict', message: '그 사이 일정이 바뀌었습니다.', detail: { current: 2 } });
  drag(handle('A3010'), 7 * pxPerDay());
  expect(await screen.findByText(CONFLICT_NOTICE)).toBeInTheDocument();
});

test('two quick drags go one at a time; the second uses the version the first returned', async () => {
  await renderGantt();
  const release = holdNextWrite();
  drag(handle('A3010'), 7 * pxPerDay());
  drag(handle('A3030'), 7 * pxPerDay());
  await waitFor(() => expect(writes()).toHaveLength(1));
  await act(async () => release(makeView({ version: 2 })));
  await waitFor(() => expect(writes()).toHaveLength(2));
  expect(writes()[1]).toEqual(['PATCH', '/api/schedules/1/activities/A3030', expect.objectContaining({ base_version: 2 })]);
});

test('no drag editing during a conditions preview', async () => {
  await renderGantt();
  act(() => useSchedulePreview.getState().set({ scheduleId: 1, view: makeView(), moved: [], source: 'conditions' }));
  expect(handle('A3010')).toBeNull();
  drag(bar('A3010'), 7 * pxPerDay());
  fireEvent.doubleClick(bar('A3010')!);
  expect(writes()).toEqual([]);
  expect(within(leftRow('A3010')!).queryByRole('textbox')).toBeNull();
  expect(screen.getByText('미리 보기 중에는 고칠 수 없습니다')).toBeInTheDocument();
});

test('the 선행 cell checks ids against the schedule like the table and does not send an unknown one', async () => {
  await renderGantt();
  await userEvent.click(screen.getByRole('button', { name: '열' }));
  await userEvent.click(within(screen.getByRole('dialog', { name: '열' })).getByLabelText('선행'));
  await userEvent.keyboard('{Escape}');
  await userEvent.dblClick(within(leftRow('A3010')!).getByText('A2020, A1040'));
  const box = within(leftRow('A3010')!).getByRole('textbox', { name: 'A3010 선행' });
  await userEvent.clear(box);
  await userEvent.type(box, 'A2020, A9999{Enter}');
  expect(writes()).toEqual([]);
  expect(screen.getByRole('alert')).toHaveTextContent('없는 액티비티입니다: A9999');
  localStorage.clear();
});
