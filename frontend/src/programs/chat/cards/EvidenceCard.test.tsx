// 근거 카드의 저장된 근거(설계 2026-11-23): evidence.search 가 다시 쓴 결과의 card 사건 모양 그대로. 사람·현장은 가상.
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { json, signInAsDemo, stubFetch } from '../../../test-helpers';
import { CardView, type CardCtx } from './index';

const ctx: CardCtx = { sessionId: 1, sendText: async () => true, failedQuestionnaire: null, retryResume: () => {} };
const row = (id: number, searched_at: string) => ({
  evidence_id: id, title: `골조 공기 기준 ${id}`, url: `https://example.com/${id}`, hostname: 'example.com', date: '2026-03-01', searched_at,
});
const REUSED = { kind: 'evidence', search_id: 9, query: '층당 골조 공기', mode: 'web', reused: true, results: [row(1, '2026-11-20')] };

beforeEach(() => signInAsDemo());
afterEach(() => vi.unstubAllGlobals());

test('a reused card says it is saved evidence and when it was searched', () => {
  render(<CardView event="card" data={REUSED} ctx={ctx} />);
  expect(screen.getByText('저장된 근거 · 11-20 검색')).toBeVisible();
  expect(screen.getByRole('button', { name: '근거 1 다시 쓰지 않기' })).toHaveTextContent('다시 쓰지 않기');
});

test('items searched on different days show the range', () => {
  render(<CardView event="card" data={{ ...REUSED, results: [row(1, '2026-11-20'), row(2, '2026-11-02')] }} ctx={ctx} />);
  expect(screen.getByText('저장된 근거 · 11-02~11-20 검색')).toBeVisible();
});

test('a row found by another mode shows its own mode chip', () => {
  const rows = [{ ...row(1, '2026-11-20'), mode: 'legal' }, { ...row(2, '2026-11-20'), mode: 'web' }];
  render(<CardView event="card" data={{ ...REUSED, mode: 'legal', results: rows }} ctx={ctx} />);
  const items = screen.getAllByRole('listitem');
  expect(items[0]).not.toHaveTextContent('웹');
  expect(within(items[1]).getByText('웹')).toBeVisible();
  expect(screen.getAllByText('법령 검색')).toHaveLength(1); // 카드 머리의 배지만
});

// A8: 「법령」 이름표는 출처 종류가 아니라 검색 방식이다 — 줄마다 정부 누리집(*.go.kr)이면 공식, 아니면 일반 글
const LEGAL = {
  kind: 'evidence', search_id: 3, query: '착공신고 처리 기한', mode: 'legal',
  results: [
    { ...row(1, ''), url: 'https://www.law.go.kr/법령/건축법', hostname: 'law.go.kr' },
    { ...row(2, ''), url: 'https://blog.naver.com/x/1', hostname: 'blog.naver.com' },
    { ...row(3, ''), url: 'https://www.youtube.com/watch?v=1', hostname: 'youtube.com' },
  ],
};

test('a legal card is labelled as a legal search and marks official and general rows', () => {
  render(<CardView event="card" data={LEGAL} ctx={ctx} />);
  expect(screen.getByText('법령 검색')).toBeVisible();
  const items = screen.getAllByRole('listitem');
  expect(within(items[0]).getByText('공식')).toBeVisible();
  expect(within(items[1]).getByText('일반 글')).toBeVisible();
  expect(within(items[2]).getByText('일반 글')).toBeVisible();
  expect(within(items[0]).queryByText('일반 글')).toBeNull();
});

test('a web card has no official or general marks', () => {
  render(<CardView event="card" data={{ ...LEGAL, mode: 'web' }} ctx={ctx} />);
  expect(screen.queryByText('공식')).toBeNull();
  expect(screen.queryByText('일반 글')).toBeNull();
});

test('a new search card has no saved-evidence line or retire button', () => {
  render(<CardView event="card" data={{ ...REUSED, reused: undefined, results: [{ ...row(1, ''), searched_at: undefined }] }} ctx={ctx} />);
  expect(screen.queryByText(/저장된 근거/)).toBeNull();
  expect(screen.queryByRole('button', { name: /다시 쓰지 않기/ })).toBeNull();
});

test('retire then undo calls the server and swaps the row control', async () => {
  const fetchSpy = stubFetch({
    'POST /api/evidence/1/retire': { id: 1, retired: true },
    'POST /api/evidence/1/restore': { id: 1, retired: false },
  });
  render(<CardView event="card" data={REUSED} ctx={ctx} />);
  await userEvent.click(screen.getByRole('button', { name: '근거 1 다시 쓰지 않기' }));
  expect(await screen.findByText('다시 쓰지 않음')).toBeVisible();
  expect(fetchSpy.mock.calls.map((c) => [String(c[0]), c[1]?.method])).toEqual([['/api/evidence/1/retire', 'POST']]);
  await userEvent.click(screen.getByRole('button', { name: '근거 1 되돌리기' }));
  await waitFor(() => expect(screen.getByRole('button', { name: '근거 1 다시 쓰지 않기' })).toBeVisible());
  expect(String(fetchSpy.mock.calls[1][0])).toBe('/api/evidence/1/restore');
  expect(screen.queryByText('다시 쓰지 않음')).toBeNull();
});

test('a failed retire keeps the button and says why', async () => {
  stubFetch({ 'POST /api/evidence/1/retire': () => json(404, { code: 'not_found', message: '근거를 찾을 수 없습니다.', detail: null }) });
  render(<CardView event="card" data={REUSED} ctx={ctx} />);
  await userEvent.click(screen.getByRole('button', { name: '근거 1 다시 쓰지 않기' }));
  expect(await screen.findByText('근거를 찾을 수 없습니다.')).toBeVisible();
  expect(screen.getByRole('button', { name: '근거 1 다시 쓰지 않기' })).toBeEnabled();
});
