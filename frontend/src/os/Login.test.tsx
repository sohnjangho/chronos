import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeAll, expect, test, vi } from 'vitest';
import { registerPrograms } from '../programs';
import { json, stubFetch } from '../test-helpers';
import App from './App';
import Login from './Login';
import { useSession } from './session';
import { resetShellState } from './shellReset';

const mockLogin = (status: number, body: object) =>
  stubFetch({
    'POST /api/auth/login': () => json(status, body),
    '/api/approvals/count': { pending: 0 },
    '/api/schedules': [],
    '/api/chat/sessions': [],
  });

beforeAll(() => registerPrograms());

afterEach(() => {
  resetShellState();
  vi.unstubAllGlobals();
  useSession.getState().logout();
});

test('login failure shows the server message', async () => {
  mockLogin(401, { code: 'bad_credentials', message: '아이디 또는 비밀번호가 맞지 않습니다.', detail: null });
  render(<Login />);
  await userEvent.type(screen.getByLabelText('아이디'), 'demo-admin');
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

test('login screen lets a tablet user choose 데스크톱 or 태블릿 and preserves the choice after sign-in', async () => {
  vi.stubGlobal('innerWidth', 820);
  vi.stubGlobal('innerHeight', 1180);
  mockLogin(200, { token: 't', user: { id: 2, name: '김현장', role: 'user' } });
  render(<App />);
  expect(screen.getByText('자동 감지: 태블릿')).toBeVisible();
  await userEvent.click(screen.getByRole('button', { name: '데스크톱' }));
  await userEvent.type(screen.getByLabelText('아이디'), 'kim');
  await userEvent.type(screen.getByLabelText('비밀번호'), 'pw');
  await userEvent.click(screen.getByRole('button', { name: '들어가기' }));
  expect(await screen.findByTestId('desktop-surface')).toBeVisible();
});

test('tablet viewport logs directly into TabletShell when mode is 자동', async () => {
  vi.stubGlobal('innerWidth', 820);
  vi.stubGlobal('innerHeight', 1180);
  mockLogin(200, { token: 't', user: { id: 2, name: '김현장', role: 'user' } });
  render(<App />);
  await userEvent.type(screen.getByLabelText('아이디'), 'kim');
  await userEvent.type(screen.getByLabelText('비밀번호'), 'pw');
  await userEvent.click(screen.getByRole('button', { name: '들어가기' }));
  expect(await screen.findByTestId('tablet-shell')).toBeVisible();
});
