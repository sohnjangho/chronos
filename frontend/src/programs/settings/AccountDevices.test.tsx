// 설정 → 계정(관리자): 계정마다 접속 상태(초록 점 「접속 중」 / 「마지막 접속 …」), 기기 목록(종류 · 브라우저 · OS),
// 기기마다 [이 기기 로그아웃] — 확인을 한 번 더 묻고 POST /api/admin/devices/{id}/logout. 계정이 6개를 넘으면 찾기 칸.
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { json } from '../../test-helpers';
import { lastSeenText } from './AccountDevices';
import { renderAs, resetAll, sent } from './testKit';

const ACCOUNT = { section: 'account' };
const NOW = new Date(2026, 10, 24, 15, 0); // 이 시험이 도는 곳의 시간대로 2026-11-24 15:00
const at = (d: number, h: number, m: number) => new Date(2026, 10, d, h, m).toISOString();

const USERS = [
  { id: 1, name: '김하늘', role: 'admin', login_id: 'demo-admin' },
  { id: 2, name: '박현장', role: 'field', login_id: 'site1' },
  { id: 3, name: '이바다', role: 'user', login_id: 'user3' },
];
const device = (over: Record<string, unknown>) => ({
  id: 10, kind: 'desktop', browser: 'Chrome', os: 'macOS', online: false, revoked: false, current: false,
  created_at: at(20, 9, 0), last_seen_at: at(24, 14, 12), revoked_at: null, ...over,
});
const DEVICES = [
  {
    user_id: 1, online: true, last_seen_at: at(24, 14, 59),
    devices: [device({ id: 11, online: true, current: true, last_seen_at: at(24, 14, 59) })],
  },
  {
    user_id: 2, online: false, last_seen_at: at(24, 14, 12),
    devices: [
      device({ id: 21, kind: 'phone', browser: 'Safari', os: 'iOS' }),
      device({ id: 22, kind: 'tablet', browser: 'Chrome', os: 'Android', last_seen_at: at(23, 8, 5) }),
    ],
  },
];

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(NOW);
});
afterEach(() => {
  vi.useRealTimers();
  resetAll();
});

const show = (over = {}) =>
  renderAs('admin', ACCOUNT, { '/api/auth/users': USERS, '/api/admin/accounts/devices': DEVICES, ...over });

test('last seen reads 오늘 / 어제 / a date', () => {
  expect(lastSeenText(at(24, 14, 12), NOW)).toBe('오늘 14:12');
  expect(lastSeenText(at(23, 8, 5), NOW)).toBe('어제 08:05');
  expect(lastSeenText(at(2, 7, 30), NOW)).toBe('11월 2일 07:30');
  expect(lastSeenText(new Date(2025, 11, 31, 23, 0).toISOString(), NOW)).toBe('2025년 12월 31일 23:00');
});

test('each account row shows whether it is online now or when it was last seen', async () => {
  show();
  const table = await screen.findByRole('table', { name: '계정' });
  const row = (login: string) => within(table).getByText(login).closest('tr')!;
  expect(await within(row('demo-admin')).findByText('접속 중')).toBeVisible();
  expect(row('demo-admin').querySelector('.st-dot-on')).not.toBeNull();
  expect(within(row('site1')).getByText('마지막 접속 오늘 14:12')).toBeVisible();
  expect(within(row('user3')).getByText('접속 기록 없음')).toBeVisible();
});

test('the device list is grouped by account and lists kind · browser · OS per device', async () => {
  show();
  const box = await screen.findByRole('region', { name: '접속 기기' });
  const group = await within(box).findByRole('group', { name: '박현장 (site1)' });
  expect(within(group).getByText('기기 2대')).toBeVisible();
  await userEvent.click(within(group).getByText('박현장 (site1)'));
  const items = within(group).getAllByRole('listitem');
  expect(items.map((li) => within(li).getByText(/ · /).textContent)).toEqual(['휴대폰 · Safari · iOS', '태블릿 · Chrome · Android']);
  expect(within(items[1]).getByText('마지막 접속 어제 08:05')).toBeVisible();
  expect(within(box).queryByRole('group', { name: '이바다 (user3)' })).toBeNull(); // 기기 없는 계정은 묶음 없음
  expect(within(box).queryByRole('searchbox')).toBeNull(); // 계정 6개 이하
});

test('logging out a device asks once more, sends it and shows the device as logged out', async () => {
  let list = DEVICES;
  const { fetchMock } = show({
    '/api/admin/accounts/devices': () => json(200, list),
    'POST /api/admin/devices/21/logout': () => {
      list = [DEVICES[0], { ...DEVICES[1], devices: [device({ id: 21, kind: 'phone', browser: 'Safari', os: 'iOS', revoked: true, revoked_at: at(24, 15, 0) }), DEVICES[1].devices[1]] }];
      return json(200, list[1].devices[0]);
    },
  });
  const group = await screen.findByRole('group', { name: '박현장 (site1)' });
  await userEvent.click(within(group).getByText('박현장 (site1)'));
  const phone = within(group).getAllByRole('listitem')[0];
  await userEvent.click(within(phone).getByRole('button', { name: '이 기기 로그아웃' }));
  expect(within(phone).getByText('이 기기에서 로그아웃할까요? 그 기기는 다음 동작 때 로그인 화면으로 갑니다')).toBeVisible();
  await userEvent.click(within(phone).getByRole('button', { name: '취소' }));
  expect(sent(fetchMock, 'POST /api/admin/devices/21/logout')).toEqual([]);
  await userEvent.click(within(phone).getByRole('button', { name: '이 기기 로그아웃' }));
  await userEvent.click(within(phone).getByRole('button', { name: '로그아웃' }));
  expect(await within(group).findByText('로그아웃됨')).toBeVisible();
  expect(sent(fetchMock, 'POST /api/admin/devices/21/logout')).toEqual([{}]);
  expect(within(group).getAllByRole('button', { name: '이 기기 로그아웃' })).toHaveLength(1);
});

test('your own current device is marked and its logout warns and sends the confirmation', async () => {
  const { fetchMock } = show({ 'POST /api/admin/devices/11/logout': () => json(200, device({ id: 11, revoked: true })) });
  const group = await screen.findByRole('group', { name: '김하늘 (demo-admin)' });
  await userEvent.click(within(group).getByText('김하늘 (demo-admin)'));
  const mine = within(group).getAllByRole('listitem')[0];
  expect(within(mine).getByText('지금 이 기기')).toBeVisible();
  await userEvent.click(within(mine).getByRole('button', { name: '이 기기 로그아웃' }));
  expect(within(mine).getByText(/지금 쓰고 있는 이 기기입니다/)).toBeVisible();
  await userEvent.click(within(mine).getByRole('button', { name: '로그아웃' }));
  await vi.waitFor(() => expect(sent(fetchMock, 'POST /api/admin/devices/11/logout')).toEqual([{ confirm_self: true }]));
});

test('a failed logout shows the server message in that device line', async () => {
  show({
    'POST /api/admin/devices/21/logout': () => json(404, { code: 'device_not_found', message: '기기를 찾을 수 없습니다.', detail: null }),
  });
  const group = await screen.findByRole('group', { name: '박현장 (site1)' });
  await userEvent.click(within(group).getByText('박현장 (site1)'));
  const phone = within(group).getAllByRole('listitem')[0];
  await userEvent.click(within(phone).getByRole('button', { name: '이 기기 로그아웃' }));
  await userEvent.click(within(phone).getByRole('button', { name: '로그아웃' }));
  expect(await within(phone).findByText('기기를 찾을 수 없습니다.')).toBeVisible();
});

test('more than six accounts get a search box that filters the device groups', async () => {
  const many = Array.from({ length: 8 }, (_, i) => ({ id: i + 1, name: `사람${i + 1}`, role: 'user', login_id: `p${i + 1}` }));
  const groups = many.map((u) => ({ user_id: u.id, online: false, last_seen_at: at(24, 9, 0), devices: [device({ id: 100 + u.id })] }));
  show({ '/api/auth/users': many, '/api/admin/accounts/devices': groups });
  const box = await screen.findByRole('region', { name: '접속 기기' });
  expect(await within(box).findAllByRole('group')).toHaveLength(8);
  await userEvent.type(within(box).getByRole('searchbox', { name: '계정 찾기' }), 'p7');
  expect(within(box).getAllByRole('group').map((g) => g.getAttribute('aria-label'))).toEqual(['사람7 (p7)']);
  await userEvent.clear(within(box).getByRole('searchbox', { name: '계정 찾기' }));
  await userEvent.type(within(box).getByRole('searchbox', { name: '계정 찾기' }), '없는사람');
  expect(within(box).getByText('찾는 계정이 없습니다.')).toBeVisible();
});

test('the account screen still works when the device list cannot be read', async () => {
  show({ '/api/admin/accounts/devices': () => json(500, { code: 'boom', message: '접속 상태를 읽을 수 없습니다.', detail: null }) });
  const table = await screen.findByRole('table', { name: '계정' });
  expect(await within(table).findByText('site1')).toBeVisible();
  expect(await screen.findByText('접속 상태를 읽을 수 없습니다.')).toBeVisible();
});
