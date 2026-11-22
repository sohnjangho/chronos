import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test } from 'vitest';
import { json } from '../../test-helpers';
import { renderAs, resetAll, sent } from './testKit';

const ACCOUNT = { section: 'account' };
const PASSWORD = 'fake-pass-1234';
type Account = {
  id: number;
  name: string;
  role: string;
  login_id: string;
  status?: string;
  email?: string;
  organization?: string;
  department?: string;
  note?: string;
};

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

test('a long login id without hyphens may wrap in the edit form', async () => {
  const longId = 'a'.repeat(50);
  renderAs('admin', ACCOUNT, { '/api/auth/users': [{ id: 7, name: '긴아이디', role: 'user', login_id: longId }] });
  await userEvent.click(await screen.findByText('긴아이디'));
  const form = screen.getByRole('region', { name: '계정 고치기' });
  expect(within(form).getByText(longId)).toHaveClass('st-wrap');
});

test('admin can select field role (현장 관리자) when creating an account', async () => {
  let users: Account[] = [{ id: 1, name: '손장호', role: 'admin', login_id: 'jhsohn' }];
  const { fetchMock } = renderAs('admin', ACCOUNT, {
    '/api/auth/users': () => json(200, users),
    'POST /api/auth/users': (init?: RequestInit) => {
      const body = JSON.parse(String(init?.body));
      users = [...users, { id: 3, name: body.name, role: body.role, login_id: body.login_id }];
      return json(201, users[1]);
    },
  });
  await screen.findByRole('table', { name: '계정' });
  await userEvent.click(screen.getByRole('button', { name: '+ 계정 추가' }));
  const form = screen.getByRole('region', { name: '계정 추가' });
  await userEvent.type(within(form).getByLabelText('아이디'), 'site1');
  await userEvent.type(within(form).getByLabelText('이름'), '박현장');
  await userEvent.selectOptions(within(form).getByLabelText('등급'), 'field');
  await userEvent.type(within(form).getByLabelText('비밀번호'), PASSWORD);
  await userEvent.click(within(form).getByRole('button', { name: '만들기' }));
  expect(await within(screen.getByRole('table', { name: '계정' })).findByText('현장 관리자')).toBeVisible();
  expect(sent(fetchMock, 'POST /api/auth/users')).toEqual([
    { login_id: 'site1', name: '박현장', role: 'field', password: PASSWORD },
  ]);
});

test('admin approves a pending signup applicant and can delete a non-self user account', async () => {
  let users: Account[] = [
    { id: 1, name: '손장호', role: 'admin', login_id: 'jhsohn', status: 'active' },
    {
      id: 9,
      name: '이가입',
      role: 'user',
      login_id: 'lee_new',
      status: 'pending',
      email: 'lee@example.com',
      organization: '크로노스',
      department: '공정팀',
      note: '일정 수립 담당',
    },
  ];
  const { fetchMock } = renderAs('admin', ACCOUNT, {
    '/api/auth/users': () => json(200, users),
    'PATCH /api/auth/users/9': (init?: RequestInit) => {
      const body = JSON.parse(String(init?.body));
      users = users.map((u) => (u.id === 9 ? { ...u, ...body } : u));
      return json(200, users[1]);
    },
    'DELETE /api/auth/users/9': () => {
      users = users.filter((u) => u.id !== 9);
      return new Response(null, { status: 204 });
    },
  });

  const queue = await screen.findByRole('region', { name: '가입 승인 대기' });
  expect(within(queue).getByText('이가입 (lee_new)')).toBeVisible();
  expect(within(queue).getByText(/일정 수립 담당/)).toBeVisible();
  await userEvent.selectOptions(within(queue).getByLabelText('이가입 승인 등급'), 'field');
  await userEvent.click(within(queue).getByRole('button', { name: '승인' }));

  expect(sent(fetchMock, 'PATCH /api/auth/users/9')).toEqual([{ status: 'active', role: 'field' }]);
  expect(await within(screen.getByRole('table', { name: '계정' })).findByText('현장 관리자')).toBeVisible();
  expect(screen.queryByRole('region', { name: '가입 승인 대기' })).toBeNull();

  await userEvent.click(screen.getByText('lee_new'));
  const edit = screen.getByRole('region', { name: '계정 고치기' });
  await userEvent.click(within(edit).getByRole('button', { name: '계정 삭제' }));
  expect(sent(fetchMock, 'DELETE /api/auth/users/9')).toHaveLength(1);
});
