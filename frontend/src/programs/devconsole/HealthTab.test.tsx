// 시스템 진단(시안 A): 판정 한 줄 · 개수 칩(거르개) · 찾기 · 「먼저 볼 것」(실패 → 확인 필요 → 모름) · 영역 4묶음 · 마지막 확인 · 강제 중단.
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import DevConsole from './DevConsole';
import { fetchMock, kakaoHealth, mockHealth, notifyHealth, openCheck, setup, urls, voiceHealth } from './testKit';

const show = () => render(<DevConsole windowId="w1" params={{ tab: 'health' }} />);
const groups = () => screen.getByRole('group', { name: '영역 묶음' });
const pinned = () => screen.getByRole('region', { name: '먼저 볼 것' });
const rowNames = (el: HTMLElement) =>
  within(el).queryAllByRole('button', { name: / — / }).map((b) => b.getAttribute('aria-label')!);

/** 시안과 같은 섞인 상태: 벡터 검색 실패 · 문자 확인 필요(보냈는지 모름 2건) · 정보 API 확인 필요 · AI 전화 모름. */
function mixed() {
  mockHealth({
    qdrant: { status: 'error', collections: [], points_count: 0, latency_ms: 3004, message: 'Qdrant 서버에 연결할 수 없습니다.' },
    info_api: {
      status: 'warn', count: 2, message: '연결 2개 · 마지막 연결 시험 실패 1개',
      connections: [
        { id: 1, name: '기상청 단기예보', kind: 'kma', status: 'ok', checked_at: '2026-11-24T04:10:00Z' },
        { id: 2, name: '건설기계 대여 시세', kind: 'generic', status: 'failed', checked_at: '2026-11-24T03:55:00Z' },
      ],
    },
    evidence_reuse: { reusable: 4, reused_7d: 6, searches_7d: 9, days: 30 },
    notify: notifyHealth({ needs_check: 2, kakao: kakaoHealth({ ready: true }), voice: voiceHealth({ status: 'unknown', checked_at: null, last_diagnosis: null }) }),
    presence: { online_users: 3, online_devices: 5 },
  });
}

beforeEach(() => {
  localStorage.clear();
  setup();
});
afterEach(() => vi.unstubAllGlobals());

describe('요약 줄', () => {
  test('one verdict line, count chips by the four states, people · devices · running turns', async () => {
    mixed();
    show();
    const strip = await screen.findByRole('group', { name: '요약' });
    expect(within(strip).getByText('1개가 멈췄습니다')).toBeVisible();
    const chips = within(strip).getByRole('group', { name: '상태로 거르기' });
    expect(within(chips).getAllByRole('button').map((b) => b.textContent)).toEqual(['전체 9', '정상 5', '확인 필요 2', '실패 1', '모름 1']);
    expect(strip).toHaveTextContent('접속 중 3명 · 기기 5대 · 실행 중 턴 1건');
  });

  test('all fine says 모두 정상; only checks say 확인할 것 n개', async () => {
    show();
    expect(await screen.findByText('모두 정상')).toBeVisible();
  });

  test('no presence field (older server) leaves out the people count but keeps running turns', async () => {
    mockHealth({ qdrant: { status: 'off', collections: [], points_count: 0, latency_ms: null, message: '꺼 둠' } });
    show();
    const strip = await screen.findByRole('group', { name: '요약' });
    expect(within(strip).getByText('확인할 것 1개')).toBeVisible();
    expect(strip).not.toHaveTextContent('접속 중');
    expect(strip).toHaveTextContent('실행 중 턴 1건');
  });
});

describe('먼저 볼 것', () => {
  test('실패 → 확인 필요 → 모름, each with 할 일; a click opens 지금 상태 · 영향 · 기계 출력', async () => {
    mixed();
    show();
    await screen.findByText('1개가 멈췄습니다');
    expect(rowNames(pinned())).toEqual(['벡터 검색 서버 — 실패', '문자 연결 — 확인 필요', '정보 API — 확인 필요', 'AI 전화 — 모름']);
    expect(within(pinned()).getByText('연락처에서 2건 확인')).toBeVisible();
    await userEvent.click(within(pinned()).getByRole('button', { name: '벡터 검색 서버 — 실패' }));
    const open = within(pinned()).getByRole('region', { name: '벡터 검색 서버 자세히' });
    expect(within(open).getByRole('heading', { name: '지금 상태' })).toBeVisible();
    expect(open).toHaveTextContent('기다린 시간3,004ms');
    expect(within(open).getByRole('heading', { name: '영향' })).toBeVisible();
    expect(open).toHaveTextContent('낱말이 같은 글만 찾습니다');
    expect(within(open).getByRole('button', { name: '기계 출력 펼치기' })).toBeVisible();
  });

  test('nothing to look at → no 먼저 볼 것 box', async () => {
    show();
    await screen.findByText('모두 정상');
    expect(screen.queryByRole('region', { name: '먼저 볼 것' })).toBeNull();
  });
});

describe('영역 묶음', () => {
  test('four groups, one row per check with its last-checked time', async () => {
    mixed();
    show();
    await screen.findByText('1개가 멈췄습니다');
    const g = groups();
    expect(within(g).getAllByRole('heading', { level: 3 }).map((h) => h.textContent)).toEqual(['AI · 검색', '문자 · 카카오톡 · 전화', '자료', '지금 접속 · 실행 중']);
    const ai = within(g).getByRole('region', { name: 'AI · 검색' });
    expect(rowNames(ai)).toEqual(['AI 모델 연결 — 정상', '근거 검색 — 정상', '근거 다시 쓰기 — 정상', '벡터 검색 서버 — 실패']);
    // 서버가 시각을 주지 않는 칸은 진단을 부른 때, AI 전화는 아직 진단 안 함 → —
    const llmRow = within(ai).getByRole('button', { name: 'AI 모델 연결 — 정상' });
    expect(within(llmRow).getByTitle(/진단을 부른 때/)).toBeVisible();
    const voiceRow = within(g).getByRole('button', { name: 'AI 전화 — 모름' });
    expect(within(voiceRow).getByTitle(/아직 확인한 적 없음/)).toHaveTextContent('—');
  });

  test('a chip filters rows; 전체 brings them back', async () => {
    mixed();
    show();
    await screen.findByText('1개가 멈췄습니다');
    await userEvent.click(screen.getByRole('button', { name: '실패 1' }));
    expect(screen.getByRole('button', { name: '실패 1' })).toHaveAttribute('aria-pressed', 'true');
    expect(rowNames(groups())).toEqual(['벡터 검색 서버 — 실패']);
    expect(rowNames(pinned())).toEqual(['벡터 검색 서버 — 실패']);
    await userEvent.click(screen.getByRole('button', { name: '전체 9' }));
    expect(rowNames(groups()).length).toBeGreaterThan(5);
  });

  test('search finds a row by its plain name, tech name or summary, and says when nothing matches', async () => {
    mixed();
    show();
    await screen.findByText('1개가 멈췄습니다');
    const box = screen.getByRole('searchbox', { name: '점검 항목 찾기' });
    await userEvent.type(box, 'qdrant');
    expect(rowNames(groups())).toEqual(['벡터 검색 서버 — 실패']);
    await userEvent.clear(box);
    await userEvent.type(box, '한빛 현장');
    expect(rowNames(groups())).toEqual(['카카오톡 — 정상']);
    await userEvent.clear(box);
    await userEvent.type(box, '없는말');
    expect(screen.getByText('맞는 점검 항목이 없습니다.')).toBeVisible();
  });

  test('a stopped-turn row keeps 강제 중단 working and 다시 점검 reads the diagnosis again', async () => {
    show();
    await screen.findByText('모두 정상');
    const live = within(groups()).getByRole('region', { name: '지금 접속 · 실행 중' });
    expect(within(live).getByText('골조 지연 만회')).toBeVisible();
    const before = urls().filter((u) => u === '/api/devconsole/health').length;
    await userEvent.click(within(live).getByRole('button', { name: '강제 중단' }));
    await waitFor(() => expect(urls()).toContain('/api/devconsole/turns/7/stop'));
    await waitFor(() => expect(urls().filter((u) => u === '/api/devconsole/health').length).toBe(before + 1));
    await userEvent.click(screen.getByRole('button', { name: '다시 점검' }));
    await waitFor(() => expect(urls().filter((u) => u === '/api/devconsole/health').length).toBe(before + 2));
  });

  test('a field the screen does not know yet shows in 기타 with its raw output', async () => {
    mockHealth({ backup: { status: 'error', message: '백업 실패' } });
    show();
    const row = await openCheck('backup');
    expect(within(groups()).getByRole('heading', { name: '기타' })).toBeVisible();
    expect(row).toHaveTextContent('백업 실패');
    expect(within(row).getByRole('button', { name: '기계 출력 펼치기' })).toBeVisible();
  });

  test('the console only reads: no POST while showing the diagnosis', async () => {
    mixed();
    show();
    await openCheck('문자 연결');
    await openCheck('AI 전화');
    expect(fetchMock.mock.calls.some(([, init]) => (init as RequestInit | undefined)?.method === 'POST')).toBe(false);
  });
});
