import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test } from 'vitest';
import { useSchedulePreview } from '../../os/schedulePreview';
import { useUiContext } from '../../os/uiContext';
import { forgetSchedules } from '../../shared/schedule/scheduleStore';
import manifest from './index';
import {
  actualBar, bar, chartBody, fetchMock, FINISH_BY, ghost, leftHeaders, leftRow, link, makeView, num, pxPerDay, renderGantt, schedule, setupGantt, tool,
} from './testKit';

beforeEach(() => setupGantt());
afterEach(() => {
  forgetSchedules();
  useSchedulePreview.getState().reset();
  useUiContext.getState().reset();
});

test('the manifest opens 간트차트 at 1600×900 in the work group', () => {
  expect(manifest).toMatchObject({ id: 'gantt', name: '간트차트', kind: 'work', tone: 'orange', defaultSize: { w: 1600, h: 900 } });
});

const conditionsLoaded = () => waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u) === '/api/schedules/1/conditions')).toBe(true));

test('the 간트차트 window shows its toolbar, left grid columns and chart', async () => {
  await renderGantt();
  expect(leftHeaders()).toEqual(['WBS / ID', '이름', 'OD', 'RD', 'TF']);
  expect(leftRow('2')).toHaveTextContent('2 골조');
  expect(leftRow('2')).toHaveTextContent('(2개)');
  expect(leftRow('A3010')).toHaveTextContent('외장 패널');
  expect(bar('A3010')).toBeInTheDocument();
  expect(screen.getByText('2027년 3월')).toBeInTheDocument(); // 2월은 좁아 비우고 3월이 연도를 단다
  expect(screen.getByText('4월')).toBeInTheDocument();
});

test('CPM layer off hides links and critical color', async () => {
  await renderGantt();
  expect(bar('A2020')).toHaveClass('critical');
  expect(document.querySelectorAll('[data-link]').length).toBeGreaterThan(0);
  await userEvent.click(screen.getByRole('button', { name: 'CPM' }));
  expect(document.querySelectorAll('[data-link]')).toHaveLength(0);
  expect(bar('A2020')).not.toHaveClass('critical');
});

test('actual layer draws progress under the plan bar', async () => {
  await renderGantt();
  expect(actualBar('A2020')).toBeInTheDocument();
  expect(actualBar('A3010')).toBeNull();
  // 끝나지 않은 A2020 은 Data Date 까지, 끝난 A1030 은 Actual 종료까지.
  const dd = document.querySelector('[data-vline="data"]')!;
  expect(num(actualBar('A2020'), 'x') + num(actualBar('A2020'), 'width')).toBeCloseTo(num(dd, 'x1'), 0);
  await userEvent.click(screen.getByRole('button', { name: 'Actual' }));
  expect(actualBar('A2020')).toBeNull();
  expect(bar('A2020')).toBeInTheDocument();
});

test('relation lines: critical path in red, lags in the title, only with the CPM layer', async () => {
  await renderGantt();
  expect(link('A2020>A3010')).toHaveClass('critical');
  expect(link('A2020>A3020')).not.toHaveClass('critical');
  expect(link('A2020>A3020')!.querySelector('title')).toHaveTextContent('A2020 → A3020 SS+30');
  expect(link('A1030>A1040')!.getAttribute('d')).toMatch(/^M /);
});

test('Plan only (Actual off) still shows the CPM layer; Plan off hides bars and turns CPM off with a reason', async () => {
  await renderGantt();
  await userEvent.click(tool('Actual'));
  expect(bar('A2020')).toHaveClass('critical');
  expect(link('A2020>A3010')).toBeInTheDocument();
  await userEvent.click(tool('Actual'));
  await userEvent.click(tool('Plan'));
  expect(bar('A2020')).toBeNull();
  expect(document.querySelectorAll('[data-link]')).toHaveLength(0);
  expect(actualBar('A2020')).toBeInTheDocument();
  expect(tool('CPM')).toBeDisabled();
  expect(tool('CPM')).toHaveAttribute('title', expect.stringContaining('Plan'));
});

test('bars show progress fill, milestones as ◆ with names, summary bars on wbs rows', async () => {
  await renderGantt();
  const fill = document.querySelector('[data-progress="A2020"]')!;
  expect(num(fill, 'width')).toBeCloseTo(0.36 * num(bar('A2020'), 'width'), 1);
  expect(document.querySelector('[data-ms="A1010"]')).toBeInTheDocument();
  expect(document.querySelector('[data-ms="A4030"]')).toBeInTheDocument();
  expect(bar('A4030')).toBeNull();
  expect(screen.getAllByText('준공').length).toBeGreaterThan(1); // 왼쪽 표 + ◆ 옆 이름
  expect(document.querySelector('[data-summary="2"]')).toBeInTheDocument();
});

// PM 결정(11-20): 화면 날짜는 Plan(지금 일정을 실적 없이 계산한 것)과 Actual 두 벌. 막대는 plan_start~plan_finish 이고
// 지금 계산(ES~EF, 실적을 넣은 것)이나 처음 Plan 버전은 따로 그리지 않는다.
test('Plan bars are drawn at plan_start~plan_finish, not at ES~EF, and there is no gray Plan-version line', async () => {
  const acts = makeView().activities.map((a) =>
    a.id === 'A3010' ? { ...a, es: '2027-07-20', ef: '2027-09-06', ls: '2027-07-20', lf: '2027-09-20', tf: 10 } : a.id === 'A4030' ? { ...a, es: '2027-11-29', ef: '2027-11-29' } : a,
  );
  setupGantt(makeView({ activities: acts }));
  await renderGantt();
  const dd = num(document.querySelector('[data-vline="data"]'), 'x1'); // Data Date 2027.06.01
  expect(num(bar('A3010'), 'x') - dd).toBeCloseTo(44 * pxPerDay(), 1); // Plan 시작 07.15
  expect(num(bar('A3010'), 'width')).toBeCloseTo(49 * pxPerDay(), 1); // 07.15 ~ 09.01
  const msX = Number(document.querySelector('[data-ms="A4030"]')!.getAttribute('d')!.split(' ')[1]);
  expect(msX - dd).toBeCloseTo(177 * pxPerDay(), 1); // ◆ = Plan 종료 11.24 끝
  expect(num(document.querySelector('[data-float="A3010"]'), 'x')).toBeCloseTo(num(bar('A3010'), 'x') + num(bar('A3010'), 'width'), 1);
  expect(document.querySelector('[data-planmark]')).toBeNull();
});

test('an activity without Plan dates has no Plan bar and says so beside its row', async () => {
  const acts = makeView().activities.map((a) => (a.id === 'A3030' ? { ...a, plan_start: null, plan_finish: null, status: 'new' } : a));
  setupGantt(makeView({ activities: acts }));
  await renderGantt();
  expect(bar('A3030')).toBeNull();
  expect(link('A2020>A3030')).toBeNull();
  expect(screen.getByText('승강기 설치 · Plan 없음')).toBeInTheDocument();
  expect(bar('A3020')).toBeInTheDocument();
});

test('Data Date line and weekend shading', async () => {
  await renderGantt();
  expect(screen.getByText('Data Date 06.01')).toBeInTheDocument();
  const wk = document.querySelector('[data-weekend]')!;
  expect([0, 6]).toContain(new Date(`${wk.getAttribute('data-weekend')}T00:00:00Z`).getUTCDay());
});

test('deadline line appears only with a finish_by condition', async () => {
  setupGantt(makeView(), [FINISH_BY]);
  await renderGantt();
  expect(await screen.findByText(/기한 11\.30/)).toBeVisible();
  expect(document.querySelector('[data-vline="deadline"]')).toBeInTheDocument();
});

test('no deadline without a finish_by condition, and a turned-off one is not drawn', async () => {
  setupGantt(makeView(), [{ ...FINISH_BY, state: 'off' }]);
  await renderGantt();
  await conditionsLoaded();
  expect(screen.queryByText(/기한/)).toBeNull();
  expect(document.querySelector('[data-vline="deadline"]')).toBeNull();
});

test('a milestone_by condition is a ◆ on that activity row with its date', async () => {
  setupGantt(makeView(), [{ id: 'in.ms', kind: 'milestone_by', params: { activity_id: 'A4030', date: '2027-11-20' } }]);
  await renderGantt();
  await waitFor(() => expect(document.querySelector('[data-due="A4030"]')).toBeInTheDocument());
  expect(document.querySelector('[data-due="A4030"] title')).toHaveTextContent('기한 2027.11.20');
});

test('clicking a bar selects the same row as the table and publishes the ui context', async () => {
  await renderGantt();
  fireEvent.pointerDown(bar('A3010')!, { clientX: 300, button: 0 });
  fireEvent.pointerUp(document.body, { clientX: 300 });
  expect(schedule().selected).toBe('A3010');
  expect(leftRow('A3010')).toHaveAttribute('aria-selected', 'true');
  await waitFor(() => expect(useUiContext.getState().byWindow.w1).toMatchObject({ selected_activity: 'A3010' }));
  expect(document.querySelector('[data-sel="A3010"]')).toBeInTheDocument();
});

test('clicking a left row selects it in the shared schedule store', async () => {
  await renderGantt();
  await userEvent.click(leftRow('A4010')!);
  expect(schedule()).toMatchObject({ selected: 'A4010', selectedBy: 'w1' });
  expect(leftRow('A4010')).toHaveAttribute('aria-selected', 'true');
});

test('arrow keys move the selection in the left grid', async () => {
  await renderGantt();
  await userEvent.click(leftRow('A3010')!);
  await userEvent.keyboard('{ArrowDown}');
  expect(schedule().selected).toBe('A3020');
  expect(leftRow('A3020')).toHaveFocus();
});

test('a wbs group folds from its toggle and keeps its summary bar', async () => {
  await renderGantt();
  const t = within(leftRow('2')!).getByRole('button', { name: '2 골조' });
  expect(t).toHaveAttribute('aria-expanded', 'true');
  await userEvent.click(t);
  expect(leftRow('A2020')).toBeNull();
  expect(bar('A2020')).toBeNull();
  expect(document.querySelector('[data-summary="2"]')).toBeInTheDocument();
});

test('conditions preview draws preview dates, dashed ghosts at the old place and a banner until cleared', async () => {
  await renderGantt();
  const before = num(bar('A3010'), 'x');
  const moved = { es: '2027-07-20', ef: '2027-09-06', plan_start: '2027-07-20', plan_finish: '2027-09-06' };
  const activities = makeView().activities.map((a) => (a.id === 'A3010' ? { ...a, ...moved } : a));
  act(() =>
    useSchedulePreview.getState().set({
      scheduleId: 1,
      view: makeView({ activities, finish: '2027-11-29' }),
      moved: [{ activity_id: 'A3010', name: '외장 패널', before: { start: '2027-07-15', finish: '2027-09-01' }, after: { start: '2027-07-20', finish: '2027-09-06' } }],
      source: 'conditions',
    }),
  );
  expect(screen.getByText('미리 보기 중 — 조건·규칙 창에서 확정하거나 되돌리세요')).toBeInTheDocument();
  // 준공이 늦어져 맞춤 눈금이 바뀐다 — 점선은 저장된 자리(7.15), 막대는 미리 보기 자리(7.20).
  const dd = num(document.querySelector('[data-vline="data"]'), 'x1');
  expect(num(ghost('A3010'), 'x') - dd).toBeCloseTo(44 * pxPerDay(), 1);
  expect(num(bar('A3010'), 'x') - num(ghost('A3010'), 'x')).toBeCloseTo(5 * pxPerDay(), 1);
  expect(ghost('A3020')).toBeNull();
  act(() => useSchedulePreview.getState().clear(1));
  expect(screen.queryByText(/미리 보기 중/)).toBeNull();
  expect(ghost('A3010')).toBeNull();
  expect(num(bar('A3010'), 'x')).toBeCloseTo(before, 1);
});

test('a preview of another schedule is not drawn', async () => {
  await renderGantt();
  act(() => useSchedulePreview.getState().set({ scheduleId: 2, view: makeView({ id: 2 }), moved: [], source: 'conditions' }));
  expect(screen.queryByText(/미리 보기 중/)).toBeNull();
});

test('resource strip shows each key resource and when it is used, without inventing load numbers', async () => {
  await renderGantt();
  const strip = screen.getByRole('region', { name: '주요 자원' });
  expect(within(strip).getByText('타워크레인 (1대)')).toBeInTheDocument();
  const lane = strip.querySelector('[data-res="crane"]')!;
  expect(lane.querySelectorAll('[data-use]')).toHaveLength(1);
  expect(lane.querySelector('[data-use="A2020"] title')).toHaveTextContent('A2020 지상 1~5층 골조');
  expect(strip.querySelectorAll('.over')).toHaveLength(0);
  expect(strip.textContent).not.toMatch(/필요|최고/);
});

test('the resource strip is not shown when the schedule has no resources', async () => {
  setupGantt(makeView({ resources: [] }));
  await renderGantt();
  expect(screen.queryByRole('region', { name: '주요 자원' })).toBeNull();
});

test('the splitter changes the left grid width from the keyboard', async () => {
  await renderGantt();
  const split = screen.getByRole('separator', { name: '표와 차트 나눔선' });
  const left = document.querySelector<HTMLElement>('.gt-left')!;
  const w0 = parseFloat(left.style.width);
  split.focus();
  await userEvent.keyboard('{ArrowRight}');
  expect(parseFloat(left.style.width)).toBe(w0 + 16);
  expect(split).toHaveAttribute('aria-valuenow', String(w0 + 16));
});

test('the chart body scrolls by itself; the header follows horizontally and the grid vertically', async () => {
  await renderGantt();
  await userEvent.click(tool('확대'));
  await userEvent.click(tool('확대'));
  const body = chartBody();
  body.scrollLeft = 240;
  body.scrollTop = 60;
  fireEvent.scroll(body);
  expect(document.querySelector<HTMLElement>('.gt-head')!.scrollLeft).toBe(240);
  expect(document.querySelector<HTMLElement>('.gt-left-body')!.scrollTop).toBe(60);
});

test('a wide left grid scrolls sideways in its own body with the header following and ID·이름 pinned', async () => {
  await renderGantt();
  const body = document.querySelector<HTMLElement>('.gt-left-body')!;
  body.scrollLeft = 80;
  fireEvent.scroll(body);
  expect(document.querySelector<HTMLElement>('.gt-left-head')!.scrollLeft).toBe(80);
  const cells = leftRow('A3010')!.querySelectorAll('[role="gridcell"]');
  expect([...cells].slice(0, 2).map((c) => c.className.includes('pin'))).toEqual([true, true]);
  expect(cells[2].className).not.toContain('pin');
  expect(within(leftRow('2')!).getByRole('gridcell').className).toContain('pin');
});

test('CPM layer draws a float tail from EF to LF (server LS/LF); none when critical or with CPM off', async () => {
  const acts = makeView().activities.map((a) => (a.id === 'A3020' ? { ...a, ls: '2027-07-09', lf: '2027-09-01' } : { ...a, ls: a.es, lf: a.ef }));
  setupGantt(makeView({ activities: acts }));
  await renderGantt();
  const tail = document.querySelector('[data-float="A3020"]')!;
  const b = bar('A3020')!;
  expect(num(tail, 'x')).toBeCloseTo(num(b, 'x') + num(b, 'width'), 1); // EF 다음 날 0시
  expect(num(tail, 'x') + num(tail, 'width') - num(b, 'x')).toBeCloseTo(80 * pxPerDay(), 1); // 6.14 ~ 9.01 끝
  expect(tail.querySelector('title')).toHaveTextContent('여유 18일 · LF 2027.09.01');
  expect(document.querySelector('[data-float="A2020"]')).toBeNull();
  await userEvent.click(tool('CPM'));
  expect(document.querySelector('[data-float]')).toBeNull();
});

test('the working calendar from the server shades days off and blocked periods', async () => {
  setupGantt(makeView({ calendar: { days_per_week: 6, blocked: [{ tag: '타설', start: '2027-07-20', finish: '2027-08-10' }] } }));
  await renderGantt();
  const days = [...document.querySelectorAll('[data-weekend]')].map((d) => new Date(`${d.getAttribute('data-weekend')}T00:00:00Z`).getUTCDay());
  expect(days.length).toBeGreaterThan(0);
  expect(new Set(days)).toEqual(new Set([0]));
  const blocked = document.querySelector('[data-blocked="타설"]')!;
  expect(blocked.querySelector('title')).toHaveTextContent('작업 금지(타설) 2027.07.20~2027.08.10');
  expect(num(blocked, 'width')).toBeCloseTo(22 * pxPerDay(), 1);
});
