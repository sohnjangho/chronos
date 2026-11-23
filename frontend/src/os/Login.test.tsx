import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeAll, beforeEach, expect, test, vi } from 'vitest';
import { registerPrograms } from '../programs';
import { json, stubFetch } from '../test-helpers';
import App from './App';
import Login from './Login';
import { useSession } from './session';
import { resetShellState } from './shellReset';
import { useDeviceMode } from './useIsMobile';

const mockLogin = (status: number, body: object) =>
  stubFetch({
    'POST /api/auth/login': () => json(status, body),
    '/api/approvals/count': { pending: 0 },
    '/api/schedules': [],
    '/api/chat/sessions': [],
  });

beforeAll(() => registerPrograms());

beforeEach(() => localStorage.clear());

afterEach(() => {
  localStorage.clear();
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
  expect(screen.getByText('계정은 회원가입 신청 뒤 관리자가 승인합니다. 등급은 관리자 · 사용자 · 현장 관리자 세 가지입니다.')).toBeVisible();
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

test('opens signup modal, checks password confirmation, and submits pending account request', async () => {
  let sentBody: unknown = null;
  stubFetch({
    'POST /api/auth/signup': (init?: RequestInit) => {
      sentBody = JSON.parse(String(init?.body));
      return json(201, {
        id: 10,
        login_id: 'hong1',
        name: '홍길동',
        role: 'field',
        status: 'pending',
        message: '회원가입 신청이 접수되었습니다. 관리자 승인 후 로그인할 수 있습니다.',
      });
    },
  });
  render(<Login />);
  await userEvent.click(screen.getByRole('button', { name: '회원가입' }));
  const dlg = screen.getByRole('dialog', { name: '회원가입' });
  expect(dlg).toBeVisible();

  await userEvent.type(within(dlg).getByLabelText('아이디 *'), 'hong1');
  await userEvent.type(within(dlg).getByLabelText('이름 *'), '홍길동');
  await userEvent.type(within(dlg).getByLabelText('이메일 *'), 'hong1@example.com');
  await userEvent.type(within(dlg).getByLabelText('비밀번호 *'), 'pass1234');
  await userEvent.type(within(dlg).getByLabelText('비밀번호 확인 *'), 'mismatch');
  await userEvent.click(within(dlg).getByRole('button', { name: '가입 신청하기' }));
  expect(within(dlg).getByText('비밀번호와 비밀번호 확인이 일치하지 않습니다.')).toBeVisible();

  const confirm = within(dlg).getByLabelText('비밀번호 확인 *');
  await userEvent.clear(confirm);
  await userEvent.type(confirm, 'pass1234');
  await userEvent.click(within(dlg).getByRole('button', { name: /현장 관리자/ }));
  await userEvent.click(within(dlg).getByRole('button', { name: '가입 신청하기' }));

  expect(await within(dlg).findByText('회원가입 신청이 접수되었습니다. 관리자 승인 후 로그인할 수 있습니다.')).toBeVisible();
  expect(sentBody).toEqual({
    login_id: 'hong1',
    password: 'pass1234',
    name: '홍길동',
    role: 'field',
    email: 'hong1@example.com',
  });
});

test('selected screen mode persists in localStorage and survives reload on a tablet viewport', async () => {
  vi.stubGlobal('innerWidth', 820);
  vi.stubGlobal('innerHeight', 1180);
  mockLogin(200, { token: 't', user: { id: 2, name: '김현장', role: 'user' } });
  const first = render(<App />);
  await userEvent.click(screen.getByRole('button', { name: '데스크톱' }));
  await userEvent.type(screen.getByLabelText('아이디'), 'kim');
  await userEvent.type(screen.getByLabelText('비밀번호'), 'pw');
  await userEvent.click(screen.getByRole('button', { name: '들어가기' }));
  expect(await screen.findByTestId('desktop-surface')).toBeVisible();
  first.unmount();

  useDeviceMode.getState().reset();
  useDeviceMode.getState().load(2);
  render(<App />);
  expect(screen.getByTestId('desktop-surface')).toBeVisible();
});
