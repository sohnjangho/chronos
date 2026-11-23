// 일정 도구 프로그램끼리(스케줄 ↔ 간트차트): 같은 일정을 보는 창은 저장소 하나를 함께 쓴다 —
// 고침·되돌리기·쓰기 줄·고른 액티비티. 프로그램 폴더는 서로 import하지 않으므로 이 시험은 programs 바로 아래에 둔다.
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { useCurrentSchedule } from '../os/currentSchedule';
import { useUiContext } from '../os/uiContext';
import { useWindows } from '../os/windowStore';
import { forgetSchedules, holdSchedule, scheduleStore } from '../shared/schedule/scheduleStore';
import Gantt from './gantt/Gantt';
import { bar, leftRow, setupGantt } from './gantt/testKit';
import ScheduleTable from './schedule-table/ScheduleTable';
import { cell, editCell, fetchMock, loadSpy, makeView, mockPatch, row, rowOrNull, schedule, server, table, writes } from './schedule-table/testKit';
import { json } from '../test-helpers';

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

// W1(11-23): 탐색기 되돌리기·승인함 승인처럼 다른 곳에서 버전이 바뀌면 열린 일정 창과 새로 여는 창이 새 버전을 보인다.
const head = (c: HTMLElement) => within(c).getByRole('group', { name: '일정 요약' });

test('a reload signal (restore or approval elsewhere) makes an open window read the new version', async () => {
  const { gantt } = await openBoth();
  expect(head(gantt.container)).toHaveTextContent('완료 예정 2027.11.24');
  server.view = makeView({ version: 6, finish: '2027-10-29' });
  act(() => useCurrentSchedule.getState().bumpReload());
  await waitFor(() => expect(head(gantt.container)).toHaveTextContent('완료 예정 2027.10.29'));
  expect(loadSpy).toHaveBeenCalledTimes(2); // 두 창이 같은 저장소라 한 번만 읽는다
});

test('a window opened while another window holds an old copy reads the schedule again', async () => {
  const release = holdSchedule(scheduleStore(1), 'w-cpm'); // CPM 창이 옛 버전을 잡고 있다
  await act(() => schedule().load());
  server.view = makeView({ version: 6, finish: '2027-10-29' });
  const gantt = render(<Gantt windowId="w2" params={{ id: '1' }} />);
  await waitFor(() => expect(head(gantt.container)).toHaveTextContent('완료 예정 2027.10.29'));
  expect(loadSpy).toHaveBeenCalledTimes(2);
  release();
});

test('opening another window keeps the delay notice when the version did not change', async () => {
  const tableWin = render(<ScheduleTable windowId="w1" params={{ id: '1' }} />);
  await screen.findByRole('table', { name: '스케줄표' });
  const late = makeView({ version: 2 });
  late.activities = late.activities.map((a) => (a.id === 'A3010' ? { ...a, status: 'late +2' } : a));
  mockPatch(late);
  await editCell('A3010', 'OD', '40');
  expect(await within(tableWin.container).findByText(/늦어졌습니다/)).toBeVisible();
  render(<Gantt windowId="w2" params={{ id: '1' }} />);
  await waitFor(() => expect(loadSpy).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(schedule().view?.version).toBe(2));
  expect(within(tableWin.container).getByText(/늦어졌습니다/)).toBeVisible();
});

// W2(11-23, PM 결정 1): 기록했지만 승인 전인(열린) 지연은 계산에 넣지 않고, 간트·공정률 창 위 띠로 건수와 일수 합을 알린다.
const delayEvent = (id: number, days: number, status: 'open' | 'reflected') => ({ id, activity_id: 'A2020', days, status });
let delayEvents: ReturnType<typeof delayEvent>[] = [];

function stubDelays() {
  const inner = fetchMock.getMockImplementation()!;
  fetchMock.mockImplementation(async (input, init) =>
    String(input) === '/api/schedules/1/delays' ? json(200, { schedule_id: 1, version: 1, events: delayEvents }) : inner(input, init),
  );
}
const band = () => screen.queryByRole('note', { name: '기록된 지연' });

test('the gantt shows a band with the count and days of open delays, not the reflected ones', async () => {
  delayEvents = [delayEvent(1, 3, 'open'), delayEvent(2, 2, 'open'), delayEvent(3, 4, 'reflected')];
  stubDelays();
  render(<Gantt windowId="w2" params={{ id: '1' }} />);
  await waitFor(() => expect(band()).toHaveTextContent('기록된 지연 2건 · 지연 일수 합 5일 · 승인 전'));
  expect(band()).toHaveTextContent('일정·공정률 계산에는 승인해 반영한 지연만 들어갑니다');
});

test('no band without open delays, and none in the schedule table', async () => {
  delayEvents = [delayEvent(3, 4, 'reflected')];
  stubDelays();
  render(<Gantt windowId="w2" params={{ id: '1' }} />);
  await screen.findByRole('toolbar', { name: '간트 도구' });
  await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u) === '/api/schedules/1/delays')).toBe(true));
  expect(band()).toBeNull();
  delayEvents = [delayEvent(1, 3, 'open')];
  act(() => useCurrentSchedule.getState().bumpDelays()); // 사건이 생겼다
  await waitFor(() => expect(band()).not.toBeNull());
  render(<ScheduleTable windowId="w1" params={{ id: '1' }} />);
  await screen.findByRole('table', { name: '스케줄표' });
  expect(screen.getAllByRole('note', { name: '기록된 지연' })).toHaveLength(1); // 스케줄 창에는 없다
});

const delayReads = () => fetchMock.mock.calls.filter(([u]) => String(u) === '/api/schedules/1/delays').length;

test('the band follows a new version of the schedule (an approval that reflected a delay)', async () => {
  delayEvents = [delayEvent(1, 3, 'open')];
  stubDelays();
  render(<Gantt windowId="w2" params={{ id: '1' }} />);
  await waitFor(() => expect(band()).toHaveTextContent('기록된 지연 1건 · 지연 일수 합 3일 · 승인 전'));
  delayEvents = [delayEvent(1, 3, 'reflected')];
  server.view = makeView({ version: 2 });
  await act(() => schedule().load());
  await waitFor(() => expect(band()).toBeNull());
});

// 리뷰 W2: 같은 버전을 다시 읽었다고(뷰 객체만 바뀜) 지연 목록을 다시 묻지 않는다.
test('reading the same version again does not ask for the delays again', async () => {
  delayEvents = [delayEvent(1, 3, 'open')];
  stubDelays();
  render(<Gantt windowId="w2" params={{ id: '1' }} />);
  await waitFor(() => expect(band()).not.toBeNull());
  const asked = delayReads();
  await act(() => schedule().load());
  await act(() => schedule().load());
  expect(delayReads()).toBe(asked);
});

// W2 후속: 지연 기록 창에서 사건을 등록·고치면(delaysToken) 일정을 다시 읽지 않고 띠만 다시 센다.
test('the band counts again when the delays window changes an event, without reading the schedule again', async () => {
  delayEvents = [];
  stubDelays();
  render(<Gantt windowId="w2" params={{ id: '1' }} />);
  await screen.findByRole('toolbar', { name: '간트 도구' });
  await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u) === '/api/schedules/1/delays')).toBe(true));
  expect(band()).toBeNull();
  const reads = loadSpy.mock.calls.length;
  delayEvents = [delayEvent(1, 3, 'open'), delayEvent(2, 1, 'open')];
  act(() => useCurrentSchedule.getState().bumpDelays());
  await waitFor(() => expect(band()).toHaveTextContent('기록된 지연 2건 · 지연 일수 합 4일 · 승인 전'));
  expect(loadSpy).toHaveBeenCalledTimes(reads);
});


// 리뷰 W1: 로그아웃(reloadToken 0 으로)에는 열린 창이 다시 읽지 않고, 다시 읽기 신호에도 버전이 그대로면 지연 알림을 둔다.
test('a reload token going back to 0 (logout) does not make open windows read', async () => {
  render(<Gantt windowId="w2" params={{ id: '1' }} />);
  await screen.findByRole('toolbar', { name: '간트 도구' });
  act(() => useCurrentSchedule.getState().bumpReload());
  await waitFor(() => expect(loadSpy).toHaveBeenCalledTimes(2));
  act(() => useCurrentSchedule.setState({ reloadToken: 0 }));
  await new Promise((r) => setTimeout(r, 20));
  expect(loadSpy).toHaveBeenCalledTimes(2);
});

test('a reload signal at the same version keeps the delay notice of the table window', async () => {
  const tableWin = render(<ScheduleTable windowId="w1" params={{ id: '1' }} />);
  await screen.findByRole('table', { name: '스케줄표' });
  const late = makeView({ version: 2 });
  late.activities = late.activities.map((a) => (a.id === 'A3010' ? { ...a, status: 'late +2' } : a));
  mockPatch(late);
  await editCell('A3010', 'OD', '40');
  expect(await within(tableWin.container).findByText(/늦어졌습니다/)).toBeVisible();
  server.view = late;
  const reads = loadSpy.mock.calls.length;
  act(() => useCurrentSchedule.getState().bumpReload());
  await waitFor(() => expect(loadSpy).toHaveBeenCalledTimes(reads + 1));
  await waitFor(() => expect(schedule().view?.version).toBe(2));
  expect(within(tableWin.container).getByText(/늦어졌습니다/)).toBeVisible();
});
