import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { useCurrentSchedule } from '../../os/currentSchedule';
import { useSchedulePreview } from '../../os/schedulePreview';
import { useUiContext } from '../../os/uiContext';
import { useWindows } from '../../os/windowStore';
import { forgetSchedules } from '../../shared/schedule/scheduleStore';
import Delays from './Delays';
import type { DelayEvent } from './delaysApi';
import manifest from './index';
import {
  D, delayCalls, E2, ev, holdDelayPreview, lastBody, m, mockDelayPreview, mockDelays, mockPostError, mockScenario, mockScenarioError,
  mockWrite, previewFor, stubDelaysApi, V,
} from './testKit';

let openSpy: ReturnType<typeof vi.fn>;

beforeEach(() => {
  stubDelaysApi();
  useSchedulePreview.getState().reset();
  openSpy = vi.fn();
  useWindows.setState({ open: openSpy } as never);
});
afterEach(() => {
  forgetSchedules();
  useCurrentSchedule.setState({ current: null });
  vi.unstubAllGlobals();
});

const show = (params: Record<string, string> = { id: '1' }) => render(<Delays windowId="w1" params={params} />);
const table = () => screen.getByRole('table', { name: '지연 사건' });
const bodyRows = () => within(table()).getAllByRole('row').slice(1);
const options = () => within(screen.getByRole('listbox', { name: '대상 액티비티' })).queryAllByRole('option');
const writes = () => delayCalls().filter((c) => c.method !== 'GET');

async function openForm() {
  show();
  await userEvent.click(await screen.findByRole('button', { name: '+ 지연 사건' }));
}
async function pickActivity(name: string) {
  await userEvent.click(await screen.findByRole('option', { name: new RegExp(name) }));
}
/** 그 액티비티의 사건(일정 1의 첫 사건)을 그 상태로 두고 열어 그 줄을 고른다. */
async function selectRow(aid: string, status: DelayEvent['status']) {
  const first = ev({ activity_id: aid, status, reflected_version: status === 'reflected' ? 2 : null });
  mockDelays({ ...D, events: [first, E2] });
  const r = show();
  await userEvent.click(await screen.findByRole('row', { name: new RegExp(`작업 ${aid}`) }));
  return r;
}

test('the manifest opens 지연 기록 at 1400×860 in the work group', () => {
  expect(manifest).toMatchObject({ id: 'delays', name: '지연 기록', kind: 'work', tone: 'brown', defaultSize: { w: 1400, h: 860 } });
});

test('kpis summarize totals', async () => {
  mockDelays(D);
  show();
  expect(await screen.findByText('+2일')).toBeVisible();
  expect(screen.getByText('620만 원')).toBeVisible();
  expect(screen.getByText(/불가항력 2일/)).toBeVisible();
  expect(screen.getByText('Plan 11.24 → 11.26 · 기한 여유 2일')).toBeVisible();
  expect(screen.getByText('3일')).toBeVisible();
  expect(screen.getByText('사건 1건')).toBeVisible();
});

// W6(11-23): 합계는 열린 사건과 이미 반영된 사건을 함께 센다 — 이름표가 그것을 말한다.
test('the finish impact kpi says it adds up reflected events too', async () => {
  mockDelays(D);
  show();
  expect(await screen.findByText('준공 영향 누적(반영 포함)')).toBeVisible();
  expect(screen.queryByText('준공 영향 합계')).toBeNull();
});

test('without a cost the cost kpi is a dash and a late deadline says so', async () => {
  mockDelays({ ...D, totals: { ...D.totals, cost: null }, finish: { ...D.finish, deadline_float: -3 } });
  show();
  expect(await screen.findByText('—')).toBeVisible();
  expect(screen.getByText('Plan 11.24 → 11.26 · 기한 3일 넘음')).toBeVisible();
});

test('the table lists each event with its share and status', async () => {
  mockDelays({ ...D, events: [ev(), { ...E2, status: 'reflected', reflected_version: 3 }] });
  show();
  await screen.findByRole('row', { name: /작업 B/ });
  const [first, second] = bodyRows();
  expect(within(first).getByText('2027.06.02')).toBeVisible();
  expect(within(first).getByText('우천')).toBeVisible();
  expect(within(first).getByText('불가항력')).toBeVisible();
  expect(within(first).getByText('+2')).toBeVisible();
  expect(within(first).getByText('열림')).toBeVisible();
  expect(within(second).getByText('발주처')).toBeVisible();
  expect(within(second).getByText('반영됨 v3')).toBeVisible();
  expect(screen.queryByText('분석 필요')).toBeNull();
  expect(screen.getByText('사건은 대화나 실적 입력에서도 등록됩니다. 여러 건은 발생 순서대로 넣어 각각의 몫을 계산합니다.')).toBeVisible();
});

test('responsibility and status filters narrow the table', async () => {
  mockDelays({ ...D, events: [ev(), { ...E2, status: 'reflected', reflected_version: 3 }] });
  show();
  await screen.findByRole('row', { name: /작업 B/ });
  await userEvent.selectOptions(screen.getByLabelText('책임 거르기'), 'owner');
  expect(bodyRows()).toHaveLength(1);
  expect(within(bodyRows()[0]).getByText('발주처')).toBeVisible();
  await userEvent.selectOptions(screen.getByLabelText('상태 거르기'), 'open');
  expect(screen.getByText('맞는 사건이 없습니다.')).toBeVisible();
});

test('adding an event posts and redraws', async () => {
  mockWrite({ ...D, events: [ev(), E2, ev({ id: 3, cause: '우천', days: 2, responsibility: 'undecided' })] });
  await openForm();
  await pickActivity('작업 B');
  await userEvent.type(screen.getByLabelText('일수'), '2');
  await userEvent.type(screen.getByLabelText('원인'), '우천');
  await userEvent.click(screen.getByRole('button', { name: '등록' }));
  expect(lastBody()).toMatchObject({ activity_id: 'B', days: 2, cause: '우천', responsibility: 'undecided' });
  expect(lastBody()).toEqual({
    activity_id: 'B', start_date: '2027-06-01', days: 2, cause: '우천', responsibility: 'undecided', daily_cost: null, evidence: '',
  });
  await waitFor(() => expect(bodyRows()).toHaveLength(3));
  expect(screen.queryByRole('button', { name: '등록' })).toBeNull();
  expect(bodyRows()[2]).toHaveAttribute('aria-current', 'true'); // 새 사건을 고른다
});

test('the form checks days, cause and daily cost before sending', async () => {
  await openForm();
  await pickActivity('작업 B');
  await userEvent.type(screen.getByLabelText('일수'), '400');
  await userEvent.type(screen.getByLabelText('하루 금액(원)'), '1.5');
  await userEvent.click(screen.getByRole('button', { name: '등록' }));
  expect(screen.getByText('일수는 1~365 사이 정수로 적어 주세요.')).toBeVisible();
  expect(screen.getByText('원인을 적어 주세요.')).toBeVisible();
  expect(screen.getByText('하루 금액은 0 이상 정수(원)로 적어 주세요.')).toBeVisible();
  expect(writes()).toEqual([]);
});

test('activity picker filters by search', async () => {
  await openForm();
  await screen.findAllByRole('option');
  expect(screen.getByRole('group', { name: '골조' })).toBeVisible(); // WBS 묶음
  await userEvent.type(screen.getByPlaceholderText('액티비티 찾기'), '골조');
  expect(options()).toHaveLength(2);
  await userEvent.clear(screen.getByPlaceholderText('액티비티 찾기'));
  await userEvent.type(screen.getByPlaceholderText('액티비티 찾기'), '없는 이름');
  expect(screen.getByText('맞는 액티비티 없음')).toBeVisible();
});

test('params prefill the form', () => {
  render(<Delays windowId="w1" params={{ id: '1', activity: 'A2020', days: '3' }} />);
  expect(screen.getByLabelText('일수')).toHaveValue('3');
});

test('a form opened from actuals records the delay as already in the schedule', async () => {
  show({ id: '1', activity: 'A2020', days: '3', before: '1' });
  expect(screen.getByText(/실적 입력에서 감지한 지연입니다/)).toBeVisible();
  await screen.findAllByRole('option');
  await userEvent.type(screen.getByLabelText('원인'), '철근 반입 늦음');
  await userEvent.click(screen.getByRole('button', { name: '등록' }));
  expect(lastBody()).toMatchObject({ activity_id: 'A2020', days: 3, cause: '철근 반입 늦음', source: 'actual', before_version: 1 });
});

test('a plain form sends no source', async () => {
  await openForm();
  await pickActivity('작업 B');
  await userEvent.type(screen.getByLabelText('일수'), '1');
  await userEvent.type(screen.getByLabelText('원인'), '장비 고장');
  await userEvent.click(screen.getByRole('button', { name: '등록' }));
  expect(lastBody()).not.toHaveProperty('source');
  expect(lastBody()).not.toHaveProperty('before_version');
});

test('reflected events cannot change days', async () => {
  await selectRow('B', 'reflected');
  await userEvent.click(screen.getByRole('button', { name: '고치기' }));
  expect(screen.getByLabelText('일수')).toBeDisabled();
  expect(screen.getByLabelText('시작일')).toBeDisabled();
  expect(screen.getByLabelText('원인')).toBeEnabled();
});

test('editing sends only the changed fields', async () => {
  await selectRow('B', 'open');
  await userEvent.click(screen.getByRole('button', { name: '고치기' }));
  const days = screen.getByLabelText('일수');
  await userEvent.clear(days);
  await userEvent.type(days, '4');
  await userEvent.clear(screen.getByLabelText('하루 금액(원)'));
  await userEvent.click(screen.getByRole('button', { name: '저장' }));
  expect(writes().at(-1)).toMatchObject({ method: 'PATCH', url: '/api/schedules/1/delays/1' });
  expect(lastBody()).toEqual({ days: 4, daily_cost: null });
});

test('an unchanged edit sends nothing', async () => {
  await selectRow('B', 'open');
  await userEvent.click(screen.getByRole('button', { name: '고치기' }));
  await userEvent.click(screen.getByRole('button', { name: '저장' }));
  expect(writes()).toEqual([]);
  expect(screen.getByRole('button', { name: '고치기' })).toBeVisible();
});

test('a conflict on edit shows the server text as is', async () => {
  const text = '승인함에 올라간 안에 들어 있는 사건이라 고칠 수 없습니다. 그 안을 거부한 뒤 고쳐 주세요.';
  mockPostError(409, { code: 'delay_in_submitted_plan', message: text, detail: null });
  await selectRow('B', 'open');
  await userEvent.click(screen.getByRole('button', { name: '고치기' }));
  await userEvent.type(screen.getByLabelText('일수'), '1');
  await userEvent.click(screen.getByRole('button', { name: '저장' }));
  expect(await screen.findByText(text)).toBeVisible();
});

test('the detail shows the impact analysis of the chosen event', async () => {
  mockDelays(D);
  show();
  await userEvent.click(await screen.findByRole('row', { name: /작업 B/ }));
  const side = screen.getByRole('region', { name: '사건 자세히' });
  expect(within(side).getByText('+2일 (여유 흡수 0일)')).toBeVisible();
  expect(within(side).getByText('준공 +2')).toBeVisible();
  expect(within(side).getByText('작업 B 가 새로 크리티컬')).toBeVisible();
  expect(within(side).getByText('3개')).toBeVisible();
  expect(within(side).getByText('2027.06.02 부터 2일')).toBeVisible();
  expect(within(side).getByText('310만 원')).toBeVisible();
  await userEvent.click(screen.getByRole('row', { name: /전기·기계 배관/ }));
  expect(within(side).getByText('2027.07.19 부터 4일 타워크레인 겹침이 새로 생김')).toBeVisible();
  expect(within(side).getAllByText('바뀌지 않음')).toHaveLength(2); // 주요 날짜·크리티컬 패스
  expect(within(side).getByText('공문_0611.pdf')).toBeVisible();
});

test('params.event selects that event', async () => {
  show({ id: '1', event: '2' });
  const side = await screen.findByRole('region', { name: '사건 자세히' });
  expect(await within(side).findByText('자재 반입 지연')).toBeVisible();
});

test('an event left out of the schedule says why', async () => {
  const skipped = ev({ impact: { ...ev().impact!, applied: false, note: '끝난 작업이라 넣지 않았습니다.', finish_delta: 0, cost: null } });
  mockDelays({ ...D, events: [skipped] });
  show();
  await userEvent.click(await screen.findByRole('row', { name: /작업 B/ }));
  expect(screen.getByText('끝난 작업이라 넣지 않았습니다.')).toBeVisible();
});

test('compare button makes a delay scenario and opens the compare window', async () => {
  mockScenario(9);
  show();
  await userEvent.click(await screen.findByRole('button', { name: '비교판에서 보기' }));
  expect(openSpy).toHaveBeenCalledWith('compare', { id: '1', base: 'current', other: 's:9' });
  expect(writes().at(-1)).toMatchObject({ method: 'POST', url: '/api/schedules/1/delays/scenario', body: {} });
});

test('a scenario refusal is shown', async () => {
  mockScenarioError(422, { code: 'no_open_delays', message: '열린 지연 사건이 없습니다.', detail: null });
  show();
  await userEvent.click(await screen.findByRole('button', { name: '비교판에서 보기' }));
  expect(await screen.findByText('열린 지연 사건이 없습니다.')).toBeVisible();
  expect(openSpy).not.toHaveBeenCalled();
});

test('gantt button previews open delays as ghost bars', async () => {
  mockDelayPreview({ view: V, moved: [m('B')] });
  await selectRow('B', 'open');
  await userEvent.click(screen.getByRole('button', { name: '간트에서 보기' }));
  await waitFor(() => expect(previewFor(1)?.source).toBe('delays'));
  expect(previewFor(1)?.moved).toEqual([m('B')]);
  expect(openSpy).toHaveBeenCalledWith('gantt', { id: '1', activity: 'B' });
});

test('a reflected event opens the gantt without a preview', async () => {
  await selectRow('B', 'reflected');
  await userEvent.click(screen.getByRole('button', { name: '간트에서 보기' }));
  expect(openSpy).toHaveBeenCalledWith('gantt', { id: '1', activity: 'B' });
  expect(previewFor(1)).toBeUndefined();
  expect(delayCalls().some((c) => c.url.endsWith('/preview'))).toBe(false);
});

test('closing the window clears its delay preview', async () => {
  const { unmount } = await selectRow('B', 'open');
  await userEvent.click(screen.getByRole('button', { name: '간트에서 보기' }));
  await waitFor(() => expect(previewFor(1)).toBeDefined());
  unmount();
  expect(previewFor(1)).toBeUndefined();
});

test('closing the window leaves a conditions preview alone', async () => {
  useSchedulePreview.getState().set({ scheduleId: 1, view: V, moved: [], source: 'conditions' });
  const { unmount } = show();
  await screen.findByRole('row', { name: /작업 B/ });
  unmount();
  expect(previewFor(1)?.source).toBe('conditions');
});

test('recovery request goes to chat', async () => {
  show();
  await userEvent.click(await screen.findByRole('button', { name: '만회 계획 요청' }));
  expect(openSpy).toHaveBeenCalledWith('chat', { ask: '지연 기록을 반영한 만회 계획을 만들어 줘' });
});

test('one event recovery request names the event', async () => {
  await selectRow('B', 'open');
  await userEvent.click(screen.getByRole('button', { name: '이 사건 만회안 요청' }));
  expect(openSpy).toHaveBeenCalledWith('chat', { ask: 'B 작업 B 우천 지연을 만회할 계획을 만들어 줘' });
});

test('reanalyse posts and redraws', async () => {
  mockWrite({ ...D, events: [ev({ cause: '우천(다시 분석)' }), E2] });
  await selectRow('B', 'open');
  await userEvent.click(screen.getByRole('button', { name: '다시 분석' }));
  expect(writes().at(-1)).toMatchObject({ method: 'POST', url: '/api/schedules/1/delays/analyze' });
  expect(await screen.findAllByText('우천(다시 분석)')).not.toHaveLength(0);
});

test('server error message is shown', async () => {
  mockPostError(422, { code: 'invalid_delay', message: '없는 액티비티입니다: Z', detail: null });
  await openForm();
  await pickActivity('작업 B');
  await userEvent.type(screen.getByLabelText('일수'), '2');
  await userEvent.type(screen.getByLabelText('원인'), '우천');
  await userEvent.click(screen.getByRole('button', { name: '등록' }));
  expect(await screen.findByText('없는 액티비티입니다: Z')).toBeVisible();
  expect(screen.getByRole('button', { name: '등록' })).toBeVisible(); // 폼은 그대로
});

test('title and ui context follow the schedule and the chosen event', async () => {
  useWindows.setState({ wins: [{ id: 'w1', programId: 'delays', title: '지연 기록', x: 0, y: 48, w: 1400, h: 860, z: 1, minimized: false, maximized: false }] } as never);
  show();
  await waitFor(() => expect(useWindows.getState().wins[0].title).toBe('지연 기록 — 5층 사무동 신축'));
  await userEvent.click(await screen.findByRole('row', { name: /작업 B/ }));
  expect(useUiContext.getState().byWindow.w1).toEqual({ program: 'delays', schedule_id: 1, selected_activity: 'B' });
});

test('without params.id it follows the current schedule, and without one it asks to pick', async () => {
  render(<Delays windowId="w1" />);
  expect(screen.getByText('메뉴바에서 일정을 고르세요.')).toBeVisible();
  useCurrentSchedule.setState({ current: { id: 1, name: '5층 사무동 신축' } });
  expect(await screen.findByRole('row', { name: /작업 B/ })).toBeVisible();
});

test('a failed load is shown', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ code: 'not_found', message: '일정을 찾을 수 없습니다.', detail: null }), { status: 404 })));
  show();
  expect(await screen.findByText('일정을 찾을 수 없습니다.')).toBeVisible();
});

describe('Fix round 1', () => {
  test('choosing another row while editing goes back to that row\'s detail', async () => {
    await selectRow('B', 'open');
    await userEvent.click(screen.getByRole('button', { name: '고치기' }));
    expect(screen.getByText('#1 · 우천')).toBeVisible(); // 어느 사건을 고치는지
    await userEvent.click(screen.getByRole('row', { name: /전기·기계 배관/ }));
    expect(screen.queryByRole('button', { name: '저장' })).toBeNull();
    const side = screen.getByRole('region', { name: '사건 자세히' });
    expect(within(side).getByText('자재 반입 지연')).toBeVisible();
    expect(writes()).toEqual([]);
  });

  test('a late preview after the window closed neither sets the preview nor opens the gantt', async () => {
    const release = holdDelayPreview();
    const { unmount } = await selectRow('B', 'open');
    await userEvent.click(screen.getByRole('button', { name: '간트에서 보기' }));
    unmount();
    release();
    await new Promise((r) => setTimeout(r, 20));
    expect(previewFor(1)).toBeUndefined();
    expect(openSpy).not.toHaveBeenCalledWith('gantt', expect.anything());
  });

  test('replacing a conditions preview says so', async () => {
    useSchedulePreview.getState().set({ scheduleId: 1, view: V, moved: [], source: 'conditions' });
    await selectRow('B', 'open');
    await userEvent.click(screen.getByRole('button', { name: '간트에서 보기' }));
    expect(await screen.findByText('조건 미리 보기를 지연 미리 보기로 바꿨습니다.')).toBeVisible();
    expect(previewFor(1)?.source).toBe('delays');
  });

  test('arrow keys move through the activity list and the error is linked', async () => {
    await openForm();
    await screen.findAllByRole('option');
    await userEvent.click(screen.getByRole('button', { name: '등록' }));
    const search = screen.getByPlaceholderText('액티비티 찾기');
    const error = screen.getByText('대상 액티비티를 고르세요.');
    expect(search.getAttribute('aria-describedby')).toBe(error.id);
    const listbox = screen.getByRole('listbox', { name: '대상 액티비티' });
    expect(listbox.getAttribute('aria-describedby')).toBe(error.id);
    expect(within(listbox).queryByText(/일정을 읽는 중|맞는 액티비티 없음/)).toBeNull();
    search.focus();
    await userEvent.keyboard('{ArrowDown}');
    expect(options()[0]).toHaveFocus();
    await userEvent.keyboard('{ArrowDown}{ArrowDown}');
    expect(options()[2]).toHaveFocus();
    await userEvent.keyboard('{ArrowUp}');
    expect(options()[1]).toHaveFocus();
    await userEvent.keyboard('{End}');
    expect(options().at(-1)).toHaveFocus();
    await userEvent.keyboard('{Home}{Enter}');
    expect(options()[0]).toHaveAttribute('aria-selected', 'true');
  });

  test('the compare button says why it is off', async () => {
    mockDelays({ ...D, events: [{ ...ev(), status: 'reflected', reflected_version: 2 }], totals: { ...D.totals, open_count: 0 } });
    show();
    expect(await screen.findByText('열린 사건이 없어 비교판을 만들 수 없습니다.')).toBeVisible();
    expect(screen.getByRole('button', { name: '비교판에서 보기' })).toBeDisabled();
  });

  test('a bad before version blocks saving instead of recording a user delay', async () => {
    show({ id: '1', activity: 'A2020', days: '3', before: 'v1' });
    expect(screen.getByRole('alert')).toHaveTextContent('실적 입력 전 버전 값이 올바르지 않습니다(v1)');
    await userEvent.type(screen.getByLabelText('원인'), '철근 반입 늦음');
    expect(screen.getByRole('button', { name: '등록' })).toBeDisabled();
  });

  test('a bad before version is refused even when the form is submitted directly', async () => {
    show({ id: '1', activity: 'A2020', days: '3', before: 'v1' });
    await screen.findAllByRole('option');
    await userEvent.type(screen.getByLabelText('원인'), '철근 반입 늦음');
    fireEvent.submit(screen.getByRole('form', { name: '새 지연 사건' }));
    await new Promise((r) => setTimeout(r, 20));
    expect(writes()).toEqual([]);
  });

  test('an empty before says the value is empty, without empty brackets', () => {
    show({ id: '1', activity: 'A2020', days: '3', before: '' });
    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('실적 입력 전 버전 값이 비어 있습니다.');
    expect(alert.textContent).not.toContain('()');
    expect(screen.getByRole('button', { name: '등록' })).toBeDisabled();
  });
});

test('the report visual button asks for the delay_impact picture', async () => {
  show();
  await userEvent.click(await screen.findByRole('button', { name: '보고서용 그림' }));
  expect(screen.getByRole('dialog', { name: '보고서용 그림' })).toBeVisible();
  const call = vi.mocked(fetch).mock.calls.find(([u]) => String(u) === '/api/schedules/1/visuals');
  expect(JSON.parse(String(call?.[1]?.body))).toEqual({ kind: 'delay_impact' });
});

// W2 후속: 이 창에서 사건을 등록·고치기·다시 분석하면 열린 간트·공정률 창의 「기록된 지연」 띠가 바로 다시 센다.
describe('W2 후속 기록된 지연 띠 알림', () => {
  const token = () => useCurrentSchedule.getState().delaysToken;

  test('adding an event tells the open schedule windows', async () => {
    mockWrite({ ...D, events: [ev(), E2, ev({ id: 3 })] });
    await openForm();
    const before = token();
    await pickActivity('작업 B');
    await userEvent.type(screen.getByLabelText('일수'), '2');
    await userEvent.type(screen.getByLabelText('원인'), '우천');
    await userEvent.click(screen.getByRole('button', { name: '등록' }));
    await waitFor(() => expect(bodyRows()).toHaveLength(3));
    expect(token()).toBe(before + 1);
  });

  test('an edit and a reanalyse tell them too, an unchanged edit or a refusal does not', async () => {
    await selectRow('B', 'open');
    const before = token();
    await userEvent.click(screen.getByRole('button', { name: '고치기' }));
    await userEvent.click(screen.getByRole('button', { name: '저장' }));
    expect(token()).toBe(before);
    await userEvent.click(screen.getByRole('button', { name: '고치기' }));
    await userEvent.type(screen.getByLabelText('일수'), '1');
    await userEvent.click(screen.getByRole('button', { name: '저장' }));
    await waitFor(() => expect(token()).toBe(before + 1));
    mockPostError(409, { code: 'version_conflict', message: '그 사이 일정이 바뀌었습니다.', detail: null });
    await userEvent.click(screen.getByRole('button', { name: '다시 분석' }));
    expect(await screen.findByText('그 사이 일정이 바뀌었습니다.')).toBeVisible();
    expect(token()).toBe(before + 1);
    await userEvent.click(screen.getByRole('button', { name: '다시 분석' }));
    await waitFor(() => expect(token()).toBe(before + 2));
  });
});
