import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Suspense } from 'react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { useApprovals } from '../../os/approvals';
import { useCurrentSchedule } from '../../os/currentSchedule';
import { useUiContext } from '../../os/uiContext';
import { useWindows } from '../../os/windowStore';
import Compare from './Compare';
import manifest from './index';
import {
  C, CURRENT, DELAY, PLAN, RECOVERY, S,
  compareUrls, holdNext, lastBody, lastUrl, mockCompare, mockDiscard, mockSubmit, mockSummary, mockVersions, stubCompareApi, summaryCalls, V, writes,
} from './testKit';

let openSpy: ReturnType<typeof vi.fn>;

beforeEach(() => {
  stubCompareApi();
  openSpy = vi.fn();
  const win = { id: 'w1', programId: 'compare', title: '비교판', x: 0, y: 48, w: 1600, h: 900, z: 1, minimized: false, maximized: false };
  useWindows.setState({ wins: [win], open: openSpy } as never);
  useCurrentSchedule.setState({ current: { id: 1, name: '5층 사무동 신축' } });
});
afterEach(() => {
  useCurrentSchedule.setState({ current: null });
  useUiContext.getState().reset();
  vi.unstubAllGlobals();
});

const show = (params: Record<string, string> = { id: '1' }) => render(<Compare windowId="w1" params={params} />);
/** 비교판을 열고 같은 차트가 그려질 때까지 기다린다. */
const shown = async (params?: Record<string, string>) => {
  show(params);
  await screen.findByTestId('row-B');
};
const summaryRow = (name: string) => screen.getByRole('cell', { name }).closest('tr')!;
const bar = (id: string, side: 'base' | 'other') => screen.findByTestId(`bar-${id}-${side}`);
const diffRow = (id: string) => screen.getByTestId(`diff-${id}`);
const pane = (i: number) => screen.getAllByTestId('pane')[i];
const submitButton = () => screen.findByRole('button', { name: '이 안을 반영 (승인함으로)' });
const tools = () => screen.getByRole('group', { name: '비교판 도구' });
const nextFrame = () => new Promise((ok) => requestAnimationFrame(() => ok(null)));

test('summary table lists plans', async () => {
  mockSummary(S);
  show();
  expect(await screen.findByRole('cell', { name: '만회안 A · 병행 우선' })).toBeVisible();
  expect(within(summaryRow('만회안 A · 병행 우선')).getByText('2027.03.16')).toBeVisible();
  const cur = within(summaryRow('현재 일정 (버전 3)'));
  expect(cur.getByText('+2일')).toBeVisible(); // Plan 대비
  expect(cur.getByText('−3일')).toBeVisible(); // 기한 여유(늦음)
  expect(cur.getByText('타워크레인 2/1')).toBeVisible();
  const rec = within(summaryRow('만회안 A · 병행 우선'));
  expect(rec.getByText('−1일')).toBeVisible();
  expect(rec.getByText('0일')).toBeVisible(); // 기한 여유 0
  expect(rec.getByText('A 절반 지점에서 B 시작')).toBeVisible();
  expect(rec.getByText('자동 점검 안 됨 1')).toBeVisible(); // 점검하지 않은 조건을 통과로 보이지 않는다
  expect(within(screen.getByRole('table', { name: '여러 안 요약' })).getAllByRole('row')).toHaveLength(1 + S.sides.length);
});

test('a plan without a computed Plan shows a dash, not zero', async () => {
  mockSummary({ sides: [{ ...CURRENT, plan_delta: null, deadline: null, deadline_float: null }, RECOVERY] });
  show();
  const cur = within(await screen.findByRole('cell', { name: '현재 일정 (버전 3)' }).then((c) => c.closest('tr')!));
  expect(cur.getAllByText('—')).toHaveLength(2); // Plan 대비 · 기한 여유
});

test('overlay colors pulled bars', async () => {
  mockCompare(C);
  show();
  expect(await bar('B', 'other')).toHaveClass('pulled');
  expect(await bar('E', 'other')).toHaveClass('pushed');
  expect(await bar('A', 'other')).toHaveClass('same');
  expect(await bar('B', 'base')).not.toHaveClass('pulled');
});

test('overlay places bars from server dates on one scale', async () => {
  await shown();
  const xOf = async (id: string, side: 'base' | 'other') => Number((await bar(id, side)).getAttribute('x'));
  // 같은 날 시작(A 3/1)은 같은 x, 비교의 B(3/4)는 기준의 B(3/8)보다 왼쪽
  expect(await xOf('A', 'base')).toBe(await xOf('A', 'other'));
  expect(await xOf('B', 'other')).toBeLessThan(await xOf('B', 'base'));
  expect(await xOf('B', 'base')).toBe(await xOf('E', 'base')); // 둘 다 3/8
});

test('the deadline line is drawn only when there is a deadline float', async () => {
  await shown();
  expect(screen.getByText('기한 03.16')).toBeInTheDocument();
  // 기한은 그날 끝(간트차트와 같음): 3/16 에 끝나는 비교의 C 막대 오른쪽 끝과 같은 자리
  const c = await bar('C', 'other');
  const end = Number(c.getAttribute('x')) + Number(c.getAttribute('width'));
  expect(Number(screen.getByTestId('deadline-2027-03-16').getAttribute('x1'))).toBeCloseTo(end, 6);
});

test('no deadline means no deadline line', async () => {
  const none = { deadline: null, deadline_float: null };
  mockCompare({ ...C, base: { ...C.base, ...none }, other: { ...C.other, ...none } });
  await shown();
  expect(screen.queryByTestId(/^deadline-/)).toBeNull();
});

test('changed-only hides same rows', async () => {
  await shown();
  await userEvent.click(screen.getByRole('button', { name: '달라진 것만' }));
  expect(screen.queryByTestId('row-A')).toBeNull();
  expect(screen.getByTestId('row-B')).toBeVisible();
  await userEvent.click(screen.getByRole('button', { name: '전체' }));
  expect(screen.getByTestId('row-A')).toBeVisible();
});

test('diff table shows workday deltas', async () => {
  await shown();
  await userEvent.click(screen.getByRole('button', { name: '차이 표' }));
  const b = within(diffRow('B'));
  expect(b.getByText('−3일')).toBeVisible();
  expect(b.getByText('−2일')).toBeVisible();
  expect(b.getByText('당겨짐')).toBeVisible();
  expect(b.getByText('5 → 4')).toBeVisible();
  expect(within(diffRow('E')).getAllByText('+2일')).toHaveLength(2);
  expect(within(diffRow('A')).getByText('같음')).toBeVisible();
});

test('side by side scrolls together', async () => {
  await shown();
  await userEvent.click(screen.getByRole('button', { name: '좌우 비교' }));
  fireEvent.scroll(pane(0), { target: { scrollTop: 120 } });
  expect(pane(1).scrollTop).toBe(120);
  await nextFrame();
  fireEvent.scroll(pane(1), { target: { scrollTop: 40 } });
  expect(pane(0).scrollTop).toBe(40);
  expect(within(pane(0)).getByTestId('bar-B-base')).toBeInTheDocument();
  expect(within(pane(1)).getByTestId('bar-B-other')).toHaveClass('pulled');
});

test('the scroll a pane gets from being synced does not sync back (no ping-pong)', async () => {
  await shown();
  await userEvent.click(screen.getByRole('button', { name: '좌우 비교' }));
  fireEvent.scroll(pane(0), { target: { scrollTop: 120 } });
  // 옮긴 판에서 돌아온 스크롤(브라우저가 끝에 맞춰 100 으로 멈춤)은 다시 옮기지 않는다
  fireEvent.scroll(pane(1), { target: { scrollTop: 100 } });
  expect(pane(0).scrollTop).toBe(120);
  await nextFrame();
  fireEvent.scroll(pane(1), { target: { scrollTop: 40 } }); // 사람이 굴린 것은 따라간다
  expect(pane(0).scrollTop).toBe(40);
});

test('submit sends title then opens approvals', async () => {
  mockSubmit({ approval_id: 7, applied: false, status: 'submitted' });
  const before = useApprovals.getState().ticks;
  await shown();
  await userEvent.click(await submitButton());
  expect(screen.getByRole('textbox', { name: '제목' })).toHaveValue('만회안 A · 병행 우선');
  await userEvent.click(screen.getByRole('button', { name: '보내기' }));
  await waitFor(() => expect(openSpy).toHaveBeenCalledWith('approvals', { id: '7' }));
  expect(lastBody()).toEqual({ title: '만회안 A · 병행 우선' });
  expect(writes().at(-1)?.slice(0, 2)).toEqual(['POST', '/api/schedules/1/scenarios/5/submit']);
  expect(useApprovals.getState().ticks).toBeGreaterThan(before); // 승인 배지를 다시 읽음
  expect(screen.queryByRole('dialog')).toBeNull();
  await waitFor(() => expect(tools()).toHaveFocus()); // 포커스가 body 로 떨어지지 않는다
});

test('a submit conflict shows the server message and a stale copy turns the send button off', async () => {
  mockSubmit({ status: 409, body: { code: 'scenario_stale', message: '기준 일정이 바뀌었습니다. 복사본을 다시 만들어 주세요.', detail: null } });
  await shown();
  await userEvent.click(await submitButton());
  await userEvent.click(screen.getByRole('button', { name: '보내기' }));
  expect(await screen.findByText('기준 일정이 바뀌었습니다. 복사본을 다시 만들어 주세요.')).toBeVisible();
  expect(screen.getByRole('button', { name: '보내기' })).toBeDisabled();
  expect(openSpy).not.toHaveBeenCalled();
});

test('stale scenario cannot be submitted', async () => {
  mockCompare({ ...C, other: { ...C.other, stale: true } });
  show();
  expect(await submitButton()).toBeDisabled();
  expect(screen.getByText('기준 일정이 바뀌었습니다')).toBeVisible();
  expect(await submitButton()).toHaveAccessibleDescription('기준 일정이 바뀌었습니다');
});

test('only open copies get the stale badge: a submitted stale copy shows 승인 대기 only', async () => {
  mockSummary({ sides: [CURRENT, PLAN, { ...RECOVERY, stale: true, status: 'submitted' }] });
  mockCompare({ ...C, other: { ...C.other, stale: true, status: 'submitted' } });
  await shown();
  expect(screen.queryByText('기준 일정이 바뀌었습니다')).toBeNull();
  expect(screen.getAllByText('승인 대기').length).toBeGreaterThan(0);
});

test('a discarded copy says so and offers no copy actions', async () => {
  mockCompare({ ...C, other: { ...C.other, stale: true, status: 'discarded' } });
  await shown();
  expect(screen.getByText('버린 복사본')).toBeVisible();
  expect(screen.queryByText('기준 일정이 바뀌었습니다')).toBeNull();
  expect(screen.queryByRole('button', { name: '이 안을 반영 (승인함으로)' })).toBeNull();
  expect(screen.queryByRole('button', { name: '복사본 버리기' })).toBeNull();
});

test('an applied copy is always stale but shows no stale badge and cannot be sent again', async () => {
  mockCompare({ ...C, other: { ...C.other, stale: true, status: 'applied' } });
  await shown();
  expect(screen.queryByText('기준 일정이 바뀌었습니다')).toBeNull();
  expect(screen.queryByRole('button', { name: '이 안을 반영 (승인함으로)' })).toBeNull();
  expect(screen.queryByRole('button', { name: '복사본 버리기' })).toBeNull();
});

test('comparing with a version offers no copy actions', async () => {
  mockCompare({ ...C, other: { ...PLAN, ref: 'v:2', label: '버전 2', status: null } });
  await shown();
  expect(screen.queryByRole('button', { name: '이 안을 반영 (승인함으로)' })).toBeNull();
  expect(screen.queryByRole('button', { name: '복사본 버리기' })).toBeNull();
  expect(screen.getByRole('button', { name: '+ 만약에 복사본' })).toBeEnabled();
});

test('what-if asks the agent through chat', async () => {
  await shown();
  await userEvent.click(screen.getByRole('button', { name: '+ 만약에 복사본' }));
  await userEvent.type(screen.getByRole('textbox'), '크레인 2대로 하면?');
  await userEvent.click(screen.getByRole('button', { name: '에이전트에게 맡기기' }));
  expect(openSpy).toHaveBeenCalledWith('chat', { ask: '만약에 복사본을 만들어 줘: 크레인 2대로 하면?' });
  expect(screen.queryByRole('dialog')).toBeNull();
});

test('params pick base and other', async () => {
  render(<Compare windowId="w1" params={{ id: '1', base: 's:4', other: 's:5' }} />);
  await waitFor(() => expect(lastUrl()).toContain('base=s:4&other=s:5'));
});

test('without params the base is current and the other is the newest open copy', async () => {
  show();
  await waitFor(() => expect(lastUrl()).toBe('/api/schedules/1/compare?base=current&other=s:5'));
  expect(compareUrls()).toHaveLength(1);
});

test('a submitted copy also counts as open for the default other (server meaning of 열린)', async () => {
  mockSummary({ sides: [CURRENT, PLAN, { ...RECOVERY, status: 'submitted' }] });
  show();
  await waitFor(() => expect(lastUrl()).toBe('/api/schedules/1/compare?base=current&other=s:5'));
});

test('without a copy the other is the Plan', async () => {
  mockSummary({ sides: [CURRENT, PLAN] });
  show();
  await waitFor(() => expect(lastUrl()).toBe('/api/schedules/1/compare?base=current&other=plan'));
});

test('without a Plan row the other is the previous version and Plan is not offered', async () => {
  mockSummary({ sides: [CURRENT] });
  show();
  await waitFor(() => expect(lastUrl()).toBe('/api/schedules/1/compare?base=current&other=v:2'));
  await screen.findByTestId('row-B');
  await userEvent.click(screen.getByRole('button', { name: /^기준: / }));
  const fixed = within(screen.getByRole('group', { name: '현재·Plan' }));
  expect(fixed.getAllByRole('option').map((o) => o.textContent)).toEqual(['현재 일정 (버전 3)']);
});

test('without a Plan row or an earlier version the other is current', async () => {
  mockSummary({ sides: [CURRENT] });
  mockVersions([V[0]]);
  show();
  await waitFor(() => expect(lastUrl()).toBe('/api/schedules/1/compare?base=current&other=current'));
});

test('a malformed ref in params falls back to the defaults', async () => {
  show({ id: '1', base: 'x:1', other: 'drop table' });
  await waitFor(() => expect(lastUrl()).toBe('/api/schedules/1/compare?base=current&other=s:5'));
});

test('new params on the open window pick new plans', async () => {
  const { rerender } = render(<Compare windowId="w1" params={{ id: '1', other: 's:5' }} />);
  await waitFor(() => expect(lastUrl()).toContain('other=s:5'));
  rerender(<Compare windowId="w1" params={{ id: '1', base: 's:4', other: 's:9' }} />);
  await waitFor(() => expect(lastUrl()).toContain('base=s:4&other=s:9'));
});

test('new params also re-read the summary so a copy the agent just made is listed', async () => {
  const { rerender } = render(<Compare windowId="w1" params={{ id: '1' }} />);
  await screen.findByTestId('row-B');
  const reads = summaryCalls();
  mockSummary({ sides: [...S.sides, { ...RECOVERY, ref: 's:9', label: '만약에 · 크레인 2대' }] });
  rerender(<Compare windowId="w1" params={{ id: '1', base: 'current', other: 's:9' }} />);
  expect(await screen.findByRole('cell', { name: '만약에 · 크레인 2대' })).toBeVisible();
  expect(summaryCalls()).toBe(reads + 1);
});

test('each pickable summary row has a real button in its plan cell; the base row has none', async () => {
  await shown();
  expect(within(summaryRow('현재 일정 (버전 3)')).queryByRole('button')).toBeNull();
  within(summaryRow('지연 반영안 (1건)')).getByRole('button', { name: '지연 반영안 (1건)' }).focus();
  await userEvent.keyboard('{Enter}');
  await waitFor(() => expect(lastUrl()).toBe('/api/schedules/1/compare?base=current&other=s:4'));
});

test('a refetch keeps the summary and the chart on screen with a 갱신 중 marker', async () => {
  await shown();
  const release = holdNext('compare');
  await userEvent.click(within(summaryRow('지연 반영안 (1건)')).getByRole('button'));
  expect(await screen.findByText('갱신 중')).toBeVisible();
  expect(screen.getByTestId('row-B')).toBeVisible();
  expect(screen.getByRole('cell', { name: '만회안 A · 병행 우선' })).toBeVisible();
  release();
  await waitFor(() => expect(screen.queryByText('갱신 중')).toBeNull());
});

test('clicking a summary row makes that plan the other', async () => {
  await shown();
  await userEvent.click(within(summaryRow('지연 반영안 (1건)')).getByText('2027.03.19'));
  await waitFor(() => expect(lastUrl()).toBe('/api/schedules/1/compare?base=current&other=s:4'));
});

test('the picker groups plans, versions and copies and finds by text', async () => {
  await shown();
  await userEvent.click(screen.getByRole('button', { name: '비교: 만회안 A · 병행 우선' }));
  expect(within(screen.getByRole('group', { name: '현재·Plan' })).getAllByRole('option')).toHaveLength(2);
  expect(within(screen.getByRole('group', { name: '버전' })).getAllByRole('option')).toHaveLength(3);
  expect(within(screen.getByRole('group', { name: '만약에 복사본' })).getAllByRole('option')).toHaveLength(2);
  await userEvent.type(screen.getByRole('combobox', { name: '비교 안 찾기' }), '실적');
  expect(screen.getAllByRole('option')).toHaveLength(1);
  await userEvent.click(screen.getByRole('option', { name: /버전 2/ }));
  await waitFor(() => expect(lastUrl()).toBe('/api/schedules/1/compare?base=current&other=v:2'));
  expect(screen.queryByRole('combobox')).toBeNull();
});

test('the picker marks stale copies but not applied ones', async () => {
  mockSummary({ sides: [CURRENT, PLAN, { ...RECOVERY, stale: true }, { ...DELAY, stale: true, status: 'applied' }] });
  await shown();
  await userEvent.click(screen.getByRole('button', { name: /^기준: / }));
  const copies = within(screen.getByRole('group', { name: '만약에 복사본' }));
  expect(copies.getByRole('option', { name: /만회안 A/ })).toHaveTextContent('낡음');
  expect(copies.getByRole('option', { name: /지연 반영안/ })).not.toHaveTextContent('낡음');
  await userEvent.click(copies.getByRole('option', { name: /지연 반영안/ }));
  await waitFor(() => expect(lastUrl()).toBe('/api/schedules/1/compare?base=s:4&other=s:5'));
});

test('discarding the copy asks first, deletes it and compares the next default', async () => {
  await shown();
  await userEvent.click(screen.getByRole('button', { name: '복사본 버리기' }));
  expect(writes()).toEqual([]);
  mockSummary({ sides: [CURRENT, PLAN, DELAY] });
  const reads = summaryCalls();
  const release = holdNext('summary');
  await userEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: '버리기' }));
  // 다시 읽는 동안 앞 요약·차트는 그대로(빈 화면 아님)
  expect(await screen.findByText('갱신 중')).toBeVisible();
  expect(screen.getByRole('table', { name: '여러 안 요약' })).toBeVisible();
  expect(screen.getByTestId('row-B')).toBeVisible();
  release();
  await waitFor(() => expect(lastUrl()).toBe('/api/schedules/1/compare?base=current&other=s:4'));
  expect(writes()).toEqual([['DELETE', '/api/schedules/1/scenarios/5', undefined]]);
  expect(summaryCalls()).toBe(reads + 1);
  expect(compareUrls().filter((u) => u.endsWith('other=s:5'))).toHaveLength(1); // 버린 복사본을 다시 읽지 않는다
  await waitFor(() => expect(tools()).toHaveFocus());
});

test('a refused discard shows the server message', async () => {
  mockDiscard({ status: 409, body: { code: 'scenario_locked', message: '승인을 기다리거나 반영된 복사본은 버릴 수 없습니다.', detail: null } });
  await shown();
  await userEvent.click(screen.getByRole('button', { name: '복사본 버리기' }));
  await userEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: '버리기' }));
  expect(await screen.findByText('승인을 기다리거나 반영된 복사본은 버릴 수 없습니다.')).toBeVisible();
});

test('a compare error shows the server message', async () => {
  mockCompare({ status: 422, body: { code: 'invalid_ref', message: '비교할 안을 찾을 수 없습니다: s:999', detail: null } });
  show({ id: '1', other: 's:999' });
  expect(await screen.findByText('비교할 안을 찾을 수 없습니다: s:999')).toBeVisible();
});

test('the window title and screen context name the schedule', async () => {
  await shown();
  expect(useWindows.getState().wins[0].title).toBe('비교판 — 5층 사무동 신축');
  expect(useUiContext.getState().byWindow.w1).toEqual({ program: 'compare', schedule_id: 1 });
});

test('a schedule other than the current one is named from the schedule list', async () => {
  useCurrentSchedule.setState({ current: { id: 2, name: '가상 부품 공장' } });
  await shown();
  await waitFor(() => expect(useWindows.getState().wins[0].title).toBe('비교판 — 5층 사무동 신축'));
});

test('with no schedule it asks to pick one', () => {
  useCurrentSchedule.setState({ current: null });
  render(<Compare windowId="w1" />);
  expect(screen.getByText('메뉴바에서 일정을 고르세요.')).toBeVisible();
  expect(compareUrls()).toEqual([]);
});

test('the manifest opens the compare board', async () => {
  const Screen = manifest.component;
  render(
    <Suspense fallback={null}>
      <Screen windowId="w1" params={{ id: '1' }} />
    </Suspense>,
  );
  expect(await screen.findByRole('cell', { name: '만회안 A · 병행 우선' })).toBeVisible();
});
