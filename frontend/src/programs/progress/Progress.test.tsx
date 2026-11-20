import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { useCurrentSchedule } from '../../os/currentSchedule';
import { useWindows } from '../../os/windowStore';
import { forgetSchedules } from '../../shared/schedule/scheduleStore';
import { setup } from '../../shared/schedule/testKit';
import manifest from './index';
import Progress from './Progress';

beforeEach(() => setup());
afterEach(() => {
  forgetSchedules();
  useCurrentSchedule.setState({ current: null });
  vi.unstubAllGlobals();
});

test('the manifest opens 공정률 at 1400×860 in the work group', () => {
  expect(manifest).toMatchObject({ id: 'progress', name: '공정률', kind: 'work', tone: 'rose', defaultSize: { w: 1400, h: 860 } });
});

test('without params.id it follows the OS current schedule and says it comes in the next bundle', async () => {
  useCurrentSchedule.setState({ current: { id: 1, name: '5층 사무동 신축' } });
  render(<Progress windowId="w1" />);
  expect(await screen.findByText('다음 묶음에서 만듭니다')).toBeVisible();
  await waitFor(() => expect(useWindows.getState().wins.find((w) => w.id === 'w1')?.title).toBe('공정률 — 5층 사무동 신축'));
  expect(screen.queryAllByRole('button')).toHaveLength(0);
});
