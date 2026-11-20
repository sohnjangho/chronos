import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test } from 'vitest';
import { json } from '../../test-helpers';
import { renderAs, resetAll, sent } from './testKit';

const ACCOUNT = { section: 'account' };
const PASSWORD = 'fake-pass-1234';
type Account = { id: number; name: string; role: string; login_id: string };

afterEach(resetAll);

test('admin lists accounts and adds one; the password field is cleared', async () => {
  let users: Account[] = [{ id: 1, name: '손장호', role: 'admin', login_id: 'jhsohn' }];
  const { fetchMock } = renderAs('admin', ACCOUNT, {
    '/api/auth/users': () => json(200, users),
    'POST /api/auth/users': (init?: RequestInit) => {
      const body = JSON.parse(String(init?.body));
      users = [...users, { id: 2, name: body.name, role: body.role, login_id: body.login_id }];
      return json(201, users[1]);
    },
  });
  const table = await screen.findByRole('table', { name: '계정' });
  expect(await within(table).findByText('jhsohn')).toBeVisible();
  await userEvent.click(screen.getByRole('button', { name: '+ 계정 추가' }));
  const form = screen.getByRole('region', { name: '계정 추가' });
  await userEvent.type(within(form).getByLabelText('아이디'), 'kim');
  await userEvent.type(within(form).getByLabelText('이름'), '김현장');
  const pw = within(form).getByLabelText('비밀번호');
  expect(pw).toHaveAttribute('type', 'password');
  expect(pw).toHaveAttribute('autocomplete', 'new-password');
  await userEvent.type(pw, PASSWORD);
  await userEvent.click(within(form).getByRole('button', { name: '만들기' }));
  expect(await within(table).findByText('kim')).toBeVisible();
  expect(screen.queryByDisplayValue(PASSWORD)).toBeNull();
  expect(sent(fetchMock, 'POST /api/auth/users')).toEqual([
    { login_id: 'kim', name: '김현장', role: 'user', password: PASSWORD },
  ]);
});

test('editing an account sends only what changed and shows the server message inline', async () => {
  const { fetchMock } = renderAs('admin', ACCOUNT, {
    'PATCH /api/auth/users/1': () => json(422, { code: 'last_admin', message: '관리자가 한 명은 있어야 합니다.', detail: null }),
  });
  await userEvent.click(await screen.findByText('jhsohn'));
  const form = screen.getByRole('region', { name: '계정 고치기' });
  expect(within(form).getByLabelText('이름')).toHaveValue('손장호');
  await userEvent.selectOptions(within(form).getByLabelText('등급'), 'user');
  await userEvent.click(within(form).getByRole('button', { name: '저장' }));
  expect(await within(form).findByText('관리자가 한 명은 있어야 합니다.')).toBeVisible();
  expect(sent(fetchMock, 'PATCH /api/auth/users/1')).toEqual([{ role: 'user' }]);
});
