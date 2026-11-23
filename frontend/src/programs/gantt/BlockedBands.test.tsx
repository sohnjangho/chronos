// 분야 표시 설정(Task 40): 간트의 처음 묶는 기준 · 작업 금지 기간 이름표 띠 · 기한 세로선 이름. 일정은 가상이다.
import { act, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test } from 'vitest';
import { useSchedulePreview } from '../../os/schedulePreview';
import { forgetSchedules, scheduleStore } from '../../shared/schedule/scheduleStore';
import type { ScheduleView } from '../../shared/schedule/scheduleApi';
import { makeView, num, pxPerDay, renderGantt, setupGantt, tool, type TestCond } from './testKit';

const PRESS = { tag: '프레스', start: '2027-07-20', finish: '2027-08-10' };
const DUE: TestCond = { id: 'in.finish_by', kind: 'finish_by', params: { date: '2027-09-10' }, text: '납기 9월 10일' };

/** 생산 분야처럼 보이는 가상 일정: A3010 이 프레스 공정, 자원 묶음·납기 이름. */
function factoryView(over: Partial<ScheduleView> = {}): ScheduleView {
  const base = makeView();
  return makeView({
    domain: 'manufacturing',
    display: { gantt_group_by: 'resource', deadline_label: '납기', extra_columns: ['resources'] },
    calendar: { days_per_week: 5, blocked: [PRESS] },
    activities: base.activities.map((a) => (a.id === 'A3010' ? { ...a, tags: ['프레스'] } : a)),
    ...over,
  });
}

beforeEach(() => setupGantt(factoryView(), [DUE]));
afterEach(() => {
  forgetSchedules();
  useSchedulePreview.getState().reset();
});

test('blocked bands are labeled', async () => {
  await renderGantt();
  expect(screen.getByText('프레스 작업 금지')).toBeVisible();
  const band = document.querySelectorAll('[data-blocked="프레스"]');
  expect(band).toHaveLength(1); // 한 번만 그린다(예전 음영과 겹치지 않음)
  expect(band[0].querySelector('title')).toHaveTextContent('작업 금지(프레스) 2027.07.20~2027.08.10');
  expect(num(band[0], 'width')).toBeCloseTo(22 * pxPerDay(), 1);
  expect(band[0].getAttribute('fill')).toMatch(/^url\(#/); // 빗금
});

test('the band is darker on the rows of activities with that tag', async () => {
  await renderGantt();
  await userEvent.click(tool('WBS'));
  const rows = [...document.querySelectorAll('[data-blocked-row]')].map((r) => r.getAttribute('data-blocked-row'));
  expect(rows).toEqual(['A3010']);
});

test('gantt starts grouped as the domain says', async () => {
  await renderGantt();
  expect(screen.getByRole('button', { name: '자원', pressed: true })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'WBS', pressed: false })).toBeInTheDocument();
});

test('a group-by the user picks stays when the schedule is re-read', async () => {
  await renderGantt();
  await userEvent.click(tool('WBS'));
  act(() => scheduleStore(1).setState({ view: factoryView({ version: 2, name: '다시 읽은 일정' }) }));
  expect(screen.getByRole('button', { name: 'WBS', pressed: true })).toBeInTheDocument();
});

test('without domain display the gantt starts by WBS', async () => {
  setupGantt(makeView());
  await renderGantt();
  expect(screen.getByRole('button', { name: 'WBS', pressed: true })).toBeInTheDocument();
});

test('deadline label follows the domain', async () => {
  await renderGantt();
  expect(await screen.findByText(/납기 09\.10/, { selector: '.gantt-mark' })).toBeVisible(); // 머리 이름표(세로선 요약 글 말고)
  expect(screen.queryByText(/기한 09\.10/)).toBeNull();
});

test('the legend names the deadline line the way the domain does', async () => {
  await renderGantt();
  await userEvent.click(tool('범례'));
  expect(screen.getByRole('dialog', { name: '범례' })).toHaveTextContent('납기 빨간 점선(finish_by 조건)');
});
