import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { useWindows } from '../../os/windowStore';
import { json } from '../../test-helpers';
import DevConsole from './DevConsole';
import manifest from './index';
import {
  done,
  fetchCount,
  fetchMock,
  lastUrl,
  mockHarness,
  mockHealth,
  mockOutreach,
  mockOutreachList,
  mockTurn,
  mockTurnSequence,
  mockUsage,
  notifyHealth,
  openCheck,
  outreachDetail,
  outreachRow,
  running,
  setup,
  urls,
} from './testKit';

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const structure = () => screen.findByRole('group', { name: '에이전트 구조' });
const node = async (label: string) => within(await structure()).getByRole('button', { name: new RegExp(`^${escape(label)}`) });
const detail = () => screen.getByRole('complementary', { name: '칸 상세' });
const show = () => render(<DevConsole windowId="w1" />);
const bar = () => screen.getByRole('group', { name: '이 요청' });
/** 가짜 시계(setTimeout·Date)를 쓰는 시험: 첫 읽기를 끝내고, ms 만큼 정확히 옮긴다. */
const fakeClock = () => vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
const tick = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms));
async function settle() {
  for (let i = 0; i < 20; i++) await tick(0);
}
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
  test('eight tabs including harness, sources, registry, health and updates', () => {
    show();
    expect(screen.getAllByRole('tab').map((t) => t.textContent)).toEqual([
      '에이전트 구조',
      '하네스·차단 시험',
      '프롬프트·지식',
      '도구·스킬',
      '시스템 진단',
      '실행 추적',
      '사용량·비용',
      '업데이트 내역',
    ]);
  });

  test('now node is lit and loop count shown', async () => {
    mockTurn(running({ now: 'tool', loop: 4 }));
    show();
    expect(await node('도구 실행')).toHaveClass('now');
    expect(screen.getByText('4바퀴')).toBeVisible();
    expect(screen.getByText('/ 한도 12')).toBeVisible();
  });

  test('skill node says no match when skipped', async () => {
    show();
    expect(await node('스킬 찾기')).toHaveClass('skipped');
    expect(screen.getByText('일치 없음')).toBeVisible();
  });

  test('skill node detail says the real result: no matching skill, or the applied skill name (U7)', async () => {
    show();
    await userEvent.click(await node('스킬 찾기'));
    expect(within(detail()).getByText('맞는 스킬 없음')).toBeVisible();
    expect(detail()).not.toHaveTextContent(/묶음 3|늘 건너뜁니다/);
  });

  test('a matched skill shows its name in this turn (U7)', async () => {
    const d = done();
    d.structure.nodes = d.structure.nodes.map((n) =>
      n.key === 'skill' ? { ...n, state: 'past', count: 1, detail: { ...n.detail, in: '골조 지연 만회' } } : n,
    );
    mockTurn(d);
    show();
    await userEvent.click(await node('스킬 찾기'));
    expect(within(detail()).getByText('적용: 골조 지연 만회')).toBeVisible();
  });

  test('clicking a node shows its detail folded', async () => {
    show();
    await userEvent.click(await node('컨텍스트 조립'));
    expect(screen.getByText(/지시문 \d+%/)).toBeVisible();
    expect(screen.getByRole('button', { name: '들어간 것 펼치기' })).toBeVisible();
  });

  test('running turn polls every second and stops when done', async () => {
    fakeClock();
    mockTurnSequence([running(), running(), done()]);
    show();
    await settle();
    expect(fetchCount()).toBe(1);
    await tick(999);
    expect(fetchCount()).toBe(1);
    await tick(1);
    expect(fetchCount()).toBe(2);
    await tick(999);
    expect(fetchCount()).toBe(2);
    await tick(1);
    expect(fetchCount()).toBe(3);
    expect(within(screen.getByRole('group', { name: '에이전트 구조' })).getByRole('button', { name: /^도구 실행/ })).toHaveClass('past');
    await tick(5000);
    expect(fetchCount()).toBe(3);
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

  test('a turn cost that includes estimates says so', async () => {
    mockTurn(done({ cost_estimated: 'some' }));
    show();
    await structure();
    expect(screen.getByRole('group', { name: '이 요청' })).toHaveTextContent('약 $0.12 (일부 추정)');
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
    expect(screen.getByRole('button', { name: /^요청:/ })).toHaveFocus();
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
    expect(picker).toHaveFocus();
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

  test('estimated costs say 추정, and a total with some estimates says 일부 추정', async () => {
    mockUsage({
      cost_known: true,
      rows: [
        { key: 'claude-haiku-5.5', calls: 2, input_tokens: 150, output_tokens: 30, cost: 0.03, failed: 0, cost_estimated: 'all' },
        { key: 'deepseek-v4', calls: 1, input_tokens: 10, output_tokens: 3, cost: 0.75, failed: 0, cost_estimated: null },
      ],
      totals: { calls: 3, input_tokens: 160, output_tokens: 33, cost: 0.78, failed: 0, cost_estimated: 'some' },
    });
    await openUsage();
    expect(screen.getByRole('row', { name: /claude-haiku-5\.5/ })).toHaveTextContent('약 $0.03 (추정)');
    expect(screen.getByRole('row', { name: /deepseek-v4/ })).toHaveTextContent('$0.75');
    expect(screen.getByRole('row', { name: /deepseek-v4/ })).not.toHaveTextContent('추정');
    expect(screen.getByRole('row', { name: /합계/ })).toHaveTextContent('약 $0.78 (일부 추정)');
  });
});

describe('Fix round 1', () => {
  test('I1: a cut-off JSON text says it cannot become a tree and shows only its first 300 characters', async () => {
    const d = done();
    const messages = Array.from({ length: 400 }, (_, i) => ({ role: 'user', content: `메시지 ${i}` }));
    d.timeline[1] = { ...d.timeline[1], input_text: `${JSON.stringify(messages).slice(0, 5000)}\n(뒤는 생략)` };
    mockTurn(d);
    const list = await openTrace();
    await userEvent.click(within(list).getAllByRole('button', { name: /모델 호출 \(normal\)/ })[0]);
    expect(within(list).getByText(/길어서 잘린 원문 — 나무로 풀 수 없음/)).toBeVisible();
    await userEvent.click(within(list).getByRole('button', { name: '입력 원문 펼치기' }));
    const body = within(list).getByRole('group', { name: '입력 원문 내용' });
    expect(body.textContent!.length).toBeLessThan(400);
    expect(body).not.toHaveTextContent('(뒤는 생략)');
    await userEvent.click(within(body).getByRole('button', { name: /전체 보기/ }));
    expect(body).toHaveTextContent('(뒤는 생략)');
  });

  test('I1: a long plain text at the top shows its first 300 characters', async () => {
    const d = done();
    d.structure.nodes = d.structure.nodes.map((n) => (n.key === 'respond' ? { ...n, detail: { ...n.detail, out: '가'.repeat(1000) } } : n));
    mockTurn(d);
    show();
    await userEvent.click(await node('응답·기록'));
    await userEvent.click(within(detail()).getByRole('button', { name: '나온 것 펼치기' }));
    const body = within(detail()).getByRole('group', { name: '나온 것 내용' });
    expect(body.textContent!.length).toBeLessThan(400);
    expect(within(body).getByRole('button', { name: '전체 보기 (1,000자)' })).toBeVisible();
  });

  test('a refused read stops polling, shows why and stops the clock', async () => {
    fakeClock();
    mockTurnSequence([running(), 404]);
    show();
    await settle();
    await tick(1000);
    expect(fetchCount()).toBe(2);
    expect(screen.getByRole('alert')).toHaveTextContent('실행 추적을 찾을 수 없습니다.');
    const stopped = bar().textContent;
    expect(stopped).toMatch(/\d+\.\d초째까지 확인/);
    await tick(10_000);
    expect(fetchCount()).toBe(2);
    expect(bar().textContent).toBe(stopped);
  });

  test('other failures retry after 1, 2 and then 5 seconds while the clock keeps ticking', async () => {
    fakeClock();
    mockTurnSequence([running(), 500, 500, 500, 500, 500]);
    show();
    await settle();
    const secs = () => Number(/(\d+\.\d)초째/.exec(bar().textContent ?? '')![1]);
    const first = secs();
    await tick(1000);
    expect(fetchCount()).toBe(2);
    expect(screen.getByRole('alert')).toHaveTextContent('서버 오류가 났습니다.');
    await tick(999);
    expect(fetchCount()).toBe(2);
    await tick(1);
    expect(fetchCount()).toBe(3);
    await tick(1999);
    expect(fetchCount()).toBe(3);
    await tick(1);
    expect(fetchCount()).toBe(4);
    await tick(4999);
    expect(fetchCount()).toBe(4);
    await tick(1);
    expect(fetchCount()).toBe(5);
    await tick(5000);
    expect(fetchCount()).toBe(6);
    expect(secs()).toBeGreaterThanOrEqual(first + 14);
  });

  test('a call without an end says 진행 중 only while the turn runs', async () => {
    const list = await openTrace();
    expect(within(list).getByText('진행 중')).toBeVisible();
  });

  test('a call without an end in a finished turn says it did not finish', async () => {
    const d = done();
    d.timeline = [...d.timeline, { ...d.timeline[1], seq: 99, ms: null, output_text: '' }];
    mockTurn(d);
    const list = await openTrace();
    const row = within(list).getAllByRole('button', { name: /모델 호출 \(normal\)/ }).at(-1)!;
    expect(within(row).getByText('끝나지 않음')).toBeVisible();
    expect(within(list).queryByText('진행 중')).toBeNull();
  });

  test('paths the trace cannot record are dashed with a note and a legend entry', async () => {
    show();
    const svg = await structure();
    // SVG 툴팁은 선 묶음(g)의 <title> 이다(getByTitle 은 svg 바로 아래 title 만 찾는다).
    const notes = [...svg.querySelectorAll('.dc-edge.is-unknown > title')].map((t) => t.textContent);
    expect(notes).toEqual(['기록에 남지 않는 길', '기록에 남지 않는 길']);
    expect(screen.getByText('기록에 남지 않는 길', { selector: '.dc-legend span' })).toBeVisible();
  });

  test('assistive tech hears each node state', async () => {
    show();
    expect(await node('도구 실행')).toHaveAccessibleName(/^도구 실행, 지금, /);
    expect(await node('스킬 찾기')).toHaveAccessibleName(/^스킬 찾기, 건너뜀, /);
    expect(await node('요청 받기')).toHaveAccessibleName(/^요청 받기, 지나감, /);
    expect(await node('응답·기록')).toHaveAccessibleName(/^응답·기록, 아직, /);
  });

  test('the now node scrolls into view when the turn opens or the now node moves, not on every read', async () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    try {
      fakeClock();
      mockTurnSequence([running({ now: 'tool' }), running({ now: 'tool' }), running({ now: 'check' })]);
      show();
      await settle();
      expect(scroll).toHaveBeenCalledTimes(1);
      await tick(1000);
      expect(fetchCount()).toBe(2);
      expect(scroll).toHaveBeenCalledTimes(1);
      await tick(1000);
      expect(scroll).toHaveBeenCalledTimes(2);
      expect(scroll.mock.contexts[1]).toHaveAccessibleName(/^조건 점검, 지금/);
    } finally {
      delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView;
    }
  });

  test('params.tab opens harness tab and saves live agent config', async () => {
    render(<DevConsole windowId="w1" params={{ tab: 'harness' }} />);
    const cfg = await screen.findByRole('region', { name: '에이전트 · 하네스 실행 설정' });
    await userEvent.selectOptions(within(cfg).getByLabelText('승인 수준'), 'auto');
    const maxSteps = within(cfg).getByLabelText('ReAct 루프 단계 한도') as HTMLInputElement;
    await userEvent.clear(maxSteps);
    await userEvent.type(maxSteps, '16');
    await userEvent.click(within(cfg).getByRole('button', { name: '에이전트 설정 저장' }));
    expect(await within(cfg).findByText('에이전트 설정을 저장했습니다.')).toBeVisible();
  });

  test('loop harness tests H-LOOP-01·H-LIM-01 run as live engine checks and show a broken guard', async () => {
    render(<DevConsole windowId="w1" params={{ tab: 'harness' }} />);
    const table = await screen.findByRole('table', { name: '하네스 규칙 목록' });
    const row = (id: string) => within(table).getByText(id).closest('tr')!;
    for (const id of ['H-LOOP-01', 'H-LIM-01']) {
      await userEvent.click(within(row(id)).getByRole('button', { name: '차단 시험' }));
      const res = await within(row(id)).findByRole('status');
      expect(within(res).getByText('실엔진 검증')).toBeVisible();
      expect(within(res).getByText('차단 시험 완료')).toBeVisible();
      expect(urls()).toContain(`/api/devconsole/harness/${id}/test`);
    }

    mockHarness({ blocked: false, model_feedback: { llm_calls: 13, limit: 12 } });
    await userEvent.click(within(row('H-LIM-01')).getByRole('button', { name: '차단 시험' }));
    const res = within(row('H-LIM-01')).getByRole('status');
    expect(await within(res).findByText('차단 안 됨')).toBeVisible();
    expect(within(res).queryByText('차단 시험 완료')).toBeNull();
    expect(within(res).getByText('실엔진 검증')).toBeVisible();
  });

  test('health tab renders diagnostics and stops an active turn', async () => {
    render(<DevConsole windowId="w1" params={{ tab: 'health' }} />);
    expect(await openCheck('AI 모델 연결')).toHaveTextContent('기본 연결 및 인증 키 준비됨');
    expect(await openCheck('벡터 검색 서버')).toHaveTextContent('연결 정상 (컬렉션 1개 · 벡터 42건)');
    expect(screen.getByText('골조 지연 만회')).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: '강제 중단' }));
    await waitFor(() => expect(urls().some((u) => u === '/api/devconsole/turns/7/stop')).toBe(true));
  });

  test('registry tab shows tool stats, toggles tool state, and deletes skills', async () => {
    render(<DevConsole windowId="w1" params={{ tab: 'registry' }} />);
    expect(await screen.findByText('호출 4회 · 실패 1건')).toBeVisible();
    const toggleBtn = screen.getByRole('button', { name: 'progress.read 비활성화' });
    await userEvent.click(toggleBtn);
    await waitFor(() => expect(urls().some((u) => u.includes('/api/devconsole/tools/progress.read'))).toBe(true));
    await userEvent.click(screen.getByRole('button', { name: '월간 공정 보고 스킬 삭제' }));
    await waitFor(() => expect(screen.queryByText('월간 공정 보고')).toBeNull());
  });

  test('sources tab shows internal pipeline prompts and usage shows vision/embedding labels', async () => {
    render(<DevConsole windowId="w1" params={{ tab: 'sources' }} />);
    await userEvent.click(await screen.findByRole('button', { name: /내부 파이프라인 프롬프트/ }));
    expect(await screen.findByText('# WBS prompt body')).toBeVisible();

    mockUsage({
      rows: [
        { key: 'vision', calls: 1, input_tokens: 100, output_tokens: 20, cost: null, failed: 0 },
        { key: 'embedding', calls: 2, input_tokens: 50, output_tokens: 0, cost: null, failed: 0 },
      ],
    });
    await userEvent.click(screen.getByRole('tab', { name: '사용량·비용' }));
    await userEvent.selectOptions(await screen.findByLabelText('묶는 기준'), 'purpose');
    expect(await screen.findByText('그림 읽기')).toBeVisible();
    expect(screen.getByText('임베딩')).toBeVisible();
  });

  test('turn picker filters failed/stopped turns', async () => {
    render(<DevConsole windowId="w1" />);
    await structure();
    await userEvent.click(screen.getByRole('button', { name: /요청:/ }));
    await userEvent.click(screen.getByRole('radio', { name: '실행 중' }));
    expect(screen.getByText('골조가 4일 밀렸어. 만회 계획 세워 줘')).toBeVisible();
    expect(screen.queryByText('5층 사무동 공정표 만들어 줘')).toBeNull();
    await userEvent.click(screen.getByRole('radio', { name: '실패·중단' }));
    expect(screen.getByText('찾는 요청이 없습니다.')).toBeVisible();
  });
});

describe('연락 — 실행 추적 · 알림 연결 · 문자 사용량 (Task 108)', () => {
  /** 실행 추적 탭에서 고르기를 열고 종류를 「연락」으로. */
  async function openContacts() {
    await openTrace();
    await userEvent.click(screen.getByRole('button', { name: /^요청:/ }));
    const dialog = screen.getByRole('dialog', { name: '요청 고르기' });
    await userEvent.click(within(dialog).getByRole('radio', { name: '연락' }));
    await within(dialog).findByText('가상 담당 · 한빛전기');
    return dialog;
  }
  async function openContact() {
    const dialog = await openContacts();
    await userEvent.click(within(dialog).getByRole('button', { name: /가상 담당 · 한빛전기/ }));
    return screen.findByRole('list', { name: '실행 추적' });
  }

  test('the picker switches between turns and contacts and finds contacts by name', async () => {
    const dialog = await openContacts();
    expect(urls()).toContain('/api/devconsole/outreach?limit=30');
    expect(within(dialog).getByText('모르는 번호 010-****-0199')).toBeVisible();
    expect(within(dialog).getAllByRole('button')).toHaveLength(3);
    await userEvent.type(within(dialog).getByRole('searchbox'), '한빛');
    expect(within(dialog).getAllByRole('button')).toHaveLength(1);
    await userEvent.click(within(dialog).getByRole('radio', { name: '대화 턴' }));
    expect(within(dialog).getByText('5층 사무동 공정표 만들어 줘')).toBeVisible();
  });

  test('a picked contact shows who started it, the permission mode, the class and the state', async () => {
    await openContact();
    expect(urls()).toContain('/api/devconsole/outreach/message/501');
    const head = screen.getByRole('group', { name: '이 연락' });
    expect(head).toHaveTextContent('가상 담당 · 한빛전기');
    expect(head).toHaveTextContent('시작 에이전트');
    expect(head).toHaveTextContent('권한 위임');
    expect(head).toHaveTextContent('확인 필요 — 보냈는지 알 수 없음');
    expect(screen.getByRole('button', { name: /^연락:/ })).toHaveTextContent('가상 담당');
    expect(screen.queryByRole('group', { name: '이 요청' })).toBeNull();
  });

  test('the timeline splits attempts in order and marks the unsure result as needs-check, not failure', async () => {
    const list = await openContact();
    expect(within(list).getAllByText(/^시도 \d$/).map((e) => e.textContent)).toEqual(['시도 1', '시도 2', '시도 2', '시도 2']);
    const unsure = within(list).getByRole('button', { name: /통로 결과 — 보냈는지 확인 필요/ });
    expect(within(unsure).getByText('확인 필요', { selector: '.dc-tag' })).toBeVisible();
    expect(within(unsure).getByText('확인 필요', { selector: '.dc-c-res' })).not.toHaveClass('is-danger');
    expect(within(list).getByRole('button', { name: /근무시간/ })).toHaveTextContent('막음');
    expect(screen.getByText(/확인 필요 1건/)).toBeVisible();
    expect(within(list).getByRole('button', { name: /알 수 없는 사건/ })).toBeVisible();
  });

  test('events are grouped with counts, filtered by group and searched by code', async () => {
    const list = await openContact();
    const groups = screen.getByRole('radiogroup', { name: '사건 묶음' });
    expect(within(groups).getAllByRole('radio').map((r) => r.textContent)).toEqual([
      '전체 7', '나가는 문 판정 2', '판정 메모 1', '도구 2', '통로 결과 1', '알 수 없는 사건 1',
    ]);
    await userEvent.click(within(groups).getByRole('radio', { name: '도구 2' }));
    expect(within(list).getAllByRole('button')).toHaveLength(2);
    await userEvent.click(within(groups).getByRole('radio', { name: '전체 7' }));
    await userEvent.type(screen.getByRole('searchbox', { name: '사건 찾기' }), 'schedule_fact');
    expect(within(list).getAllByRole('button').map((b) => b.textContent)).toEqual([expect.stringContaining('도구 거절 · 일정 사실 조회')]);
  });

  test('machine output of an event opens folded', async () => {
    const list = await openContact();
    await userEvent.click(within(list).getByRole('button', { name: /통로 고르기 — 문자/ }));
    expect(within(list).getByRole('button', { name: '기계 출력 펼치기' })).toBeVisible();
    expect(within(list).queryByText('"channel_choice"')).toBeNull();
    await userEvent.click(within(list).getByRole('button', { name: '기계 출력 펼치기' }));
    expect(within(list).getByText('"channel_choice"')).toBeVisible();
  });

  test('a row with no recorded events says so, and more rows beyond the cap are marked', async () => {
    mockOutreachList([outreachRow({ kind: 'call', id: 9, channel: 'call', events: 0, needs_check: false, status: 'draft' })], true);
    mockOutreach('call', 9, outreachDetail({ head: { ...outreachRow({ kind: 'call', id: 9, channel: 'call', status: 'draft' }), approved_by: null, fail_reason: null, reply_to_id: null }, timeline: [], groups: [], attempts: 0, needs_check: 0 }));
    const dialog = await openContacts();
    expect(within(dialog).getByText(/더 오래된 기록이 있습니다/)).toBeVisible();
    await userEvent.click(within(dialog).getByRole('button', { name: /가상 담당/ }));
    expect(await screen.findByText('이 연락에는 남은 하네스 사건이 없습니다.')).toBeVisible();
  });

  test('the health tab shows the notify connection, worker times and the stored diagnosis with one failure and one needs-check', async () => {
    mockHealth({ notify: notifyHealth() });
    render(<DevConsole windowId="w1" params={{ tab: 'health' }} />);
    const card = await openCheck('문자 연결');
    expect(card).toHaveTextContent('시험 모드켬');
    expect(card).toHaveTextContent('허용 번호2개');
    expect(card).toHaveTextContent('070-****-0123');
    expect(card).toHaveTextContent('확인 필요1건');
    const worker = within(card).getByRole('group', { name: '조회 일꾼' });
    expect(worker).toHaveTextContent('돌고 있음');
    expect(worker).toHaveTextContent('받은 문자 조회아직 없음');
    const steps = within(card).getByRole('list', { name: '마지막 연결 진단' });
    const line = (id: string) => within(steps).getByText(id).closest('li')!;
    expect(within(line('P1')).getByText('정상')).toBeVisible();
    expect(within(line('P3')).getByText('확인 필요')).toBeVisible();
    expect(within(line('P4')).getByText('실패')).toBeVisible();
    expect(within(line('P2')).getByText('건너뜀')).toBeVisible();
    expect(card).toHaveTextContent('카카오톡아직 없음');
    expect(card).toHaveTextContent('AI 전화아직 없음');
    expect(fetchMock.mock.calls.some(([, init]) => (init as RequestInit | undefined)?.method === 'POST')).toBe(false);
  });

  test('the health tab says when there is no notify connection', async () => {
    mockHealth({ notify: { ...notifyHealth(), connected: false } });
    render(<DevConsole windowId="w1" params={{ tab: 'health' }} />);
    const card = await openCheck('문자 연결');
    expect(card).toHaveTextContent('알림 연결이 없습니다');
    expect(within(card).queryByRole('list', { name: '마지막 연결 진단' })).toBeNull();
  });

  test('usage shows sms and long counts and says the provider does not report the fee', async () => {
    mockUsage({ outreach: { sms: 12, long: 3, kakao: 0, auto_replies: 2, provider_cost: null } });
    await openUsage();
    const table = screen.getByRole('table', { name: '연락 사용량' });
    expect(within(table).getByRole('row', { name: /^문자 \(/ })).toHaveTextContent('12');
    expect(within(table).getByRole('row', { name: /^그 가운데 장문/ })).toHaveTextContent('3');
    expect(within(table).getByRole('row', { name: /제공사 요금/ })).toHaveTextContent('제공사가 알려 주지 않음');
  });
});
