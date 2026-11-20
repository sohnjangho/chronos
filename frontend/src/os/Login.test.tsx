import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';
import { json, stubFetch } from '../test-helpers';
import Login from './Login';
import { useSession } from './session';

const mockLogin = (status: number, body: object) => stubFetch({ 'POST /api/auth/login': () => json(status, body) });

afterEach(() => {
  vi.unstubAllGlobals();
  useSession.getState().logout();
});

test('login failure shows the server message', async () => {
  mockLogin(401, { code: 'bad_credentials', message: '아이디 또는 비밀번호가 맞지 않습니다.', detail: null });
  render(<Login />);
  await userEvent.type(screen.getByLabelText('아이디'), 'jhsohn');
  await userEvent.type(screen.getByLabelText('비밀번호'), 'nope');
  await userEvent.click(screen.getByRole('button', { name: '들어가기' }));
  expect(await screen.findByText('아이디 또는 비밀번호가 맞지 않습니다.')).toBeVisible();
  expect(useSession.getState().session).toBeNull();
});

test('login screen follows the mockup wording', () => {
  render(<Login />);
  expect(screen.getByText('일정을 만들고, 지키고, 고치는 에이전트 OS')).toBeVisible();
  expect(screen.getByText('계정은 관리자가 만듭니다. 등급은 관리자와 사용자 두 가지입니다.')).toBeVisible();
});
