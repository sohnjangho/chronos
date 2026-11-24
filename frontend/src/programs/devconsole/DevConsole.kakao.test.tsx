// 개발 콘솔 ④(Task 111): 카카오톡 — 시스템 진단의 저장된 채널·문안 상태 · 사용량의 알림톡 건수와 문자로 대신 나간 수.
// 콘솔은 제공사를 부르지 않는다(저장된 값만 보인다).
import { render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import DevConsole from './DevConsole';
import { kakaoHealth, mockHealth, mockUsage, notifyHealth, setup, urls } from './testKit';

const show = (tab: string) => render(<DevConsole windowId="w1" params={{ tab }} />);

beforeEach(() => {
  localStorage.clear();
  setup();
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe('시스템 진단 — 카카오톡', () => {
  test('shows the stored channel and template counts without calling anything', async () => {
    mockHealth({ notify: notifyHealth({ kakao: kakaoHealth() }) });
    show('health');
    const card = await screen.findByRole('article', { name: '카카오톡' });
    expect(card).toHaveTextContent('한빛 현장 채널');
    expect(card).toHaveTextContent('준비 안 됨');
    expect(within(card).getByText('문안 승인').nextElementSibling).toHaveTextContent('2개');
    expect(within(card).getByText('문안 검수 중').nextElementSibling).toHaveTextContent('1개');
    expect(within(card).getByText('문안 반려').nextElementSibling).toHaveTextContent('1개');
    expect(within(card).getByText('문안 휴면').nextElementSibling).toHaveTextContent('3개');
    expect(within(screen.getByRole('article', { name: '알림 연결' })).getByText('아래 「카카오톡」 칸')).toBeVisible();
    expect(urls().some((u) => u.includes('kakao') || u.includes('/notify'))).toBe(false);
  });

  test('says there is no channel and that kakao is not used', async () => {
    mockHealth({ notify: notifyHealth({ kakao: kakaoHealth({ channel: null, templates: { approved: 0, reviewing: 0, rejected: 0, dormant: 0 }, synced_at: null }) }) });
    show('health');
    const card = await screen.findByRole('article', { name: '카카오톡' });
    expect(card).toHaveTextContent('카카오톡: 연결된 채널 없음 — 쓰지 않음');
    expect(within(card).queryByText('문안 승인')).toBeNull();
  });
});

describe('사용량 — 카카오톡', () => {
  test('kakao count and the number sent as SMS instead', async () => {
    mockUsage({ outreach: { sms: 4, long: 0, kakao: 0, auto_replies: 0, provider_cost: null, fallback_sms: 3, kakao_not_ready: 2, text_models: [] } });
    show('usage');
    const table = await screen.findByRole('table', { name: '연락 사용량' });
    expect(within(table).getByRole('row', { name: /^카카오톡\(알림톡\)/ })).toHaveTextContent('아직 쓰지 않습니다');
    const instead = within(table).getByRole('row', { name: /^문자로 대신 나간 수/ });
    expect(within(instead).getAllByRole('cell')[0]).toHaveTextContent('3');
    expect(instead).toHaveTextContent('「준비 안 됨」 사건 2건');
  });
});
