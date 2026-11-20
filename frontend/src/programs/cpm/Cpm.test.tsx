import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { useUiContext } from '../../os/uiContext';
import { useWindows } from '../../os/windowStore';
import { forgetSchedules } from '../../shared/schedule/scheduleStore';
import { svgMarkup } from './exportPng';
import manifest from './index';
import {
  a, at, bigView, canvas, card, edge, lastBody, mockProgress, mockScenarios, networkSvg, nodeIds, r, renderCpm, schedule, setupCpm, view, writes,
} from './testKit';

beforeEach(() => setupCpm());
afterEach(() => {
  forgetSchedules();
  useUiContext.getState().reset();
  vi.unstubAllGlobals();
});

const button = (name: string | RegExp) => screen.getByRole('button', { name });

test('the manifest opens CPM at 1600×900 in the work group', () => {
  expect(manifest).toMatchObject({ id: 'cpm', name: 'CPM', kind: 'work', tone: 'fuchsia', defaultSize: { w: 1600, h: 900 } });
});

test('the CPM window names the schedule and draws every card and relation with the counts', async () => {
  await renderCpm();
  await waitFor(() => expect(useWindows.getState().wins.find((w) => w.id === 'w1')?.title).toBe('CPM — 5층 사무동 신축'));
  expect(nodeIds()).toEqual(['A', 'B', 'D', 'C']);
  expect(document.querySelectorAll('[data-edge]')).toHaveLength(4);
  expect(screen.getByText('노드 4 · 관계 4 · 크리티컬 3 · 음수 플로트 0')).toBeVisible();
  expect(within(card('B')).getByText('작업 B')).toBeInTheDocument();
  expect(within(card('B')).getByText('계획 내')).toBeInTheDocument();
  expect(edge('D', 'C')).toHaveTextContent('SS+15');
});

test('turning the CPM layer off hides float rows and critical color', async () => {
  await renderCpm();
  expect(card('A').querySelector('.critical')).not.toBeNull();
  expect(within(card('A')).getByText('LS/LF')).toBeInTheDocument();
  await userEvent.click(button('CPM'));
  expect(button('CPM')).toHaveAttribute('aria-pressed', 'false');
  expect(card('A').querySelector('.critical')).toBeNull();
  expect(within(card('A')).queryByText('LS/LF')).toBeNull();
  expect(within(card('A')).queryByText('ES/EF')).toBeNull();
  expect(edge('A', 'B').querySelector('.critical')).toBeNull();
});

test('a card shows paired values in two columns like the mockup', async () => {
  setupCpm(view([a('A', { es: '2027-03-01', ef: '2027-03-05', od: 5, rd: 2 })], []));
  await renderCpm();
  const values = [...card('A').querySelectorAll('.cpm-v')].map((t) => [t.textContent, t.getAttribute('x')]);
  expect(values.slice(0, 2)).toEqual([['03.01', '62'], ['03.05', '150']]);
  expect(values).toContainEqual(['5일', '62']);
  expect(values).toContainEqual(['2일', '150']);
});

test('turning Plan off hides the Plan row and chip; Actual off hides progress and status', async () => {
  setupCpm(view([a('A', { actual_start: '2027-03-01', progress: 0.4 })], []));
  await renderCpm();
  expect(within(card('A')).getByText('Plan 대비')).toBeInTheDocument();
  expect(within(card('A')).getByText('진행 중')).toBeInTheDocument();
  await userEvent.click(button('Plan'));
  expect(within(card('A')).queryByText('Plan 대비')).toBeNull();
  expect(within(card('A')).queryByText('Plan')).toBeNull();
  await userEvent.click(button('Actual'));
  expect(within(card('A')).queryByText('진행 중')).toBeNull();
  expect(within(card('A')).getByText('TF')).toBeInTheDocument();
  expect(card('A').querySelector('[data-progress]')).toBeNull();
});

test('clicking a card selects it in every window and fills the detail panel', async () => {
  await renderCpm();
  await userEvent.click(card('D'));
  expect(schedule().selected).toBe('D');
  expect(schedule().selectedBy).toBe('w1');
  expect(useUiContext.getState().byWindow.w1?.selected_activity).toBe('D');
  const panel = screen.getByRole('region', { name: '상세' });
  expect(within(panel).getByText('D 작업 D')).toBeVisible();
  expect(within(panel).getByText('작업')).toBeVisible();
  expect(within(panel).getByRole('button', { name: 'A → D FS 관계 고치기' })).toBeVisible();
  expect(within(panel).getByRole('button', { name: 'D → C SS+15 관계 고치기' })).toBeVisible();
});

// 리뷰 M4: 카드는 aria-pressed 대신 aria-current, 이름에 크리티컬·상태.
test('a card names its critical mark and status, and the picked card is the current one', async () => {
  await renderCpm();
  expect(screen.getByRole('button', { name: 'A 작업 A, 크리티컬, 미착수' })).toBe(card('A'));
  expect(screen.getByRole('button', { name: 'D 작업 D, 미착수' })).toBe(card('D'));
  expect(card('A')).not.toHaveAttribute('aria-pressed');
  await userEvent.click(card('D'));
  expect(card('D')).toHaveAttribute('aria-current', 'true');
  expect(card('A')).not.toHaveAttribute('aria-current');
});

// 리뷰 M3: Tab 은 카드 하나만 거쳐 확대 단추·상세로 간다. 카드끼리는 화살표, 관계선은 Tab 차례에 없다(상세의 관계 목록으로).
test('Tab stops at one card then leaves the network; relation lines are not tab stops', async () => {
  await renderCpm();
  button('PNG 내보내기').focus();
  await userEvent.tab();
  expect(card('A')).toHaveFocus();
  await userEvent.tab();
  expect(button('확대')).toHaveFocus();
  expect(document.querySelectorAll('[data-node][tabindex="0"]')).toHaveLength(1);
  expect(document.querySelectorAll('[data-edge][tabindex="0"]')).toHaveLength(0);
});

test('arrow keys move between cards by column and row, and Enter picks', async () => {
  await renderCpm();
  card('A').focus();
  await userEvent.keyboard('{ArrowRight}');
  expect(card('B')).toHaveFocus();
  await userEvent.keyboard('{ArrowDown}');
  expect(card('D')).toHaveFocus();
  await userEvent.keyboard('{ArrowRight}');
  expect(card('C')).toHaveFocus();
  expect(card('C')).toHaveAttribute('tabindex', '0');
  expect(card('A')).toHaveAttribute('tabindex', '-1');
  await userEvent.keyboard('{ArrowLeft}{ArrowUp}{Enter}');
  expect(card('B')).toHaveFocus();
  expect(schedule().selected).toBe('B');
});

test('editing a relation saves the successor predecessors', async () => {
  await renderCpm();
  await userEvent.click(edge('B', 'C'));
  await userEvent.selectOptions(screen.getByLabelText('종류'), 'SS');
  await userEvent.clear(screen.getByLabelText('간격'));
  await userEvent.type(screen.getByLabelText('간격'), '2');
  await userEvent.click(button('저장'));
  await waitFor(() => expect(writes()).toHaveLength(1));
  expect(writes()[0][1]).toBe('/api/schedules/1/activities/C/predecessors');
  expect(lastBody()).toEqual({ items: [{ pred: 'B', type: 'SS', lag: 2 }, { pred: 'D', type: 'SS', lag: 15 }], base_version: 1 });
  await waitFor(() => expect(screen.queryByRole('form', { name: '관계 고치기' })).toBeNull());
});

test('a relation from the panel can be deleted; a bad lag is not sent', async () => {
  await renderCpm();
  await userEvent.click(card('D'));
  await userEvent.click(screen.getByRole('button', { name: 'D → C SS+15 관계 고치기' }));
  await userEvent.clear(screen.getByLabelText('간격'));
  await userEvent.type(screen.getByLabelText('간격'), '1.5');
  await userEvent.click(button('저장'));
  expect(screen.getByRole('alert')).toHaveTextContent('간격은 정수(일)로 넣어 주세요.');
  expect(writes()).toEqual([]);
  await userEvent.click(button('삭제'));
  await waitFor(() => expect(lastBody()).toEqual({ items: [{ pred: 'B', type: 'FS', lag: 0 }], base_version: 1 }));
});

test('summary line shows compliance, variance, recovery and finish', async () => {
  mockProgress({ cpm: { plan_compliance: { pct: 83, done: 5, due: 6 }, critical_variance: { days: 4, max_id: 'A2020' }, finish_variance: { days: 4, plan: '2027-11-24', current: '2027-11-28' } } });
  mockScenarios([{ id: 9, recovery: { planned_gain: 5, achieved: 3 } }, { id: 3, recovery: { planned_gain: 2, achieved: 2 } }]);
  await renderCpm();
  expect(await screen.findByText('83%')).toBeVisible();
  expect(screen.getByText('5/6 액티비티')).toBeVisible();
  expect(screen.getByText('최대 A2020')).toBeVisible();
  expect(await screen.findByText('60%')).toBeVisible();
  expect(screen.getByText('3/5일 만회')).toBeVisible();
  expect(screen.getByText(/Plan 11\.24 → 11\.28/)).toBeVisible();
  expect(screen.getAllByText('+4일')).toHaveLength(2);
});

test('no applied recovery says so; missing CPM values show a dash', async () => {
  mockScenarios([{ id: 2, recovery: null }]);
  await renderCpm();
  expect(await screen.findByText('만회 계획 없음')).toBeVisible();
  const summary = screen.getByRole('group', { name: 'CPM 요약' });
  expect(within(summary).getAllByText('—')).toHaveLength(4);
});

// 리뷰 M1: 목표 단축이 없으면 「목표 단축 null일」 대신 「—」.
test('a recovery without a planned gain shows a dash', async () => {
  mockScenarios([{ id: 4, recovery: { planned_gain: null, achieved: 2 } }]);
  await renderCpm();
  const stat = (await screen.findByText('만회 계획 달성률')).parentElement!;
  await waitFor(() => expect(stat).toHaveTextContent('만회 계획 달성률—목표 단축 없음'));
  expect(screen.queryByText(/null/)).toBeNull();
});

test('the summary reads again when the schedule changes', async () => {
  await renderCpm();
  await waitFor(() => expect(progressCalls()).toBe(1));
  await userEvent.click(edge('A', 'B'));
  await userEvent.clear(screen.getByLabelText('간격'));
  await userEvent.type(screen.getByLabelText('간격'), '1');
  await userEvent.click(button('저장'));
  await waitFor(() => expect(progressCalls()).toBe(2));
});

const progressCalls = () => vi.mocked(fetch).mock.calls.filter(([u]) => String(u) === '/api/schedules/1/progress').length;

test('find selects the first match by name or ID and says when nothing matches', async () => {
  await renderCpm();
  await userEvent.type(screen.getByPlaceholderText('코드·이름 검색'), '작업 C');
  await userEvent.click(button('찾기'));
  expect(schedule().selected).toBe('C');
  await userEvent.clear(screen.getByPlaceholderText('코드·이름 검색'));
  await userEvent.type(screen.getByPlaceholderText('코드·이름 검색'), 'd{Enter}');
  expect(schedule().selected).toBe('D');
  await userEvent.clear(screen.getByPlaceholderText('코드·이름 검색'));
  await userEvent.type(screen.getByPlaceholderText('코드·이름 검색'), '없는 것');
  await userEvent.click(button('찾기'));
  expect(screen.getByRole('alert')).toHaveTextContent('찾는 액티비티가 없습니다: 없는 것');
});

test('critical-only and selected views redraw the network', async () => {
  await renderCpm();
  await userEvent.click(button('크리티컬 경로만'));
  expect(nodeIds()).toEqual(['A', 'B', 'C']);
  expect(button('선택 항목')).toBeDisabled();
  await userEvent.click(card('B'));
  await userEvent.click(button('선택 항목'));
  expect(nodeIds().sort()).toEqual(['A', 'B', 'C']);
  await userEvent.click(button('전체'));
  expect(nodeIds()).toHaveLength(4);
});

test('finding a card hidden by the view switches back to the whole network', async () => {
  await renderCpm();
  await userEvent.click(button('크리티컬 경로만'));
  await userEvent.type(screen.getByPlaceholderText('코드·이름 검색'), 'D{Enter}');
  expect(schedule().selected).toBe('D');
  expect(nodeIds()).toContain('D');
});

test('the WBS filter shows one top group', async () => {
  setupCpm(view([a('A', { wbs: '1' }), a('B', { wbs: '2' })], [r('A', 'B')]));
  await renderCpm();
  await userEvent.selectOptions(screen.getByRole('combobox', { name: 'WBS' }), '2');
  expect(nodeIds()).toEqual(['B']);
  await userEvent.selectOptions(screen.getByRole('combobox', { name: 'WBS' }), '');
  expect(nodeIds()).toEqual(['A', 'B']);
});

// 리뷰 M6: 선택 항목 보기는 WBS 로 거르지 않으므로 WBS 고르기를 끄고 까닭을 보인다.
test('in the selected view the WBS picker is off and says why', async () => {
  await renderCpm();
  await userEvent.click(card('B'));
  await userEvent.click(button('선택 항목'));
  const picker = screen.getByRole('combobox', { name: 'WBS' });
  expect(picker).toBeDisabled();
  expect(picker.closest('[title]')).toHaveAttribute('title', '선택 항목 보기는 WBS 로 거르지 않습니다');
  await userEvent.click(button('전체'));
  expect(picker).toBeEnabled();
});

/** 카드를 누르고 (dx, dy) 옮겨 놓는다. */
function drag(el: Element, dx: number, dy: number) {
  fireEvent.pointerDown(el, { clientX: 300, clientY: 300, button: 0 });
  fireEvent.pointerMove(document.body, { clientX: 300 + dx / 2, clientY: 300 + dy / 2 });
  fireEvent.pointerMove(document.body, { clientX: 300 + dx, clientY: 300 + dy });
  fireEvent.pointerUp(document.body, { clientX: 300 + dx, clientY: 300 + dy });
}

test('dragging a card only moves it in this window; its lines follow; auto layout puts it back', async () => {
  await renderCpm();
  const before = edge('A', 'B').querySelector('path')!.getAttribute('d');
  const other = edge('D', 'C').querySelector('path')!.getAttribute('d');
  drag(card('B'), 40, 300);
  expect(at('B')).toEqual([408, 324]);
  expect(edge('A', 'B').querySelector('path')!.getAttribute('d')).not.toBe(before);
  expect(edge('D', 'C').querySelector('path')!.getAttribute('d')).toBe(other);
  expect(writes()).toEqual([]);
  expect(schedule().selected).toBeNull();
  await userEvent.click(button('자동 배치'));
  expect(at('B')).toEqual([368, 24]);
});

test('zoom steps by 1.25 at the bottom left', async () => {
  await renderCpm();
  const w = () => Number(networkSvg().getAttribute('width'));
  const w0 = w();
  await userEvent.click(button('확대'));
  expect(w()).toBeCloseTo(w0 * 1.25, 5);
  await userEvent.click(button('축소'));
  await userEvent.click(button('축소'));
  expect(w()).toBeCloseTo(w0 / 1.25, 5);
});

test('a card picked in another window is brought to the middle', async () => {
  await renderCpm();
  act(() => schedule().select('C', 'w2'));
  await waitFor(() => expect(canvas().scrollLeft).toBe(712 + 124));
  expect(canvas().scrollTop).toBe(24 + 84);
});

test('params.activity selects that card and brings it to the middle', async () => {
  await renderCpm({ id: '1', activity: 'D' });
  await waitFor(() => expect(schedule().selected).toBe('D'));
  await waitFor(() => expect(canvas().scrollTop).toBe(224 + 84));
  expect(canvas().scrollLeft).toBe(368 + 124);
});

test('png export serializes the network svg', async () => {
  await renderCpm();
  const xml = svgMarkup(networkSvg());
  expect(xml).toContain('data-node="A"');
  expect(xml).toContain('xmlns="http://www.w3.org/2000/svg"');
});

test('two hundred nodes render', async () => {
  setupCpm(bigView(200));
  await renderCpm();
  expect(document.querySelectorAll('[data-node]')).toHaveLength(200);
  expect(screen.getByText(/^노드 200 · /)).toBeVisible();
});
