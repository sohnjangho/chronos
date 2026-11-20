import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';
import { signInAsDemo, stubFetch } from '../test-helpers';
import { useCurrentSchedule } from './currentSchedule';
import ScheduleSelector from './ScheduleSelector';
import { useSession } from './session';

const schedules = [
  { id: 4, name: '5층 사무동 신축', domain: 'construction', level: 'L3', version: 2, finish: null, updated_at: 'x' },
  { id: 5, name: '물류센터', domain: 'construction', level: 'L2', version: 1, finish: null, updated_at: 'x' },
];

afterEach(() => {
  useCurrentSchedule.getState().setCurrent(null);
  useSession.getState().logout();
  vi.unstubAllGlobals();
});

test('a mouse click on a schedule picks it (the search box blur does not close the list first)', async () => {
  signInAsDemo('admin');
  stubFetch({ '/api/schedules': schedules });
  render(<ScheduleSelector />);
  await userEvent.click(await screen.findByRole('button', { name: '일정 고르기' }));
  await userEvent.click(await screen.findByRole('option', { name: '물류센터 · L2' }));
  expect(useCurrentSchedule.getState().current).toEqual({ id: 5, name: '물류센터' });
  expect(screen.queryByRole('listbox')).toBeNull();
  expect(screen.getByRole('button', { name: '물류센터 · L2' })).toHaveFocus();
});
