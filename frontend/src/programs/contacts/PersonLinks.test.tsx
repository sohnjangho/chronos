// 관리자 등급·참여 프로젝트(11-24 PM). 관리자 등급은 관리자만 바꾸고 올릴 때 확인을 묻는다. 참여 프로젝트는 프로젝트마다 체크 —
// 켜면 그 프로젝트의 협력사를 골라 [등록], 끄면 그 프로젝트의 연락처를 숨긴다. 같은 번호가 그곳에 있으면 「같은 사람으로 연결」.
// 사람·회사·번호는 모두 가상이다.
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { useCurrentSchedule } from '../../os/currentSchedule';
import { useUiContext } from '../../os/uiContext';
import { useWindows } from '../../os/windowStore';
import Contacts from './Contacts';
import { levelConfirm } from './PersonLinks';
import ThreadHeader from './ThreadHeader';
import {
  BOOK, detail, EMPTY, lastWrite, mockBook, mockDetail, mockOtherBook, mockProjects, mockWrite, PARK, PROJECTS, stubContacts, writes,
} from './testKit';

beforeEach(() => {
  stubContacts();
  useWindows.setState({ open: vi.fn(), setTitle: vi.fn() } as never);
  useCurrentSchedule.setState({ current: { id: 1, name: '5층 사무동 신축' } });
});
afterEach(() => {
  cleanup();
  useCurrentSchedule.setState({ current: null });
  useUiContext.getState().reset();
  vi.unstubAllGlobals();
});

async function editForm() {
  render(<Contacts windowId="w1" params={{}} />);
  await userEvent.click(await screen.findByRole('button', { name: /박현장/ }));
  await userEvent.click(screen.getByRole('button', { name: '고치기' }));
  return screen.findByRole('form', { name: '사람 고치기' });
}

const OTHER = { ...EMPTY, companies: [{ id: 210, name: '나래설비', trade: '설비', note: '', hidden: false, people: [] }] };
const LINKED = detail(PARK, {
  projects: 2,
  project_links: [
    { schedule_id: 1, name: '5층 사무동 신축', contact_id: 1, company_id: 10, company_name: '대한골조', current: true },
    { schedule_id: 2, name: '물류센터 증축', contact_id: 31, company_id: 210, company_name: '나래설비', current: false },
  ],
});

test('admin raises the level: a confirm with the exact words, then PATCH access_level manager', async () => {
  mockWrite(200, detail(PARK, { access_level: 'manager' }));
  const f = await editForm();
  const level = within(f).getByRole('group', { name: '관리자 등급' });
  expect(within(level).getByRole('radio', { name: '협력사 담당' })).toBeChecked();
  await userEvent.click(within(level).getByRole('radio', { name: '관리자 등급' }));
  expect(within(level).getByText(/등록된 프로젝트의 모든 협력사 일정/)).toBeVisible();
  await userEvent.click(within(f).getByRole('button', { name: '저장' }));

  const box = await within(f).findByRole('alertdialog', { name: '관리자 등급' });
  const words = '관리자 등급은 이 사람이 등록된 프로젝트의 모든 협력사 일정을 전화·문자로 들을 수 있게 합니다. 참여 프로젝트 1곳 모두에 적용됩니다. 계속할까요?';
  expect(within(box).getByText(words)).toBeVisible();
  expect(levelConfirm(1)).toBe(words);
  expect(writes()).toEqual([]);
  await userEvent.click(within(box).getByRole('button', { name: '계속' }));
  await waitFor(() => expect(lastWrite()?.method).toBe('PATCH'));
  expect(lastWrite()?.body).toEqual({ access_level: 'manager' });
});

test('the level confirm names how many projects it applies to', async () => {
  mockDetail(LINKED);
  mockProjects([PROJECTS[0], { ...PROJECTS[1], linked: true, contact_id: 31, company_id: 210, company_name: '나래설비' }]);
  const f = await editForm();
  await userEvent.click(within(f).getByRole('radio', { name: '관리자 등급' }));
  await userEvent.click(within(f).getByRole('button', { name: '저장' }));
  const box = await within(f).findByRole('alertdialog', { name: '관리자 등급' });
  expect(within(box).getByText(/참여 프로젝트 2곳 모두에 적용됩니다/)).toBeVisible();
  await userEvent.click(within(box).getByRole('button', { name: '취소' }));
  expect(writes()).toEqual([]);
});

test('cancelling the level confirm sends nothing; lowering the level needs no confirm', async () => {
  mockDetail(detail(PARK, { access_level: 'manager' }));
  mockWrite(200, detail(PARK));
  const f = await editForm();
  const level = within(f).getByRole('group', { name: '관리자 등급' });
  expect(within(level).getByRole('radio', { name: '관리자 등급' })).toBeChecked();
  await userEvent.click(within(level).getByRole('radio', { name: '협력사 담당' }));
  await userEvent.click(within(f).getByRole('button', { name: '저장' }));
  await waitFor(() => expect(lastWrite()?.body).toEqual({ access_level: 'trade' }));
  expect(within(f).queryByRole('alertdialog')).toBeNull();
});

test('a non-admin sees the level locked', async () => {
  cleanup();
  stubContacts('user');
  const f = await editForm();
  const level = within(f).getByRole('group', { name: '관리자 등급' });
  for (const radio of within(level).getAllByRole('radio')) expect(radio).toBeDisabled();
  expect(within(level).getByText('관리자 등급은 관리자만 바꿀 수 있습니다.')).toBeVisible();
});

test('참여 프로젝트: checking another project picks its company and registers the person there', async () => {
  mockOtherBook(OTHER);
  mockWrite(201, LINKED);
  const f = await editForm();
  const box = within(f).getByRole('group', { name: /참여 프로젝트/ });
  const here = await within(box).findByRole('checkbox', { name: /5층 사무동 신축/ });
  expect(here).toBeChecked();
  expect(here).toBeDisabled();
  await userEvent.click(within(box).getByRole('checkbox', { name: /물류센터 증축/ }));
  const company = await within(box).findByRole('combobox', { name: '그 프로젝트의 협력사' });
  expect([...(company as HTMLSelectElement).options].map((o) => o.textContent)).toEqual(['나래설비', '+ 새 협력사']);
  expect(writes()).toEqual([]);
  mockProjects([PROJECTS[0], { ...PROJECTS[1], linked: true, contact_id: 31, company_id: 210, company_name: '나래설비' }]);
  await userEvent.click(within(box).getByRole('button', { name: '등록' }));

  await waitFor(() => expect(lastWrite()?.url).toBe('/api/schedules/1/contacts/people/1/projects'));
  expect(lastWrite()?.body).toEqual({ schedule_id: 2, company_id: 210 });
  expect(await within(box).findByText('나래설비')).toBeVisible();
  expect(within(f).getByText(/참여 프로젝트 2곳 모두에 저장됩니다/)).toBeVisible();
});

test('a new company there is created first; the same number there offers 「같은 사람으로 연결」', async () => {
  const f = await editForm();
  const box = within(f).getByRole('group', { name: /참여 프로젝트/ });
  await userEvent.click(await within(box).findByRole('checkbox', { name: /물류센터 증축/ }));
  expect(await within(box).findByRole('combobox', { name: '그 프로젝트의 협력사' })).toHaveValue('new');
  await userEvent.click(within(box).getByRole('button', { name: '등록' }));
  expect(within(box).getByText('새 협력사 이름을 넣어 주세요.')).toBeVisible();
  await userEvent.type(within(box).getByLabelText('새 협력사 이름'), '나래골조');
  mockWrite(201, { id: 220, name: '나래골조', trade: '', note: '', hidden: false });
  mockWrite(409, { code: 'same_number_there', message: '그 프로젝트에 같은 번호의 연락처가 이미 있습니다. 같은 사람으로 연결할 수 있습니다.', detail: { contact_id: 44 } });
  await userEvent.click(within(box).getByRole('button', { name: '등록' }));

  expect(await within(box).findByText(/같은 번호의 연락처가 이미 있습니다/)).toBeVisible();
  expect(writes().map((w) => [w.url, w.body])).toEqual([
    ['/api/schedules/2/contacts/companies', { name: '나래골조' }],
    ['/api/schedules/1/contacts/people/1/projects', { schedule_id: 2, company_id: 220 }],
  ]);
  mockWrite(201, LINKED);
  await userEvent.click(within(box).getByRole('button', { name: '같은 사람으로 연결' }));
  await waitFor(() => expect(lastWrite()?.body).toEqual({ schedule_id: 2, link_contact_id: 44 }));
  expect(JSON.stringify(writes())).not.toMatch(/010-?0000/);
});

test('unchecking a linked project removes it (DELETE — the row is hidden there, not deleted)', async () => {
  mockDetail(LINKED);
  mockProjects([PROJECTS[0], { ...PROJECTS[1], linked: true, contact_id: 31, company_id: 210, company_name: '나래설비' }]);
  mockWrite(200, detail(PARK));
  const f = await editForm();
  const box = within(f).getByRole('group', { name: /참여 프로젝트/ });
  expect(within(f).getByText(/참여 프로젝트 2곳 모두에 저장됩니다/)).toBeVisible();
  mockProjects(PROJECTS);
  await userEvent.click(await within(box).findByRole('checkbox', { name: /물류센터 증축/ }));
  await waitFor(() => expect(lastWrite()?.method).toBe('DELETE'));
  expect(lastWrite()?.url).toBe('/api/schedules/1/contacts/people/1/projects/2');
  expect(within(box).getByText(/빼면 그 프로젝트의 연락처를 숨깁니다/)).toBeVisible();
});

test('a new person: 참여 프로젝트 comes after saving', async () => {
  render(<Contacts windowId="w1" params={{}} />);
  await screen.findByText('박현장');
  await userEvent.click(screen.getByRole('button', { name: '+ 사람 추가' }));
  const f = await screen.findByRole('form', { name: '사람 추가' });
  expect(within(f).getByText('저장한 뒤 다른 프로젝트에도 같은 사람으로 등록할 수 있습니다.')).toBeVisible();
  expect(within(f).queryByRole('checkbox', { name: /물류센터/ })).toBeNull();
});

test('the list shows 「프로젝트 n」 and 「관리자 등급」 chips; the header lists the projects', async () => {
  const park = { ...PARK, projects: 2, access_level: 'manager' as const };
  mockBook({ ...BOOK, companies: [{ ...BOOK.companies[0], people: [park, BOOK.companies[0].people[1]] }, ...BOOK.companies.slice(1)] });
  render(<Contacts windowId="w1" params={{}} />);
  const row = await screen.findByRole('button', { name: /박현장/ });
  expect(within(row).getByText('프로젝트 2')).toBeVisible();
  expect(within(row).getByText('관리자 등급')).toBeVisible();
  expect(within(screen.getByRole('button', { name: /최반장/ })).queryByText(/프로젝트 \d/)).toBeNull();
  cleanup();

  mockDetail(LINKED);
  render(<ThreadHeader scheduleId={1} person={PARK} />);
  expect(await screen.findByText('참여 프로젝트: 5층 사무동 신축 · 물류센터 증축')).toBeVisible();
});
