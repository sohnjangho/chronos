// R10: 200 액티비티 — 보이는 줄만 그린다(표 줄·막대 모두). 스크롤하면 그 줄이 그려진다.
import { fireEvent, waitFor } from '@testing-library/react';
import { afterEach, expect, test } from 'vitest';
import { useSchedule } from '../scheduleStore';
import { bar, bigView, chartBody, ganttGrid, leftRow, renderGantt, setupGantt } from './testKit';

afterEach(() => useSchedule.getState().reset());

test('200 activities: only the visible rows are drawn on both sides', async () => {
  setupGantt(bigView(200));
  await renderGantt();
  expect(ganttGrid()).toHaveAttribute('aria-rowcount', '210');
  expect(ganttGrid().querySelectorAll('[data-row]').length).toBeLessThan(60);
  expect(document.querySelectorAll('[data-bar]').length).toBeLessThan(60);
  expect(leftRow('1')).toBeInTheDocument();
});

test('scrolling the chart draws the rows that come into view', async () => {
  setupGantt(bigView(200));
  await renderGantt();
  expect(leftRow('10')).toBeNull();
  const body = chartBody();
  body.scrollTop = 190 * 30;
  fireEvent.scroll(body);
  expect(leftRow('10')).toBeInTheDocument();
  expect(bar('B0200')).toBeInTheDocument();
  expect(leftRow('1')).toBeNull();
});

test('params.activity opens the gantt on that row far down', async () => {
  setupGantt(bigView(200));
  await renderGantt({ id: '1', tab: 'gantt', activity: 'B0200' });
  await waitFor(() => expect(leftRow('B0200')).toHaveAttribute('aria-selected', 'true'));
  expect(bar('B0200')).toBeInTheDocument();
});

test('the wheel over the left grid scrolls the chart body', async () => {
  setupGantt(bigView(200));
  await renderGantt();
  fireEvent.wheel(document.querySelector('.gt-left-body')!, { deltaY: 300 });
  expect(chartBody().scrollTop).toBe(300);
});
