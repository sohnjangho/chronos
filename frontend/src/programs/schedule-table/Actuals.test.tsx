// 실적 입력(Task 30): 머리줄 Data Date 고치기 · 가중치 방식과 직접 입력 · 지연 알림.
import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { useWindows } from '../../os/windowStore';
import { forgetSchedules, holdSchedule, scheduleStore } from '../../shared/schedule/scheduleStore';
import type { ScheduleView } from '../../shared/schedule/scheduleApi';
import { cell, editCell, lastBody, loadSpy, makeView, mockPatch, mockWeightMode, renderSchedule, schedule, setup, toolbar, viewWith, writes } from './testKit';

let openSpy: ReturnType<typeof vi.fn>;

beforeEach(() => {
  localStorage.clear();
  setup();
  openSpy = vi.fn();
  useWindows.setState({ open: openSpy } as never);
});
afterEach(() => {
  forgetSchedules();
  vi.unstubAllGlobals();
});

const stats = () => screen.getByRole('group', { name: '일정 요약' });
const dateInput = () => screen.getByRole('textbox', { name: 'Data Date' });
const SUMMARY = { critical_count: 8, negative_float_count: 0, warning_count: 1 };

/** 몇 액티비티의 칸만 바꾼 일정. */
function withActivities(over: Partial<ScheduleView>, acts: Record<string, Partial<ScheduleView['activities'][number]>>): ScheduleView {
  const v = makeView(over);
  return { ...v, activities: v.activities.map((a) => ({ ...a, ...acts[a.id] })) };
}

async function chooseWeightMode(label: string) {
  await userEvent.selectOptions(within(toolbar()).getByRole('combobox', { name: '가중치' }), label);
}

describe('Data Date', () => {
  test('data date edit patches the schedule', async () => {
    await renderSchedule();
    mockPatch(viewWith({ version: 2, data_date: '2027-06-08' }));
    await userEvent.click(screen.getByRole('button', { name: /Data Date/ }));
    await userEvent.clear(dateInput());
    await userEvent.type(dateInput(), '2027-06-08{Enter}');
    expect(lastBody()).toEqual({ data_date: '2027-06-08', base_version: 1 });
    expect(await within(stats()).findByText('2027.06.08')).toBeVisible();
    expect(screen.queryByRole('textbox', { name: 'Data Date' })).toBeNull();
  });

  test('the field starts with the current date, accepts dots and clears with an empty value', async () => {
    await renderSchedule();
    await userEvent.click(screen.getByRole('button', { name: /Data Date/ }));
    expect(dateInput()).toHaveValue('2027.06.01');
    expect(dateInput()).toHaveFocus();
    mockPatch(viewWith({ version: 2, data_date: null }));
    await userEvent.clear(dateInput());
    await userEvent.type(dateInput(), '{Enter}');
    expect(lastBody()).toEqual({ data_date: null, base_version: 1 });
    expect(await within(stats()).findByText('없음')).toBeVisible();
  });

  test('a wrong date is not sent and Esc or the same date sends nothing', async () => {
    await renderSchedule();
    await userEvent.click(screen.getByRole('button', { name: /Data Date/ }));
    await userEvent.clear(dateInput());
    await userEvent.type(dateInput(), '2027.13.01{Enter}');
    expect(screen.getByText('날짜 형식이 맞지 않습니다: 2027.13.01 (예 2027.05.12)')).toBeVisible();
    expect(dateInput()).toBeVisible();
    await userEvent.type(dateInput(), '{Escape}');
    expect(screen.queryByRole('textbox', { name: 'Data Date' })).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: /Data Date/ }));
    await userEvent.type(dateInput(), '{Enter}');
    expect(writes()).toEqual([]);
  });

  test('a version conflict reloads like any other write', async () => {
    await renderSchedule();
    mockPatch(409, { code: 'version_conflict', message: 'x', detail: { current: 3 } });
    await userEvent.click(screen.getByRole('button', { name: /Data Date/ }));
    await userEvent.clear(dateInput());
    await userEvent.type(dateInput(), '2027.06.08{Enter}');
    await waitFor(() => expect(loadSpy).toHaveBeenCalledTimes(2));
    expect(await screen.findByText('그 사이 일정이 바뀌어 다시 불러왔습니다')).toBeVisible();
  });
});

describe('가중치', () => {
  test('manual weight mode makes the weight cell editable and warns about missing weights', async () => {
    await renderSchedule();
    mockWeightMode('manual', viewWith({ weight_mode: 'manual', summary: { ...SUMMARY, weight_missing: 3 } }));
    await chooseWeightMode('직접 입력');
    expect(lastBody()).toEqual({ mode: 'manual' });
    expect(await screen.findByText('가중치 없는 작업 3개')).toBeVisible();
    await userEvent.dblClick(cell('A2020', '가중치(%)'));
    expect(within(cell('A2020', '가중치(%)')).getByRole('textbox')).toBeInTheDocument();
  });

  test('a manual weight is sent as manual_weight and an empty one clears it', async () => {
    setup(withActivities({ weight_mode: 'manual', summary: { ...SUMMARY, weight_missing: 9 } }, { A2020: { manual_weight: 30 } }));
    useWindows.setState({ open: openSpy } as never);
    await renderSchedule();
    expect(cell('A2020', '가중치(%)')).toHaveTextContent(/^30 \(20\.2%\)$/); // 넣은 값 (정규화한 %, 묶음 줄과 같은 단위)
    expect(cell('A3010', '가중치(%)')).toHaveTextContent(/^$/);
    await userEvent.dblClick(cell('A2020', '가중치(%)'));
    expect(within(cell('A2020', '가중치(%)')).getByRole('textbox')).toHaveValue('30');
    await userEvent.keyboard('{Escape}');
    expect(within(toolbar()).getByRole('combobox', { name: '가중치' })).toHaveValue('manual');
    await editCell('A3010', '가중치(%)', '12.5');
    expect(lastBody()).toEqual({ manual_weight: 12.5, base_version: 1 });
    await editCell('A2020', '가중치(%)', ' ');
    expect(writes().at(-1)).toEqual(['PATCH', '/api/schedules/1/activities/A2020', { manual_weight: null, base_version: 2 }]);
    await editCell('A3020', '가중치(%)', '-1');
    expect(screen.getByText('가중치는 0 이상 숫자로 넣어 주세요.')).toBeVisible();
    expect(writes()).toHaveLength(2);
  });

  test('duration mode keeps the weight read-only and shows no warning', async () => {
    await renderSchedule();
    expect(within(toolbar()).getByRole('combobox', { name: '가중치' })).toHaveValue('duration');
    await userEvent.dblClick(cell('A2020', '가중치(%)'));
    expect(within(cell('A2020', '가중치(%)')).queryByRole('textbox')).toBeNull();
    expect(screen.queryByText(/가중치 없는 작업/)).toBeNull();
  });
});

describe('지연 알림', () => {
  test('a newly late activity offers the delay window', async () => {
    await renderSchedule();
    mockPatch(withActivities({ version: 2 }, { A2020: { status: 'late +7' } })); // late +4 → +7
    await editCell('A2020', '진도(%)', '20');
    expect(await screen.findByText('A2020 이(가) Plan보다 3일 더 늦어졌습니다.')).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: '지연 기록 열기' }));
    expect(openSpy).toHaveBeenCalledWith('delays', { id: '1', activity: 'A2020', days: '3', before: '1' });
    expect(screen.queryByRole('button', { name: '지연 기록 열기' })).toBeNull();
  });

  test('an on-plan activity that becomes late is named, the edited one first, and the band closes', async () => {
    await renderSchedule();
    mockPatch(withActivities({ version: 2 }, { A3010: { status: 'late +2' }, A3020: { status: 'late +5' } }));
    await editCell('A3020', 'OD', '45');
    expect(await screen.findByText('A3020 이(가) Plan보다 5일 늦어졌습니다.')).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: '닫기' }));
    expect(screen.queryByText(/늦어졌습니다/)).toBeNull();
    expect(openSpy).not.toHaveBeenCalled();
  });

  test('a closed notice stays closed when the window is opened again, and a new change shows again', async () => {
    const release = holdSchedule(scheduleStore(1), 'w2'); // 간트 창이 같은 일정을 잡고 있다
    const first = await renderSchedule();
    mockPatch(withActivities({ version: 2 }, { A3010: { status: 'late +2' } }));
    await editCell('A3010', 'OD', '40');
    await userEvent.click(await screen.findByRole('button', { name: '닫기' }));
    first.unmount();
    await renderSchedule();
    expect(screen.queryByText(/늦어졌습니다/)).toBeNull();
    mockPatch(withActivities({ version: 3 }, { A3010: { status: 'late +4' } }));
    await editCell('A3010', 'OD', '42');
    expect(await screen.findByText('A3010 이(가) Plan보다 2일 더 늦어졌습니다.')).toBeVisible();
    release();
  });

  test('a reload (409 or a change from elsewhere) takes the notice away', async () => {
    await renderSchedule();
    mockPatch(withActivities({ version: 2 }, { A3010: { status: 'late +2' } }));
    await editCell('A3010', 'OD', '40');
    expect(await screen.findByText(/늦어졌습니다/)).toBeVisible();
    await act(() => schedule().load());
    expect(screen.queryByText(/늦어졌습니다/)).toBeNull();
  });

  test('nothing is shown when no activity got later', async () => {
    await renderSchedule();
    mockPatch(withActivities({ version: 2 }, { A2020: { status: 'late +2' }, A3010: { status: 'early -1' } }));
    await editCell('A2020', '진도(%)', '60');
    await waitFor(() => expect(schedule().view?.version).toBe(2));
    expect(screen.queryByRole('button', { name: '지연 기록 열기' })).toBeNull();
  });
});
