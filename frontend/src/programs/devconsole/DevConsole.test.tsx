import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { useWindows } from '../../os/windowStore';
import { json } from '../../test-helpers';
import DevConsole from './DevConsole';
import manifest from './index';
import { done, fetchCount, fetchMock, lastUrl, mockTurn, mockTurnSequence, mockUsage, running, setup, urls } from './testKit';

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const structure = () => screen.findByRole('group', { name: '에이전트 구조' });
const node = async (label: string) => within(await structure()).getByRole('button', { name: new RegExp(`^${escape(label)}`) });
const detail = () => screen.getByRole('complementary', { name: '칸 상세' });
const show = () => render(<DevConsole windowId="w1" />);
async function openUsage() {
  show();
  await userEvent.click(screen.getByRole('tab', { name: '사용량·비용' }));
  await screen.findByRole('table', { name: '사용량' });
}
async function openTrace() {
  show();
  await structure();
  await userEvent.click(screen.getByRole('tab', { name: '실행 추적' }));
  return screen.findByRole('list', { name: '실행 추적' });
}

let openSpy: ReturnType<typeof vi.fn>;
beforeEach(() => {
  localStorage.clear();
  setup();
  openSpy = vi.fn();
  useWindows.setState({ open: openSpy } as never);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('지시서 시험', () => {
  test('three tabs only', () => {
    show();
    expect(screen.getAllByRole('tab').map((t) => t.textContent)).toEqual(['에이전트 구조', '실행 추적', '사용량·비용']);
  });

  test('now node is lit and loop count shown', async () => {
    mockTurn(running({ now: 'tool', loop: 4 }));
    show();
    expect(await node('도구 실행')).toHaveClass('now');
    expect(screen.getByText('4바퀴')).toBeVisible();
    expect(screen.getByText('/ 한도 12')).toBeVisible();
  });

  test('skill node says it comes later', async () => {
    show();
    expect(await node('스킬 찾기')).toHaveClass('skipped');
    expect(screen.getByText('묶음 3')).toBeVisible();
  });

  test('clicking a node shows its detail folded', async () => {
    show();
    await userEvent.click(await node('컨텍스트 조립'));
    expect(screen.getByText(/지시문 \d+%/)).toBeVisible();
    expect(screen.getByRole('button', { name: '들어간 것 펼치기' })).toBeVisible();
  });

  test('running turn polls every second and stops when done', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'], shouldAdvanceTime: true });
    mockTurnSequence([running(), done()]);
    show();
    // 첫 읽기(목록 → 상세)가 끝나 그림이 뜬 뒤부터 센다(워크플로우 시험과 같은 방식).
    expect(await node('도구 실행')).toHaveClass('now');
    await act(() => vi.advanceTimersByTimeAsync(2500));
    expect(fetchCount()).toBe(2);
    expect(await node('도구 실행')).toHaveClass('past');
    await act(() => vi.advanceTimersByTimeAsync(5000));
    expect(fetchCount()).toBe(2);
  });

  // 실제 API 의 llm 줄 이름은 "모델 호출 (normal)" 이다(지시서 시험의 /llm/ 대신).
  test('trace rows expand to raw text blocks', async () => {
    await openTrace();
    await userEvent.click((await screen.findAllByRole('button', { name: /모델 호출 \(normal\)/ }))[0]);
    expect(screen.getByText('입력 원문')).toBeVisible();
  });

  test('usage shows dash and note when cost is unknown', async () => {
    mockUsage({ cost_known: false, rows: [{ key: 'claude-sonnet-5.5', calls: 2, input_tokens: 150, output_tokens: 30, cost: null, failed: 0 }] });
    await openUsage();
    expect(screen.getByText('Liner가 비용 값을 보내지 않아 비용은 비어 있습니다(토큰만 셉니다).')).toBeVisible();
    const row = screen.getByRole('row', { name: /claude-sonnet-5\.5/ });
    expect(within(row).getByText('—')).toBeVisible();
  });

  test('usage group switch refetches', async () => {
    await openUsage();
    await userEvent.selectOptions(screen.getByLabelText('묶는 기준'), 'user');
    await waitFor(() => expect(lastUrl()).toContain('group=user'));
  });
});

describe('관리자만', () => {
  test('a non-admin sees why and nothing is fetched', () => {
    setup('user');
    show();
    expect(screen.getByText('개발 콘솔은 관리자만 쓸 수 있습니다.')).toBeVisible();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test('the server refusal is shown as its message', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json(403, { code: 'admin_only', message: '관리자만 쓸 수 있습니다.', detail: null })));
    show();
    expect(await screen.findByRole('alert')).toHaveTextContent('관리자만 쓸 수 있습니다.');
  });

  test('the manifest keeps the admin-only system window at 1600×900', () => {
    expect(manifest).toMatchObject({ id: 'devconsole', name: '개발 콘솔', kind: 'system', adminOnly: true, defaultSize: { w: 1600, h: 900 } });
  });
});

describe('위 줄과 요청 고르기', () => {
  test('a running turn shows calls, tokens and the running time but no cost', async () => {
    show();
    await structure();
    const bar = screen.getByRole('group', { name: '이 요청' });
    expect(bar).toHaveTextContent('도구 호출 5');
    expect(bar).toHaveTextContent('모델 호출 4');
    expect(bar).toHaveTextContent('토큰 21.4K');
    expect(bar).toHaveTextContent(/1\d\.\d초째/);
    expect(bar).not.toHaveTextContent('$');
  });

  test('a finished turn shows its cost and total time', async () => {
    mockTurn(done());
    show();
    await structure();
    const bar = screen.getByRole('group', { name: '이 요청' });
    expect(bar).toHaveTextContent('$0.12');
    expect(bar).toHaveTextContent('41.2초');
    expect(bar).not.toHaveTextContent('초째');
  });

  test('the picker reloads recent turns, finds by text and opens the chosen turn', async () => {
    show();
    await structure();
    await userEvent.click(screen.getByRole('button', { name: /^요청:/ }));
    const dialog = screen.getByRole('dialog', { name: '요청 고르기' });
    expect(urls().filter((u) => u === '/api/devconsole/turns?limit=30')).toHaveLength(2);
    await userEvent.type(within(dialog).getByRole('searchbox', { name: '요청 찾기' }), '공정표');
    const choices = within(dialog).getAllByRole('button');
    expect(choices.map((b) => b.textContent)).toEqual([expect.stringContaining('5층 사무동 공정표 만들어 줘')]);
    await userEvent.click(choices[0]);
    expect(screen.queryByRole('dialog')).toBeNull();
    await waitFor(() => expect(urls()).toContain('/api/devconsole/turns/38'));
    expect(await screen.findByRole('button', { name: /^요청: 5층 사무동 공정표/ })).toBeVisible();
  });

  test('escape closes the picker and it opens again with an empty search', async () => {
    show();
    await structure();
    const picker = screen.getByRole('button', { name: /^요청:/ });
    await userEvent.click(picker);
    await userEvent.type(screen.getByRole('searchbox', { name: '요청 찾기' }), '공정표');
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).toBeNull();
    await userEvent.click(picker);
    expect(screen.getByRole('searchbox', { name: '요청 찾기' })).toHaveValue('');
    expect(within(screen.getByRole('dialog')).getAllByRole('button')).toHaveLength(2);
  });
});

describe('칸 상세', () => {
  test('a model node names its model and a code node says it uses none', async () => {
    show();
    await userEvent.click(await node('판단 (모델)'));
    expect(within(detail()).getByText('claude-sonnet-5.5')).toBeVisible();
    await userEvent.click(await node('조건 점검'));
    expect(within(detail()).getByText('쓰지 않음 (코드)')).toBeVisible();
    expect(within(detail()).getByText('점검 한도 5회')).toBeVisible();
  });

  test('expanding what went in shows an indented, foldable tree', async () => {
    show();
    await userEvent.click(await node('도구 실행'));
    await userEvent.click(within(detail()).getByRole('button', { name: '들어간 것 펼치기' }));
    const tree = within(detail()).getByRole('group', { name: '들어간 것 내용' });
    expect(within(tree).getByText('1. schedule.read')).toBeVisible();
    expect(within(tree).getAllByText('"A2020"')[0]).toBeVisible();
    expect(within(detail()).getByRole('button', { name: '들어간 것 접기' })).toBeVisible();
  });

  test('the context time says it is longer than the real assembly', async () => {
    show();
    await userEvent.click(await node('컨텍스트 조립'));
    const note = within(detail()).getByText('실제보다 김');
    expect(note).toHaveAttribute('title', expect.stringContaining('다시 만든 시간'));
  });

  test('approval settings open the settings approval section', async () => {
    show();
    await userEvent.click(await node('승인 판단'));
    expect(within(detail()).getByText('승인 수준: 모두 승인')).toBeVisible();
    await userEvent.click(within(detail()).getByRole('button', { name: '설정 열기' }));
    expect(openSpy).toHaveBeenCalledWith('settings', { section: 'approval' });
  });
});

describe('실행 추적의 알려진 한계', () => {
  test('tool start times are marked estimated and parallel calls are grouped', async () => {
    const list = await openTrace();
    const rows = within(list).getAllByRole('button', { name: /schedule\.read|delay\.impact/ });
    for (const r of rows) expect(within(r).getByText('어림')).toBeVisible();
    expect(within(rows[0]).getByText('동시 2')).toBeVisible();
    expect(within(rows[1]).getByText('동시 2')).toBeVisible();
    expect(within(list).getAllByText(/^\d+바퀴$/).map((e) => e.textContent)).toEqual(['1바퀴', '2바퀴', '3바퀴', '4바퀴']);
  });

  test('a step after an unreadable reply says it has no pair', async () => {
    mockTurn(done({}, { unpaired: true }));
    const list = await openTrace();
    const row = within(list).getByRole('button', { name: /harness\.check/ });
    expect(within(row).getByText('짝 없음')).toHaveAttribute('title', expect.stringContaining('잘려'));
  });

  test('an inner model call says it keeps no text', async () => {
    const list = await openTrace();
    await userEvent.click(within(list).getByRole('button', { name: /도구 안 모델 호출/ }));
    expect(within(list).getByText('도구 안 모델 호출은 글을 남기지 않습니다(모델·토큰·시간만).')).toBeVisible();
  });
});

describe('사용량', () => {
  test('rows show token bars, a total line and search calls', async () => {
    await openUsage();
    const table = screen.getByRole('table', { name: '사용량' });
    expect(within(table).getByRole('row', { name: /합계/ })).toHaveTextContent('15');
    expect(within(table).getAllByRole('meter')).toHaveLength(2);
    expect(screen.getByText('근거 검색 6번 · 실패 1')).toBeVisible();
  });

  test('known cost is shown and the period switch refetches', async () => {
    mockUsage({ cost_known: true, rows: [{ key: 'claude-sonnet-5.5', calls: 2, input_tokens: 150, output_tokens: 30, cost: 0.05, failed: 0 }], totals: { calls: 2, input_tokens: 150, output_tokens: 30, cost: 0.05, failed: 0 } });
    await openUsage();
    expect(screen.queryByText(/Liner가 비용 값을/)).toBeNull();
    expect(screen.getByRole('row', { name: /claude-sonnet-5\.5/ })).toHaveTextContent('$0.05');
    await userEvent.selectOptions(screen.getByLabelText('기간'), '30');
    await waitFor(() => expect(lastUrl()).toBe('/api/devconsole/usage?days=30&group=model'));
  });
});
