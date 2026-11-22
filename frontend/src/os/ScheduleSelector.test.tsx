import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';
import { json, signInAsDemo, stubFetch } from '../test-helpers';
import { useCurrentSchedule } from './currentSchedule';
import NewProjectModal from './NewProjectModal';
import ScheduleSelector from './ScheduleSelector';
import { useSession } from './session';
import { useWindows } from './windowStore';

const schedules = [
  { id: 4, name: '5층 사무동 신축', domain: 'construction', level: 'L3', version: 2, finish: null, updated_at: 'x' },
  { id: 5, name: '물류센터', domain: 'construction', level: 'L2', version: 1, finish: null, updated_at: 'x' },
];

afterEach(() => {
  useCurrentSchedule.setState({ userId: null, current: null, reloadToken: 0, newProjectModal: 'closed', creatingNewProject: false });
  useWindows.getState().reset();
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

test('direct project creation creates schedule, updates currentSchedule, and opens gantt', async () => {
  signInAsDemo('admin');
  let list: { id: number; name: string; domain: string; level: string; version: number; finish: string | null; updated_at: string }[] = [...schedules];
  stubFetch({
    '/api/schedules': () => json(200, list),
    'POST /api/schedules': () => {
      const created = { id: 9, name: '신약 임상 R&D', domain: 'rnd', level: 'L3', version: 1, finish: '2027-06-01', updated_at: 'x' };
      list = [...list, created];
      return json(201, created);
    },
  });
  render(
    <>
      <ScheduleSelector />
      <NewProjectModal />
    </>,
  );
  await userEvent.click(await screen.findByRole('button', { name: '일정 고르기' }));
  await userEvent.click(screen.getByRole('button', { name: '+ 새 프로젝트 직접 만들기' }));
  const dialog = await screen.findByRole('dialog', { name: '새 프로젝트 만들기' });
  await userEvent.type(screen.getByLabelText('프로젝트 이름'), '신약 임상 R&D');
  await userEvent.click(screen.getByRole('button', { name: '프로젝트 생성' }));
  await waitFor(() => expect(useCurrentSchedule.getState().current).toEqual({ id: 9, name: '신약 임상 R&D' }));
  expect(dialog).not.toBeInTheDocument();
  expect(useWindows.getState().wins.map((w) => w.programId)).toContain('gantt');
});
