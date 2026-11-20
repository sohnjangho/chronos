import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { useWindows } from '../../os/windowStore';
import { forgetSchedules } from '../../shared/schedule/scheduleStore';
import { setup } from '../../shared/schedule/testKit';
import Cpm from './Cpm';
import manifest from './index';

beforeEach(() => setup());
afterEach(() => {
  forgetSchedules();
  vi.unstubAllGlobals();
});

test('the manifest opens CPM at 1600×900 in the work group', () => {
  expect(manifest).toMatchObject({ id: 'cpm', name: 'CPM', kind: 'work', tone: 'fuchsia', defaultSize: { w: 1600, h: 900 } });
});

test('until the next bundle the window says so, names the schedule and has no dead buttons', async () => {
  render(<Cpm windowId="w1" params={{ id: '1' }} />);
  expect(await screen.findByText('다음 묶음에서 만듭니다')).toBeVisible();
  await waitFor(() => expect(useWindows.getState().wins.find((w) => w.id === 'w1')?.title).toBe('CPM — 5층 사무동 신축'));
  expect(screen.getByRole('group', { name: '일정 요약' })).toBeVisible();
  expect(screen.queryAllByRole('button')).toHaveLength(0);
});
