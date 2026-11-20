import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { useSchedulePreview } from '../../os/schedulePreview';
import { forgetSchedules } from '../../shared/schedule/scheduleStore';
import { makeView, mockPatch, schedule, writes } from './testKit';
import { bar, chartBody, leftHeaders, leftRow, num, pxPerDay, renderGantt, setupGantt, tool } from './testKit';

beforeEach(() => setupGantt());
afterEach(() => {
  localStorage.clear(); // 열 고르기는 사용자별로 기억된다
  vi.useRealTimers();
  vi.restoreAllMocks();
  forgetSchedules();
  useSchedulePreview.getState().reset();
});

const toolbar = () => screen.getByRole('toolbar', { name: '간트 도구' });
const viewportX = (el: Element | null, attr = 'x') => num(el, attr) - chartBody().scrollLeft;

test('toolbar has the 8-2 tools and no dead buttons (each disabled one says why)', async () => {
  await renderGantt();
  const names = within(toolbar()).getAllByRole('button').map((b) => b.getAttribute('aria-label') ?? b.textContent);
  for (const n of ['Plan', 'Actual', 'CPM', '축소', '확대', '맞춤', '선택 맞춤', 'Data Date', '오늘', '이전 기간', '다음 기간', 'WBS', '자원', '모두 펼치기', '모두 접기', '열', '범례', '되돌리기', '다시 하기', 'CSV 내보내기', '그림 내보내기'])
    expect(names).toContain(n);
  expect(names).not.toContain('일정');
  for (const b of within(toolbar()).getAllByRole('button')) if ((b as HTMLButtonElement).disabled) expect(b.getAttribute('title')).toBeTruthy();
});

test('zoom changes pxPerDay by 1.25', async () => {
  await renderGantt();
  const before = pxPerDay();
  await userEvent.click(screen.getByRole('button', { name: '확대' }));
  expect(pxPerDay()).toBeCloseTo(before * 1.25);
  await userEvent.click(screen.getByRole('button', { name: '축소' }));
  await userEvent.click(screen.getByRole('button', { name: '축소' }));
  expect(pxPerDay()).toBeCloseTo(before / 1.25);
});

test('맞춤 goes back to the whole schedule after zooming', async () => {
  await renderGantt();
  const fit = pxPerDay();
  await userEvent.click(tool('확대'));
  await userEvent.click(tool('확대'));
  await userEvent.click(tool('맞춤'));
  expect(pxPerDay()).toBeCloseTo(fit);
  expect(chartBody().scrollLeft).toBe(0);
});

test('선택 맞춤 zooms to the selected activity', async () => {
  await renderGantt();
  expect(tool('선택 맞춤')).toBeDisabled();
  await userEvent.click(leftRow('A3010')!);
  const fit = pxPerDay();
  await userEvent.click(tool('선택 맞춤'));
  expect(pxPerDay()).toBeGreaterThan(fit * 3);
  expect(viewportX(bar('A3010'))).toBeCloseTo(2 * pxPerDay(), 0);
});

test('Data Date and 이전/다음 기간 scroll the chart', async () => {
  await renderGantt();
  for (let i = 0; i < 6; i += 1) await userEvent.click(tool('확대'));
  await userEvent.click(tool('Data Date'));
  const at = viewportX(document.querySelector('[data-vline="data"]'), 'x1');
  expect(at).toBeGreaterThan(0);
  expect(at).toBeLessThan(1000);
  const s0 = chartBody().scrollLeft;
  await userEvent.click(tool('다음 기간'));
  expect(chartBody().scrollLeft).toBeGreaterThan(s0);
  await userEvent.click(tool('이전 기간'));
  expect(chartBody().scrollLeft).toBeCloseTo(s0, 0);
});

test('오늘 scrolls to today inside the schedule', async () => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date('2027-08-16T03:00:00Z'));
  await renderGantt();
  for (let i = 0; i < 6; i += 1) await userEvent.click(tool('확대'));
  await userEvent.click(tool('오늘'));
  const at = viewportX(document.querySelector('[data-vline="today"]'), 'x1');
  expect(at).toBeGreaterThan(0);
  expect(at).toBeLessThan(1000);
  expect(document.querySelector('[data-mark="today"]')).toHaveTextContent('오늘');
});

test('오늘 outside the schedule says so instead of doing nothing', async () => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date('2026-11-20T03:00:00Z'));
  await renderGantt();
  await userEvent.click(tool('오늘'));
  expect(screen.getByRole('status')).toHaveTextContent('오늘(2026.11.20)은 이 일정 기간 밖입니다');
  expect(document.querySelector('[data-vline="today"]')).toBeNull();
});

test('모두 접기 · 모두 펼치기', async () => {
  await renderGantt();
  await userEvent.click(tool('모두 접기'));
  expect(leftRow('A1010')).toBeNull();
  expect(leftRow('4')).toBeInTheDocument();
  await userEvent.click(tool('모두 펼치기'));
  expect(leftRow('A4030')).toBeInTheDocument();
});

test('묶는 기준 자원 shows one lane per key resource and 자원 없음', async () => {
  await renderGantt();
  expect(tool('WBS')).toHaveAttribute('aria-pressed', 'true');
  await userEvent.click(tool('자원'));
  expect(tool('자원')).toHaveAttribute('aria-pressed', 'true');
  expect(leftRow('res:crane')).toHaveTextContent('타워크레인 (1대)');
  expect(leftRow('res:crane/A2020')).toHaveTextContent('지상 1~5층 골조');
  expect(leftRow('res:')).toHaveTextContent('자원 없음');
  expect(document.querySelector('[data-lane="res:crane"]')).toBeInTheDocument();
  await userEvent.click(within(leftRow('res:crane')!).getByRole('button', { name: '타워크레인 (1대)' }));
  expect(leftRow('res:crane/A2020')).toBeNull();
  expect(document.querySelectorAll('[data-lane="res:crane"] [data-lane-bar]')).toHaveLength(1);
});

test('열 adds a table column to the left grid', async () => {
  await renderGantt();
  await userEvent.click(tool('열'));
  await userEvent.click(within(screen.getByRole('dialog', { name: '열' })).getByLabelText('Plan 시작'));
  expect(leftHeaders()).toEqual(['WBS / ID', '이름', 'OD', 'RD', 'Plan 시작', 'TF']); // 스케줄표와 같은 칸 차례
  expect(leftRow('A3010')).toHaveTextContent('2027.07.15');
});

test('범례 explains every mark, including what the resource strip does not show yet', async () => {
  await renderGantt();
  await userEvent.click(tool('범례'));
  const legend = screen.getByRole('dialog', { name: '범례' });
  for (const t of ['크리티컬', '진도', 'Actual', '실적 없이', '마일스톤', '기한', 'Data Date', '오늘', '쉬는 날', '작업 금지', '여유 꼬리', '관계선', '미리 보기', '자원 줄'])
    expect(legend).toHaveTextContent(t);
  expect(legend).toHaveTextContent('필요량');
  expect(legend).not.toHaveTextContent('Plan 버전'); // PM 결정 11-20: 회색 Plan 버전 줄은 없앴다
});

test('되돌리기 · 다시 하기 use the same history as the table', async () => {
  await renderGantt();
  mockPatch(makeView({ version: 2 }));
  await schedule().patchActivity('A3010', { od: 40 });
  await waitFor(() => expect(tool('되돌리기')).toBeEnabled());
  mockPatch(makeView({ version: 3 }));
  await userEvent.click(tool('되돌리기'));
  await waitFor(() => expect(writes().at(-1)).toEqual(['POST', '/api/schedules/1/versions/1/restore', { base_version: 2 }]));
  await waitFor(() => expect(tool('다시 하기')).toBeEnabled());
});

async function capturedDownload(click: () => Promise<void>) {
  const blobs: Blob[] = [];
  const names: string[] = [];
  vi.spyOn(URL, 'createObjectURL').mockImplementation((b) => (blobs.push(b as Blob), 'blob:x'));
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    names.push(this.download);
  });
  await click();
  await waitFor(() => expect(names).toHaveLength(1));
  return { blob: blobs[0], name: names[0] };
}

test('CSV 내보내기 writes the left grid columns with the table safe CSV', async () => {
  await renderGantt();
  const { blob, name } = await capturedDownload(() => userEvent.click(tool('CSV 내보내기')));
  const text = await blob.text(); // text() 는 앞의 BOM 을 떼고 읽는다
  expect(name).toBe('5층 사무동 신축 v1 간트.csv');
  expect([...new Uint8Array(await blob.arrayBuffer()).slice(0, 3)]).toEqual([0xef, 0xbb, 0xbf]);
  expect(text.split('\r\n')[0]).toBe('ID,이름,OD,RD,TF');
  expect(text).toContain('A3010,외장 패널,35,,0\r\n');
});

test('그림 내보내기 falls back to an SVG file when the canvas cannot be used', async () => {
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
  await renderGantt();
  const { blob, name } = await capturedDownload(() => userEvent.click(tool('그림 내보내기')));
  expect(name).toBe('5층 사무동 신축 v1 간트.svg');
  expect(blob.type).toBe('image/svg+xml');
  const svg = await blob.text();
  expect(svg).toContain('외장 패널');
  expect(svg).toContain('data-bar="A4010"');
  expect(svg).toContain('2027년 3월');
  expect(svg).not.toContain('var(--');
});

test('during a conditions preview the CSV still exports the saved schedule', async () => {
  await renderGantt();
  const activities = makeView().activities.map((a) => (a.id === 'A3010' ? { ...a, od: 99 } : a));
  act(() => useSchedulePreview.getState().set({ scheduleId: 1, view: makeView({ activities }), moved: [], source: 'conditions' }));
  const { blob } = await capturedDownload(() => userEvent.click(tool('CSV 내보내기')));
  expect(await blob.text()).toContain('A3010,외장 패널,35,');
});

test('changing 묶는 기준 starts the new rows from the top', async () => {
  await renderGantt();
  const body = chartBody();
  body.scrollTop = 300;
  fireEvent.scroll(body);
  await userEvent.click(tool('자원'));
  expect(chartBody().scrollTop).toBe(0);
  expect(document.querySelector<HTMLElement>('.gt-left-body')!.scrollTop).toBe(0);
});
