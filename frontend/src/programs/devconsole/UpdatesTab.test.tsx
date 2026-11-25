// 업데이트 내역(시안 U1): 판마다 카드(때 · 이름 · 커밋 · 「지금 실서버 판」 · 알림 띠 · 새 기능/고침/안전), 날짜 묶음, 갈래 칩 · 찾기.
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import DevConsole from './DevConsole';
import { mockUpdates, setup } from './testKit';

const item = (text: string, note: string | null = null) => ({ text, note });
const ENTRIES = [
  {
    at: '2026-11-24T14:12:00+09:00', commit: 'c5f1c23', title: '기기 이어 쓰기 · 프로젝트 관리', notice: '이 판부터 모두 한 번 다시 로그인해야 합니다.',
    added: [item('창·탭 자리를 기억합니다'), item('새 아이콘 20종')], fixed: [item('받아쓰기를 한국어로 고정', '음성 진단도 같은 설정')], safety: [item('잃어버린 기기만 로그아웃')],
  },
  { at: '2026-11-24T12:01:00+09:00', commit: '5c69aab', title: '받는 전화 · 여러 언어', notice: null, added: [item('AI 전화가 걸려 오는 전화를 받습니다')], fixed: [], safety: [item('수신거부한 번호의 전화는 받지 않습니다')] },
  { at: '2026-11-23T08:47:00+09:00', commit: '79cd19d', title: '음성 연결 고침', notice: null, added: [], fixed: [item('AI 전화의 음성 연결이 다시 됩니다', 'Gemini Live v1alpha 로 연결')], safety: [] },
];

const show = () => render(<DevConsole windowId="w1" params={{ tab: 'updates' }} />);
const cards = () => screen.queryAllByRole('article').map((a) => a.getAttribute('aria-label'));

beforeEach(() => {
  localStorage.clear();
  setup();
});
afterEach(() => vi.unstubAllGlobals());

describe('업데이트 내역', () => {
  test('the tab sits after 접속 기록', () => {
    show();
    const tabs = screen.getAllByRole('tab').map((t) => t.textContent);
    expect(tabs.slice(-2)).toEqual(['접속 기록', '업데이트 내역']);
  });

  test('cards newest first, grouped by date, with three columns and the notice', async () => {
    mockUpdates({ entries: ENTRIES, running_commit: null });
    show();
    await screen.findByRole('article', { name: /기기 이어 쓰기/ });
    expect(cards()).toEqual(['오후 2:12 기기 이어 쓰기 · 프로젝트 관리', '오후 12:01 받는 전화 · 여러 언어', '오전 8:47 음성 연결 고침']);
    expect(screen.getAllByRole('heading', { level: 3, name: /^11월 2\d일/ }).map((h) => h.textContent)).toEqual(['11월 24일 (화) · 2판', '11월 23일 (월) · 1판']);
    const top = screen.getByRole('article', { name: /기기 이어 쓰기/ });
    expect(within(top).getByRole('note')).toHaveTextContent('모두 한 번 다시 로그인');
    expect(within(top).getByRole('list', { name: '새 기능' }).children).toHaveLength(2);
    expect(within(top).getByRole('list', { name: '고침' })).toHaveTextContent('받아쓰기를 한국어로 고정음성 진단도 같은 설정');
    expect(top).toHaveTextContent('새 기능 2 · 고침 1 · 안전 1');
    expect(top).toHaveTextContent('c5f1c23');
    const mid = screen.getByRole('article', { name: /받는 전화/ });
    expect(within(mid).getByText('없음')).toBeVisible(); // 고침 없음
    expect(within(mid).queryByRole('note')).toBeNull();
    expect(screen.getByText(/deploy\/updates\.jsonl/)).toBeVisible();
  });

  test('the card whose commit is the running server commit says 지금 실서버 판', async () => {
    mockUpdates({ entries: ENTRIES, running_commit: '5c69aab' });
    show();
    const live = await screen.findByRole('article', { name: /받는 전화/ });
    expect(within(live).getByText('지금 실서버 판')).toBeVisible();
    expect(screen.getAllByText('지금 실서버 판')).toHaveLength(1);
  });

  test('the live commit matches by prefix either way (a longer or shorter sha), but not below 7 characters', async () => {
    mockUpdates({ entries: ENTRIES, running_commit: '5c69aab0123' });
    const { unmount } = show();
    expect(within(await screen.findByRole('article', { name: /받는 전화/ })).getByText('지금 실서버 판')).toBeVisible();
    unmount();
    mockUpdates({ entries: [{ ...ENTRIES[1], commit: '5c69aab9f' }], running_commit: '5c69aab' });
    const second = show();
    expect(within(await screen.findByRole('article', { name: /받는 전화/ })).getByText('지금 실서버 판')).toBeVisible();
    second.unmount();
    mockUpdates({ entries: ENTRIES, running_commit: '5c69' });
    show();
    await screen.findByRole('article', { name: /받는 전화/ });
    expect(screen.queryByText('지금 실서버 판')).toBeNull();
    expect(screen.getByText(/지금 실서버 커밋 5c69 은 기록에 없습니다/)).toBeVisible();
  });

  test('a running commit not in the record is said so; an unreadable one too', async () => {
    mockUpdates({ entries: ENTRIES, running_commit: 'abc1234' });
    const { unmount } = show();
    expect(await screen.findByText(/지금 실서버 커밋 abc1234 은 기록에 없습니다/)).toBeVisible();
    expect(screen.queryByText('지금 실서버 판')).toBeNull();
    unmount();
    mockUpdates({ entries: ENTRIES, running_commit: null });
    show();
    expect(await screen.findByText(/지금 실서버 커밋을 읽지 못했습니다/)).toBeVisible();
  });

  test('category chips count items and keep only the cards (and the column) of that kind', async () => {
    mockUpdates({ entries: ENTRIES, running_commit: null });
    show();
    await screen.findByRole('article', { name: /기기 이어 쓰기/ });
    const chips = screen.getByRole('group', { name: '갈래로 거르기' });
    expect(within(chips).getAllByRole('button').map((b) => b.textContent)).toEqual(['전체', '새 기능 3', '고침 2', '안전 2']);
    await userEvent.click(within(chips).getByRole('button', { name: '고침 2' }));
    expect(cards()).toEqual(['오후 2:12 기기 이어 쓰기 · 프로젝트 관리', '오전 8:47 음성 연결 고침']);
    const top = screen.getByRole('article', { name: /기기 이어 쓰기/ });
    expect(within(top).queryByRole('list', { name: '새 기능' })).toBeNull();
    expect(within(top).getByRole('list', { name: '고침' })).toBeVisible();
  });

  test('search finds a card by an item, a title or a commit', async () => {
    mockUpdates({ entries: ENTRIES, running_commit: null });
    show();
    await screen.findByRole('article', { name: /기기 이어 쓰기/ });
    const box = screen.getByRole('searchbox', { name: '바뀐 점 찾기' });
    await userEvent.type(box, '수신거부');
    expect(cards()).toEqual(['오후 12:01 받는 전화 · 여러 언어']);
    await userEvent.clear(box);
    await userEvent.type(box, '79cd19d');
    expect(cards()).toEqual(['오전 8:47 음성 연결 고침']);
    await userEvent.clear(box);
    await userEvent.type(box, '없는 말');
    expect(screen.getByText('맞는 판이 없습니다.')).toBeVisible();
  });

  test('an empty record says nothing has been written yet', async () => {
    show();
    expect(await screen.findByText(/아직 기록된 판이 없습니다/)).toBeVisible();
  });
});
