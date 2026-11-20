import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest';
import { registerPrograms } from '../programs';
import { signInAsDemo, stubFetch } from '../test-helpers';
import { useCurrentSchedule } from './currentSchedule';
import Desktop from './Desktop';
import { useSession } from './session';
import { useShell } from './shell';
import { useWindows } from './windowStore';
import { resetShellState } from './shellReset';

const palette = () => screen.getByRole('dialog', { name: '검색' });
const box = () => within(palette()).getByRole('combobox', { name: '검색어' });
const group = (name: string) => within(palette()).getByRole('group', { name });

beforeAll(() => registerPrograms());
beforeEach(() => {
  localStorage.clear();
  signInAsDemo('admin');
  useCurrentSchedule.getState().setCurrent({ id: 4, name: '5층 사무동 신축' });
  stubFetch({
    '/api/approvals/count': { pending: 2 },
    '/api/schedules': [
      { id: 4, name: '5층 사무동 신축', level: 'L3' },
      { id: 5, name: '물류센터', level: 'L2' },
    ],
    '/api/approvals?status=pending': {
      mode: 'important',
      items: [
        { id: 11, title: '만회 계획', created_at: new Date().toISOString(), schedule_id: 4 },
        { id: 12, title: '준공 변경', created_at: new Date().toISOString(), schedule_id: 5 },
      ],
    },
    '/api/schedules/4': {
      id: 4,
      name: '5층 사무동 신축',
      activities: [
        { id: 'A1020', name: '터파기·흙막이' },
        { id: 'A1030', name: '기초 철근·타설' },
      ],
    },
  });
});
afterEach(() => {
  resetShellState();
  vi.unstubAllGlobals();
  useWindows.getState().reset();
  useShell.setState({ palette: false });
  useCurrentSchedule.getState().setCurrent(null);
  useSession.getState().logout();
});

test('Ctrl+K opens the palette; / opens it from the desktop but not while typing', async () => {
  render(<Desktop />);
  fireEvent.keyDown(document.body, { code: 'KeyK', key: 'k', ctrlKey: true });
  expect(box()).toHaveFocus();
  await userEvent.keyboard('{Escape}');
  expect(screen.queryByRole('dialog', { name: '검색' })).toBeNull();
  const input = document.createElement('input');
  document.body.append(input);
  input.focus();
  fireEvent.keyDown(input, { key: '/', code: 'Slash' });
  expect(screen.queryByRole('dialog', { name: '검색' })).toBeNull();
  input.remove();
  fireEvent.keyDown(document.body, { key: '/', code: 'Slash' });
  expect(palette()).toBeVisible();
});

test('results are grouped by kind with counts and filtered by the query', async () => {
  render(<Desktop />);
  act(() => useShell.getState().setPalette(true));
  expect(within(await within(palette()).findByRole('group', { name: '액티비티' })).getAllByRole('option')).toHaveLength(2);
  expect(within(group('프로그램')).getAllByRole('option')).toHaveLength(11);
  expect(within(group('일정')).getAllByRole('option')).toHaveLength(2);
  expect(within(group('승인 대기')).getAllByRole('option')).toHaveLength(2);
  expect(within(palette()).getByText('11')).toBeInTheDocument();
  await userEvent.type(box(), '터파기');
  expect(within(palette()).getAllByRole('group').map((g) => g.getAttribute('aria-label'))).toEqual(['액티비티']);
});

test('Enter on each kind does the right thing', async () => {
  render(<Desktop />);
  const pick = async (query: string) => {
    act(() => useShell.getState().setPalette(true));
    await within(palette()).findAllByRole('option');
    await userEvent.type(box(), query);
    await userEvent.keyboard('{Enter}');
  };
  await pick('탐색기');
  expect(useWindows.getState().activeProgramId()).toBe('explorer');
  await pick('물류');
  expect(useCurrentSchedule.getState().current).toEqual({ id: 5, name: '물류센터' });
  act(() => useCurrentSchedule.getState().setCurrent({ id: 4, name: '5층 사무동 신축' }));
  await pick('만회');
  expect(useWindows.getState().wins.find((w) => w.programId === 'approvals')?.params).toEqual({ id: '11' });
  await pick('기초');
  expect(useWindows.getState().wins.find((w) => w.programId === 'schedule-table')?.params).toEqual({ activity: 'A1030' });
});

test('arrow keys move the highlighted result', async () => {
  render(<Desktop />);
  act(() => useShell.getState().setPalette(true));
  await within(palette()).findByRole('group', { name: '액티비티' });
  const options = within(palette()).getAllByRole('option');
  expect(options[0]).toHaveAttribute('aria-selected', 'true');
  await userEvent.keyboard('{ArrowDown}{ArrowDown}');
  expect(options[2]).toHaveAttribute('aria-selected', 'true');
  await userEvent.keyboard('{ArrowUp}');
  expect(options[1]).toHaveAttribute('aria-selected', 'true');
  await userEvent.keyboard('{Enter}');
  expect(useWindows.getState().activeProgramId()).toBe('questionnaire');
});
