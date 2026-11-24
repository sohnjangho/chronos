// 다른 화면에서 연락 시작하기(Task 104) — ContactButton: 현장 관리자에게는 없고, 알림 연결이 없으면 흐리게 「알림 연결이 없습니다」,
// 누르면 공용 BatchSendDialog(Task 103)를 연다(받는 사람·내용 확인·보내기는 그 창이 한다 — 이 단추는 보내지 않는다). 자료는 가상.
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { useSession } from '../../os/session';
import { json, signInAsDemo } from '../../test-helpers';
import ContactButton from './ContactButton';

const STATUS = { ready: true, test_mode: true, allow_count: 0, agent: { sms: 'approve', kakao: 'approve', call: 'approve' }, inbound_mode: 'off', kakao_ready: false };
const BOOK = { proposals_pending: 0, reports_open: 0, companies: [] };
let status: { status: number; body: unknown };
let calls: [string, string][];

beforeEach(() => {
  signInAsDemo('user');
  status = { status: 200, body: STATUS };
  calls = [];
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push([init?.method ?? 'GET', url]);
    if (url === '/api/notify/status') return json(status.status, status.body);
    if (url === '/api/schedules/7/contacts') return json(200, BOOK);
    if (url === '/api/notify/templates') return json(200, { ready: false, reason: '카카오톡은 아직 쓸 수 없습니다', templates: [] });
    return json(404, { code: 'not_found', message: '찾을 수 없습니다.', detail: null });
  }));
});
afterEach(() => {
  vi.unstubAllGlobals();
  useSession.getState().logout();
});

test('opens the shared batch dialog with its title, and closing gives focus back without sending anything', async () => {
  render(<ContactButton scheduleId={7} label="연락" title="연락 — A1020 현장 사무실 설치" preset={{ activityId: 'A1020' }} />);
  const button = await screen.findByRole('button', { name: '연락' });
  await waitFor(() => expect(button).toBeEnabled());
  await userEvent.click(button);
  const dialog = await screen.findByRole('dialog', { name: '연락 — A1020 현장 사무실 설치' });
  expect(dialog).toBeVisible();
  await userEvent.keyboard('{Escape}');
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  expect(button).toHaveFocus();
  expect(calls.filter(([m]) => m !== 'GET')).toEqual([]);
});

test('the field-manager role never sees the button', async () => {
  signInAsDemo('field');
  const { container } = render(<ContactButton scheduleId={7} preset={{}} />);
  await new Promise((r) => setTimeout(r, 0));
  expect(container).toBeEmptyDOMElement();
  expect(screen.queryByRole('button')).toBeNull();
  expect(calls).toEqual([]); // 알림 상태도 묻지 않는다(그 길은 현장 관리자에게 403)
});

test.each([
  ['no connection', { status: 200, body: { ...STATUS, ready: false } }],
  ['status cannot be read', { status: 500, body: { code: 'error', message: '오류', detail: null } }],
])('greys out with 「알림 연결이 없습니다」 when %s', async (_name, answer) => {
  status = answer;
  render(<ContactButton scheduleId={7} label="연락" preset={{}} />);
  const button = screen.getByRole('button', { name: '연락' });
  await waitFor(() => expect(button).toHaveAttribute('title', '알림 연결이 없습니다'));
  expect(button).toBeDisabled();
});

test('an opener reason (no row picked) greys it out with that reason', async () => {
  render(<ContactButton scheduleId={7} label="연락" preset={{}} blocked="작업 행을 먼저 고르세요" />);
  const button = screen.getByRole('button', { name: '연락' });
  await waitFor(() => expect(calls).toContainEqual(['GET', '/api/notify/status']));
  expect(button).toBeDisabled();
  expect(button).toHaveAttribute('title', '작업 행을 먼저 고르세요');
});

test('many buttons on one screen ask the notify status once', async () => {
  render(
    <>
      <ContactButton scheduleId={7} label="하나" preset={{}} />
      <ContactButton scheduleId={7} label="둘" preset={{}} />
      <ContactButton scheduleId={7} label="셋" preset={{}} />
    </>,
  );
  await waitFor(() => expect(screen.getByRole('button', { name: '셋' })).toBeEnabled());
  expect(calls.filter(([, u]) => u === '/api/notify/status')).toHaveLength(1);
});
