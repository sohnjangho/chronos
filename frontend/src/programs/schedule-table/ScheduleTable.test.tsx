import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { useCurrentSchedule } from '../../os/currentSchedule';
import { useUiContext } from '../../os/uiContext';
import { useWindows } from '../../os/windowStore';
import { json } from '../../test-helpers';
import { forgetSchedules } from '../../shared/schedule/scheduleStore';
import manifest from './index';
import ScheduleTable from './ScheduleTable';
import { fetchMock, loadSpy, makeView, renderSchedule, row, rowOrNull, schedule, setup, toggle } from './testKit';

beforeEach(() => {
  localStorage.clear();
  setup();
  useCurrentSchedule.setState({ current: null });
});
afterEach(() => {
  forgetSchedules();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const title = () => useWindows.getState().wins.find((w) => w.id === 'w1')?.title;

test('the manifest opens 스케줄 at 1600×900 in the work group', () => {
  expect(manifest).toMatchObject({ id: 'schedule-table', name: '스케줄', kind: 'work', tone: 'blue', defaultSize: { w: 1600, h: 900 } });
});

describe('창과 일정 (R5)', () => {
  test('the window title names the schedule', async () => {
    await renderSchedule();
    expect(title()).toBe('스케줄 — 5층 사무동 신축');
  });

  test('without params.id it follows the OS current schedule', async () => {
    useCurrentSchedule.setState({ current: { id: 1, name: '5층 사무동 신축' } });
    await renderSchedule({});
    expect(loadSpy).toHaveBeenCalledTimes(1);
    const other = makeView({ id: 2, name: '물류센터 증축' });
    fetchMock.mockImplementation(async (url) => (String(url) === "/api/schedules/2" ? json(200, other) : json(404, { code: "not_found", message: "x", detail: null })));
    act(() => useCurrentSchedule.setState({ current: { id: 2, name: '물류센터 증축' } }));
    await waitFor(() => expect(title()).toBe('스케줄 — 물류센터 증축'));
  });

  test('without params.id and without a current schedule it asks to choose one', async () => {
    render(<ScheduleTable windowId="w1" />);
    expect(await screen.findByText('메뉴바에서 일정을 고르세요.')).toBeVisible();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test('a schedule that cannot be read shows the server message', async () => {
    fetchMock.mockImplementation(async () => json(404, { code: 'not_found', message: '일정을 찾을 수 없습니다.', detail: null }));
    render(<ScheduleTable windowId="w1" params={{ id: '9' }} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('일정을 찾을 수 없습니다.');
  });

  test('params.activity selects that row, opens its WBS and scrolls to it', async () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    const view = await renderSchedule();
    await userEvent.click(toggle('3 외장·설비'));
    expect(rowOrNull('A3020')).toBeNull();
    view.rerender(<ScheduleTable windowId="w1" params={{ id: '1', activity: 'A3020' }} />);
    await waitFor(() => expect(schedule().selected).toBe('A3020'));
    expect(row('A3020')).toHaveAttribute('aria-current', 'true');
    await waitFor(() => expect(scroll).toHaveBeenCalled());
    expect(scroll.mock.contexts.at(-1)).toBe(row('A3020'));
  });
});

test('params.activity is applied once, not again for the next schedule', async () => {
  useCurrentSchedule.setState({ current: { id: 1, name: '5층 사무동 신축' } });
  render(<ScheduleTable windowId="w1" params={{ activity: 'A3020' }} />);
  await waitFor(() => expect(schedule().selected).toBe('A3020'));
  const other = makeView({ id: 2, name: '물류센터 증축' });
  other.activities = other.activities.filter((a) => a.id !== 'A3020');
  fetchMock.mockImplementation(async () => json(200, other));
  act(() => useCurrentSchedule.setState({ current: { id: 2, name: '물류센터 증축' } }));
  await waitFor(() => expect(title()).toBe('스케줄 — 물류센터 증축'));
  expect(screen.queryByRole('alert')).toBeNull();
  expect(schedule(2).selected).toBeNull();
});

describe('화면 맥락 (R4)', () => {
  test('the window publishes the schedule and the selected activity, and null when nothing is selected', async () => {
    await renderSchedule();
    expect(useUiContext.getState().byWindow.w1).toEqual({ program: 'schedule-table', schedule_id: 1, selected_activity: null });
    await userEvent.click(row('A3010'));
    expect(useUiContext.getState().byWindow.w1).toEqual({ program: 'schedule-table', schedule_id: 1, selected_activity: 'A3010' });
  });
});

describe('머리줄', () => {
  test('there are no tabs any more: the window is the table only', async () => {
    await renderSchedule();
    expect(screen.queryByRole('tablist')).toBeNull();
    expect(screen.getByRole('toolbar', { name: '스케줄표 도구' })).toBeVisible();
  });

  test('the header shows data date, finish and the counts', async () => {
    await renderSchedule();
    const stats = screen.getByRole('group', { name: '일정 요약' });
    expect(within(stats).getByText('2027.06.01')).toBeVisible();
    expect(within(stats).getByText('완료 예정 2027.11.24')).toBeVisible();
    expect(within(stats).getByText('크리티컬 8')).toBeVisible();
    expect(within(stats).getByText('음수 플로트 0')).toBeVisible();
    expect(within(stats).getByText('경고 1')).toBeVisible();
  });

  test('a schedule without a data date says so', async () => {
    setup(makeView({ data_date: null }));
    await renderSchedule();
    expect(within(screen.getByRole('group', { name: '일정 요약' })).getByText('없음')).toBeVisible();
  });
});
