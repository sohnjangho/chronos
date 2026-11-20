import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test } from 'vitest';
import { useSchedulePreview } from '../../os/schedulePreview';
import { useUiContext } from '../../os/uiContext';
import { forgetSchedules } from '../../shared/schedule/scheduleStore';
import manifest from './index';
import {
  actualBar, bar, chartBody, delayedView, fetchMock, FINISH_BY, forecastBar, ghost, ghostTrack, leftHeaders, leftRow, link, makeView, num, pxPerDay,
  renderGantt, schedule, setupGantt, tool,
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

// PM 결정(11-20, Task 17 리뷰 I1): 액티비티마다 두 줄 — 1줄 Plan(plan_start~plan_finish), 2줄 「Actual·예측」
// (실적은 진하게 실제 시작~실제 종료 또는 Data Date, 거기서 지금 계산의 EF 까지는 예측으로 옅게, 시작 전은 ES~EF 예측만).
// 날짜는 모두 서버 값의 자리다(화면은 날짜를 계산하지 않는다).
const end = (el: Element | null) => num(el, 'x') + num(el, 'width');
const dataX = () => num(document.querySelector('[data-vline="data"]'), 'x1');

test('each activity has a Plan row and an Actual·예측 row; a delay shows as the forecast running past Plan', async () => {
  setupGantt(delayedView());
  await renderGantt();
  const ppd = pxPerDay();
  // A2020 진행 중: Plan 05.06~07.14, 실적 05.11~Data Date, 예측 Data Date~07.20(Plan 끝보다 6일 뒤).
  expect(dataX() - num(bar('A2020'), 'x')).toBeCloseTo(26 * ppd, 1);
  expect(num(bar('A2020'), 'width')).toBeCloseTo(70 * ppd, 1);
  expect(num(actualBar('A2020'), 'x') - num(bar('A2020'), 'x')).toBeCloseTo(5 * ppd, 1);
  expect(end(actualBar('A2020'))).toBeCloseTo(dataX(), 1);
  expect(num(forecastBar('A2020'), 'x')).toBeCloseTo(dataX(), 1);
  expect(end(forecastBar('A2020')) - end(bar('A2020'))).toBeCloseTo(6 * ppd, 1);
  // A3010 시작 전: 예측만(07.21~09.07), Plan 보다 6일 뒤로 밀림.
  expect(actualBar('A3010')).toBeNull();
  expect(num(forecastBar('A3010'), 'x') - num(bar('A3010'), 'x')).toBeCloseTo(6 * ppd, 1);
  expect(end(forecastBar('A3010')) - end(bar('A3010'))).toBeCloseTo(6 * ppd, 1);
  // A1020 끝남: 실적만.
  expect(actualBar('A1020')).toBeInTheDocument();
  expect(forecastBar('A1020')).toBeNull();
  // 두 줄은 위아래로 나뉜다.
  expect(num(bar('A3010'), 'y') + num(bar('A3010'), 'height')).toBeLessThanOrEqual(num(forecastBar('A3010'), 'y'));
  expect(bar('A2020')!.closest('[data-progress]')).toBeNull();
  expect(document.querySelector('[data-progress]')).toBeNull(); // Plan 줄에는 실적(진도)을 칠하지 않는다
});

test('the CPM layer colours the forecast bar (current critical) and draws float tails from EF to LF; Plan bars stay plain', async () => {
  setupGantt(delayedView());
  await renderGantt();
  const ppd = pxPerDay();
  expect(forecastBar('A2020')).toHaveClass('critical');
  expect(bar('A2020')).not.toHaveClass('critical');
  const tail = document.querySelector('[data-float="A3020"]')!;
  expect(num(tail, 'x')).toBeCloseTo(end(forecastBar('A3020')), 1); // EF 08.06 다음 날 0시
  expect(end(tail) - end(forecastBar('A3020'))).toBeCloseTo(26 * ppd, 1); // ~ LF 09.01 끝
  expect(tail.querySelector('title')).toHaveTextContent('여유 18일 · LF 2027.09.01');
  expect(document.querySelector('[data-float="A2020"]')).toBeNull();
  await userEvent.click(tool('CPM'));
  expect(forecastBar('A2020')).not.toHaveClass('critical');
  expect(document.querySelector('[data-float]')).toBeNull();
  expect(document.querySelectorAll('[data-link]')).toHaveLength(0);
});

test('relation lines join the Actual·예측 bars; red when both ends are critical, lags in the title', async () => {
  setupGantt(delayedView());
  await renderGantt();
  const d = link('A2020>A3010:FS')!.getAttribute('d')!;
  const [sx, sy] = d.split(' ').slice(1, 3).map(Number);
  expect(sx).toBeCloseTo(end(forecastBar('A2020')), 0); // FS: 선행 예측 끝에서
  expect(sy).toBeGreaterThan(num(forecastBar('A2020'), 'y'));
  expect(Number(d.split(' ').at(-1))).toBeCloseTo(num(forecastBar('A3010'), 'x'), 0); // 후행 예측 시작으로
  expect(link('A2020>A3010:FS')).toHaveClass('critical');
  expect(link('A2020>A3020:SS')).not.toHaveClass('critical');
  expect(link('A2020>A3020:SS')!.querySelector('title')).toHaveTextContent('A2020 → A3020 SS+30');
});

// Task 17 리뷰 M4: 같은 두 액티비티 사이에 종류가 다른 관계가 둘이면 선도 둘(열쇠에 종류).
test('two relations of different types between the same pair draw two lines', async () => {
  const v = makeView();
  v.relations = [...v.relations, { pred: 'A2020', succ: 'A3020', type: 'FF', lag: 5 }];
  setupGantt(v);
  await renderGantt();
  expect(link('A2020>A3020:SS')).toBeInTheDocument();
  expect(link('A2020>A3020:FF')).toBeInTheDocument();
});

test('the layer toggles say Plan · Actual·예측 · CPM; CPM sits on Actual·예측 and turns off with a reason', async () => {
  await renderGantt();
  expect(screen.getByRole('toolbar', { name: '간트 도구' }).querySelectorAll('.gt-chip[aria-pressed]').length).toBeGreaterThanOrEqual(3);
  await userEvent.click(tool('Plan'));
  expect(bar('A2020')).toBeNull();
  expect(forecastBar('A3010')).toBeInTheDocument();
  expect(link('A2020>A3010:FS')).toBeInTheDocument(); // Plan 을 꺼도 CPM 층은 예측 막대에 남는다
  await userEvent.click(tool('Plan'));
  await userEvent.click(tool('Actual·예측'));
  expect(actualBar('A2020')).toBeNull();
  expect(forecastBar('A3010')).toBeNull();
  expect(document.querySelectorAll('[data-link]')).toHaveLength(0);
  expect(bar('A2020')).toBeInTheDocument();
  expect(tool('CPM')).toBeDisabled();
  expect(tool('CPM')).toHaveAttribute('title', expect.stringContaining('Actual·예측'));
});

test('milestones are ◆ in both rows, summary bars on wbs rows', async () => {
  await renderGantt();
  expect(document.querySelector('[data-ms="A1010"]')).toBeInTheDocument();
  expect(document.querySelector('[data-ms-track="A1010"]')).toHaveClass('is-actual'); // 끝난 착공
  expect(document.querySelector('[data-ms-track="A4030"]')).toHaveClass('is-forecast'); // 준공 예측
  expect(bar('A4030')).toBeNull();
  expect(screen.getAllByText('준공').length).toBeGreaterThan(1); // 왼쪽 표 + ◆ 옆 이름
  expect(document.querySelector('[data-summary="2"]')).toBeInTheDocument();
});

test('Plan bars are drawn at plan_start~plan_finish and the float tail runs from EF to LF, not from the Plan end', async () => {
  const acts = makeView().activities.map((a) =>
    a.id === 'A3010' ? { ...a, es: '2027-07-20', ef: '2027-09-06', ls: '2027-07-20', lf: '2027-09-20', tf: 10, critical: false } : a.id === 'A4030' ? { ...a, es: '2027-11-29', ef: '2027-11-29' } : a,
  );
  setupGantt(makeView({ activities: acts }));
  await renderGantt();
  const ppd = pxPerDay();
  expect(num(bar('A3010'), 'x') - dataX()).toBeCloseTo(44 * ppd, 1); // Plan 시작 07.15
  expect(num(bar('A3010'), 'width')).toBeCloseTo(49 * ppd, 1); // 07.15 ~ 09.01
  const msX = Number(document.querySelector('[data-ms="A4030"]')!.getAttribute('d')!.split(' ')[1]);
  expect(msX - dataX()).toBeCloseTo(177 * ppd, 1); // ◆ = Plan 종료 11.24 끝
  const tail = document.querySelector('[data-float="A3010"]')!;
  expect(num(tail, 'x')).toBeCloseTo(end(forecastBar('A3010')), 1); // EF 09.06 다음 날 0시
  expect(num(tail, 'width')).toBeCloseTo(14 * ppd, 1); // 09.07 ~ 09.20: 여유 10 근무일
  expect(document.querySelector('[data-planmark]')).toBeNull();
});

test('an activity without Plan dates has no Plan bar and says so beside its row', async () => {
  const acts = makeView().activities.map((a) => (a.id === 'A3030' ? { ...a, plan_start: null, plan_finish: null, status: 'new' } : a));
  setupGantt(makeView({ activities: acts }));
  await renderGantt();
  expect(bar('A3030')).toBeNull();
  expect(forecastBar('A3030')).toBeInTheDocument();
  expect(screen.getByText('승강기 설치 · Plan 없음')).toBeInTheDocument();
  expect(bar('A3020')).toBeInTheDocument();
  expect(screen.queryByText(/Plan 을 계산할 수 없어/)).toBeNull();
});

// Task 17 리뷰 M12: 모든 액티비티의 Plan 이 없으면 줄마다가 아니라 창에 한 번 알린다.
test('when no activity has Plan dates the window says so once', async () => {
  setupGantt(makeView({ activities: makeView().activities.map((a) => ({ ...a, plan_start: null, plan_finish: null, status: 'new' })), plan_finish: null }));
  await renderGantt();
  expect(screen.getAllByText(/Plan 을 계산할 수 없어/)).toHaveLength(1);
  expect(screen.queryByText(/· Plan 없음/)).toBeNull();
  expect(forecastBar('A3010')).toBeInTheDocument();
});

// Task 17 리뷰 M7: 차트 오른쪽 끝의 이름은 잘리지 않게 막대 왼쪽에 쓴다.
test('a label that would run past the right edge is written to the left of its bar', async () => {
  const acts = makeView().activities.map((a) => (a.id === 'A4030' ? { ...a, name: '준공 및 사용 승인 서류 제출과 인수인계' } : a));
  setupGantt(makeView({ activities: acts }));
  await renderGantt();
  const label = [...document.querySelectorAll('.gantt-label')].find((t) => t.textContent?.startsWith('준공 및'))!;
  expect(label).toHaveAttribute('text-anchor', 'end');
  const msX = Number(document.querySelector('[data-ms="A4030"]')!.getAttribute('d')!.split(' ')[1]);
  expect(num(label, 'x')).toBeLessThan(msX);
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

// 미리 보기(컨트롤러 결정): 저장된 보기(저장소)와 미리 보기 보기를 액티비티마다 서버 값으로 견주어, 바뀐 줄의 이전 자리를 점선으로 —
// Plan 줄은 plan_*, Actual·예측 줄은 es/ef. moved[] 는 쓰지 않는다(목록·글용).
test('a conditions preview moves Plan and forecast bars and leaves dotted old places in both rows until cleared', async () => {
  await renderGantt();
  const before = { plan: num(bar('A3010'), 'x'), track: num(forecastBar('A3010'), 'x') };
  const moved = { es: '2027-07-20', ef: '2027-09-06', plan_start: '2027-07-20', plan_finish: '2027-09-06' };
  const activities = makeView().activities.map((a) => (a.id === 'A3010' ? { ...a, ...moved } : a));
  act(() => useSchedulePreview.getState().set({ scheduleId: 1, view: makeView({ activities, finish: '2027-11-29' }), moved: [], source: 'conditions' }));
  expect(screen.getByText('미리 보기 중 — 조건·규칙 창에서 확정하거나 되돌리세요')).toBeInTheDocument();
  const ppd = pxPerDay();
  // 준공이 늦어져 맞춤 눈금이 바뀐다 — 점선은 저장된 자리(7.15), 막대는 미리 보기 자리(7.20).
  expect(num(ghost('A3010'), 'x') - dataX()).toBeCloseTo(44 * ppd, 1);
  expect(num(bar('A3010'), 'x') - num(ghost('A3010'), 'x')).toBeCloseTo(5 * ppd, 1);
  expect(num(forecastBar('A3010'), 'x') - num(ghostTrack('A3010'), 'x')).toBeCloseTo(5 * ppd, 1);
  expect(ghost('A3020')).toBeNull();
  expect(ghostTrack('A3020')).toBeNull();
  act(() => useSchedulePreview.getState().clear(1));
  expect(screen.queryByText(/미리 보기 중/)).toBeNull();
  expect(ghost('A3010')).toBeNull();
  expect(ghostTrack('A3010')).toBeNull();
  expect(num(bar('A3010'), 'x')).toBeCloseTo(before.plan, 1);
  expect(num(forecastBar('A3010'), 'x')).toBeCloseTo(before.track, 1);
});

test('a preview that moves only the current computation (a delay) leaves Plan alone and dots only the forecast row', async () => {
  await renderGantt();
  const activities = makeView().activities.map((a) => (a.id === 'A3010' ? { ...a, es: '2027-07-20', ef: '2027-09-06' } : a));
  const bogus = [{ activity_id: 'A3020', name: '전기·기계 배관', before: { start: '2027-01-01', finish: '2027-01-02' }, after: { start: '2027-01-03', finish: '2027-01-04' } }];
  act(() => useSchedulePreview.getState().set({ scheduleId: 1, view: makeView({ activities }), moved: bogus, source: 'conditions' }));
  expect(ghost('A3010')).toBeNull();
  expect(ghostTrack('A3010')).toBeInTheDocument();
  expect(num(forecastBar('A3010'), 'x') - num(ghostTrack('A3010'), 'x')).toBeCloseTo(5 * pxPerDay(), 1);
  expect(ghost('A3020')).toBeNull(); // moved[] 로는 그리지 않는다
  expect(ghostTrack('A3020')).toBeNull();
});

// fix 2 I1·f: 미리 보기가 준공을 앞당겨도 저장된 자리(점선)가 보이게 — 범위에 저장된 보기도 넣는다. 마일스톤의 이전 자리는 ◇ 테두리.
test('when a preview pulls the finish earlier the old milestone place stays inside the chart as a ◇ outline', async () => {
  await renderGantt();
  const early = { es: '2027-11-10', ef: '2027-11-10', plan_start: '2027-11-10', plan_finish: '2027-11-10' };
  const activities = makeView().activities.map((a) => (a.id === 'A4030' ? { ...a, ...early } : a));
  act(() => useSchedulePreview.getState().set({ scheduleId: 1, view: makeView({ activities, finish: '2027-11-10', plan_finish: '2027-11-10' }), moved: [], source: 'conditions' }));
  const total = num(document.querySelector('svg.gt-rows'), 'width');
  for (const g of [ghost('A4030'), ghostTrack('A4030')]) {
    expect(g!.tagName.toLowerCase()).toBe('path');
    const cx = Number(g!.getAttribute('d')!.split(' ')[1]);
    expect(cx).toBeGreaterThan(0);
    expect(cx).toBeLessThanOrEqual(total);
  }
});

// fix 2 I2: 이름이 점선을 지나가 취소선처럼 보이지 않게 — 이름 자리는 점선 끝까지 보고 정한다.
test('a bar name is written after the dotted old place when the preview moves the bar earlier', async () => {
  await renderGantt();
  const earlier = { es: '2027-07-05', ef: '2027-08-20', plan_start: '2027-07-05', plan_finish: '2027-08-20' };
  const activities = makeView().activities.map((a) => (a.id === 'A3010' ? { ...a, ...earlier } : a));
  act(() => useSchedulePreview.getState().set({ scheduleId: 1, view: makeView({ activities }), moved: [], source: 'conditions' }));
  const label = [...document.querySelectorAll('.gantt-label')].find((t) => t.textContent === '외장 패널')!;
  const ghostEnd = Math.max(num(ghost('A3010'), 'x') + num(ghost('A3010'), 'width'), num(ghostTrack('A3010'), 'x') + num(ghostTrack('A3010'), 'width'));
  expect(num(label, 'x')).toBeGreaterThanOrEqual(ghostEnd);
});

// fix 2 minor c: 막대에 제목(층 이름과 서버 날짜), 꺼진 CPM 단추는 눌림이 아니다.
test('bars carry a title with their layer and dates; a disabled CPM toggle is not pressed', async () => {
  setupGantt(delayedView());
  await renderGantt();
  expect(bar('A2020')!.querySelector('title')).toHaveTextContent('A2020 지상 1~5층 골조 — Plan 2027.05.06 ~ 2027.07.14');
  expect(actualBar('A2020')!.querySelector('title')).toHaveTextContent('Actual 2027.05.11 ~ 진행 중(Data Date 2027.06.01)');
  expect(forecastBar('A2020')!.querySelector('title')).toHaveTextContent('예측 2027.06.01 ~ 2027.07.20');
  expect(forecastBar('A3010')!.querySelector('title')).toHaveTextContent('예측 2027.07.21 ~ 2027.09.07');
  expect(actualBar('A1020')!.querySelector('title')).toHaveTextContent('Actual 2027.03.02 ~ 2027.03.19');
  expect(document.querySelector('[data-ms="A4030"] title')).toHaveTextContent('Plan 2027.11.24');
  await userEvent.click(tool('Actual·예측'));
  expect(tool('CPM')).toBeDisabled();
  expect(tool('CPM')).toHaveAttribute('aria-pressed', 'false');
});

// fix 2 minor a: 간격 글자는 후행의 Plan 칸에 겹치지 않게 선 아래에.
test('a lag number sits below the line, clear of the successor Plan bar', async () => {
  await renderGantt();
  const lag = [...document.querySelectorAll('.gantt-lag')].find((t) => t.textContent === '+30')!;
  const planBottom = num(bar('A3020'), 'y') + num(bar('A3020'), 'height');
  expect(num(lag, 'y') - 8).toBeGreaterThanOrEqual(planBottom); // 10px 글자의 위쪽(어림)이 Plan 막대 아래
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

// Task 17 리뷰 M8: 자원 막대는 Plan 날짜라 Plan 층을 끄면 함께 숨는다(자원 묶음 줄·아래 자원 줄 모두).
test('resource lane bars follow the Plan layer toggle', async () => {
  await renderGantt();
  await userEvent.click(tool('자원'));
  expect(document.querySelectorAll('[data-lane-bar]').length).toBeGreaterThan(0);
  expect(document.querySelectorAll('[data-use]').length).toBeGreaterThan(0);
  await userEvent.click(tool('Plan'));
  expect(document.querySelectorAll('[data-lane-bar]')).toHaveLength(0);
  expect(document.querySelectorAll('[data-use]')).toHaveLength(0);
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
  const b = forecastBar('A3020')!;
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
