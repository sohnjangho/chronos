// 사람 양식의 음성 「직접 지정」(Task 99). 음성 SDK 가 음성 목록을 주지 않아(진단 P9) 목록 대신 음성 id 를 손으로 넣는다.
// 꼴은 서버(Task 72 check_voice)와 같다: 영문·숫자·. _ : - 로 64자까지.
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { useCurrentSchedule } from '../../os/currentSchedule';
import { useUiContext } from '../../os/uiContext';
import { useWindows } from '../../os/windowStore';
import Contacts from './Contacts';
import { detail, lastWrite, mockDetail, mockWrite, PARK, stubContacts, writes } from './testKit';

const SHAPE = '음성 id 는 영문·숫자와 . _ : - 로 64자까지입니다.';

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

async function addForm() {
  render(<Contacts windowId="w1" params={{}} />);
  await screen.findByText('박현장');
  await userEvent.click(screen.getByRole('button', { name: '+ 사람 추가' }));
  return screen.findByRole('form', { name: '사람 추가' });
}

async function editForm() {
  render(<Contacts windowId="w1" params={{}} />);
  await userEvent.click(await screen.findByRole('button', { name: /박현장/ }));
  await userEvent.click(screen.getByRole('button', { name: '고치기' }));
  return screen.findByRole('form', { name: '사람 고치기' });
}

test('직접 지정 opens a manual voice id field (no list) and a new person posts voice_mode manual with the id', async () => {
  const f = await addForm();
  const voice = within(f).getByRole('group', { name: '음성' });
  expect(within(voice).queryByLabelText('음성 id')).toBeNull(); // 자동이면 칸이 없다
  await userEvent.click(within(voice).getByRole('radio', { name: '직접 지정' }));
  const id = within(voice).getByLabelText('음성 id');
  expect(id.tagName).toBe('INPUT');
  expect(within(voice).getByText(/음성 SDK 가 음성 목록을 주지 않아/)).toBeVisible();
  expect(within(voice).queryByRole('listbox')).toBeNull();
  await userEvent.type(within(f).getByLabelText('이름'), '오배관');
  await userEvent.type(id, 'Fenrir');
  await userEvent.click(within(f).getByRole('button', { name: '저장' }));
  await waitFor(() => expect(lastWrite()?.method).toBe('POST'));
  expect(lastWrite()?.body).toMatchObject({ name: '오배관', voice_mode: 'manual', voice_id: 'Fenrir' });
});

test('manual without an id or with a wrong shape is caught before sending', async () => {
  const f = await addForm();
  await userEvent.type(within(f).getByLabelText('이름'), '오배관');
  const voice = within(f).getByRole('group', { name: '음성' });
  await userEvent.click(within(voice).getByRole('radio', { name: '직접 지정' }));
  await userEvent.click(within(f).getByRole('button', { name: '저장' }));
  expect(within(voice).getByText('음성을 직접 지정하려면 음성 id 를 넣어 주세요.')).toBeVisible();
  await userEvent.type(within(voice).getByLabelText('음성 id'), '목소리 하나');
  await userEvent.click(within(f).getByRole('button', { name: '저장' }));
  expect(within(voice).getByText(SHAPE)).toBeVisible();
  expect(writes()).toEqual([]);
});

test('a person with a manual voice shows the id; changing it sends only voice_id, going back to 자동 sends only the mode', async () => {
  mockDetail(detail(PARK, { voice_mode: 'manual', voice_id: 'ko-voice-7' }));
  mockWrite(200, detail(PARK, { voice_mode: 'manual', voice_id: 'Leda' }));
  let f = await editForm();
  let voice = within(f).getByRole('group', { name: '음성' });
  expect(within(voice).getByRole('radio', { name: '직접 지정' })).toBeChecked();
  const id = within(voice).getByLabelText('음성 id');
  expect(id).toHaveValue('ko-voice-7');
  await userEvent.clear(id);
  await userEvent.type(id, 'Leda');
  await userEvent.click(within(f).getByRole('button', { name: '저장' }));
  await waitFor(() => expect(lastWrite()?.method).toBe('PATCH'));
  expect(lastWrite()?.body).toEqual({ voice_id: 'Leda' });
  cleanup();
  mockWrite(200, detail(PARK));
  f = await editForm();
  voice = within(f).getByRole('group', { name: '음성' });
  await userEvent.click(within(voice).getByRole('radio', { name: '자동' }));
  expect(within(voice).queryByLabelText('음성 id')).toBeNull();
  await userEvent.click(within(f).getByRole('button', { name: '저장' }));
  await waitFor(() => expect(writes()).toHaveLength(2));
  expect(lastWrite()?.body).toEqual({ voice_mode: 'auto' });
});
