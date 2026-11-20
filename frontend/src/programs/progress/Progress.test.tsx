import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { useCurrentSchedule } from '../../os/currentSchedule';
import { useWindows } from '../../os/windowStore';
import { forgetSchedules, scheduleStore } from '../../shared/schedule/scheduleStore';
import { setup } from '../../shared/schedule/testKit';
import manifest from './index';
import Progress from './Progress';
import { lastUrl, mockProgress, P, progressUrls, stubProgressApi } from './testKit';

const downloadSvgImage = vi.hoisted(() => vi.fn(async () => 'png' as const));
vi.mock('../../shared/gantt/exportImage', () => ({ downloadSvgImage }));

let openSpy: ReturnType<typeof vi.fn>;

beforeEach(() => {
  setup();
  stubProgressApi();
  openSpy = vi.fn();
  useWindows.setState({ open: openSpy } as never);
});
afterEach(() => {
  forgetSchedules();
  useCurrentSchedule.setState({ current: null });
  vi.unstubAllGlobals();
  downloadSvgImage.mockClear();
});

const show = () => render(<Progress windowId="w1" params={{ id: '1' }} />);
const wbsTable = () => screen.getByRole('table', { name: 'WBS 묶음별' });

test('the manifest opens 공정률 at 1400×860 in the work group', () => {
  expect(manifest).toMatchObject({ id: 'progress', name: '공정률', kind: 'work', tone: 'rose', defaultSize: { w: 1400, h: 860 } });
});

test('kpis show plan, actual, gap and spi', async () => {
  mockProgress(P);
  show();
  expect(await screen.findByText('20.0%')).toBeVisible();
  expect(screen.getByText('10.0%')).toBeVisible();
  expect(screen.getByText('−10.0%p')).toBeVisible();
  expect(screen.getByText('0.50')).toBeVisible();
  expect(screen.getByText('1.00 이상이면 계획대로')).toBeVisible();
  expect(screen.getByText('진행 1 · 지연 2')).toBeVisible();
});

test('late status banner', async () => {
  show();
  expect(await screen.findByText(/계획보다 늦음/)).toBeVisible();
  expect(screen.getByText('준공 +1일')).toBeVisible();
  expect(screen.queryByText(/준공 여유/)).toBeNull(); // 기한이 없으면 여유도 없다
});

test('on or ahead of plan the banner says so with the deadline float', async () => {
  mockProgress({ ...P, spi: 1.05, finish: { ...P.finish, deadline: '2027-03-19', deadline_float: 4 } });
  show();
  expect(await screen.findByText('계획대로')).toBeVisible();
  expect(screen.queryByText(/계획보다 늦음/)).toBeNull();
  expect(screen.getByText('· 준공 여유 4일')).toBeVisible();
});

test('the toolbar shows the data date, unit and weight mode from the server', async () => {
  mockProgress({ ...P, weight_mode: 'manual' });
  show();
  expect(await screen.findByText('가중치: 직접 입력')).toBeVisible();
  expect(screen.getByRole('group', { name: '공정률 도구' })).toHaveTextContent('2027.03.03');
  expect(screen.getByRole('button', { name: '주' })).toHaveAttribute('aria-pressed', 'true');
});

test('unit switch refetches by month', async () => {
  show();
  await screen.findByText('20.0%');
  await userEvent.click(screen.getByRole('button', { name: '월' }));
  expect(lastUrl()).toContain('unit=month');
  expect(screen.getByRole('button', { name: '월' })).toHaveAttribute('aria-pressed', 'true');
  expect(await screen.findByText('공정률 — 누적(선)과 월간(막대)')).toBeVisible();
});

test('a new schedule version or weight mode refetches', async () => {
  show();
  await screen.findByText('20.0%');
  const before = progressUrls().length;
  act(() => setView({ version: 2 }));
  await waitFor(() => expect(progressUrls().length).toBe(before + 1));
  act(() => setView({ weight_mode: 'manual' }));
  await waitFor(() => expect(progressUrls().length).toBe(before + 2));
});

test('milestone and wbs tables', async () => {
  show();
  expect(await screen.findByText('지연 +1일')).toBeVisible();
  expect(within(wbsTable()).getByText('−20.0')).toBeVisible();
  expect(within(wbsTable()).getByText('1 기초')).toBeVisible();
  expect(within(screen.getByRole('table', { name: '마일스톤 추적' })).getByText('03.12')).toBeVisible();
});

test('lookahead marks blocked starts', async () => {
  show();
  expect(await screen.findByText('선행 미완료: A')).toBeVisible();
  expect(screen.getByText('03.03 ~ 03.23')).toBeVisible();
});

test('buttons open the delay window and the chat', async () => {
  show();
  await userEvent.click(await screen.findByRole('button', { name: '만회 계획 요청' }));
  expect(openSpy).toHaveBeenCalledWith('chat', { ask: '지연을 만회할 계획을 만들어 줘' });
  await userEvent.click(screen.getByRole('button', { name: '지연 기록 열기' }));
  expect(openSpy).toHaveBeenCalledWith('delays', { id: '1' });
});

test('assumed data date is labeled', async () => {
  mockProgress({ ...P, data_date_assumed: true });
  show();
  expect(await screen.findByText(/오늘로 가정/)).toBeVisible();
});

test('activities without a plan are noted only when there are some', async () => {
  show();
  await screen.findByText('20.0%');
  expect(screen.queryByText(/Plan 이 없는 액티비티/)).toBeNull();
  mockProgress({ ...P, added_after_plan: { count: 3, actual_pct: 12.5 } });
  await userEvent.click(screen.getByRole('button', { name: '월' }));
  expect(await screen.findByText(/Plan 이 없는 액티비티 3개/)).toBeVisible();
});

test('a server refusal is shown in Korean', async () => {
  mockProgress({ status: 422, body: { code: 'schedule_invalid', message: '선후 관계가 고리를 이룹니다.', detail: null } });
  show();
  expect(await screen.findByRole('alert')).toHaveTextContent('선후 관계가 고리를 이룹니다.');
});

test('image export draws the S-curve sheet and downloads it', async () => {
  show();
  await screen.findByText('20.0%');
  await userEvent.click(screen.getByRole('button', { name: '그림 내보내기' }));
  await waitFor(() => expect(downloadSvgImage).toHaveBeenCalledTimes(1));
  const [svg, name] = downloadSvgImage.mock.calls[0] as unknown as [SVGSVGElement, string];
  expect(name).toBe('5층 사무동 신축 v1 공정률');
  expect(svg.textContent).toContain('Data Date 03.03 · 계획 20.0% · 실적 10.0%');
});

/** 일정 저장소의 보기 몇 칸을 바꾼다(다른 창이 고치거나 가중치 방식을 바꾼 것처럼). */
function setView(over: Record<string, unknown>) {
  const store = scheduleStore(1);
  store.setState({ view: { ...store.getState().view!, ...over } });
}
