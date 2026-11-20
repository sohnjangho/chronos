// 묶음 2 카드(Task 39). 사건 모양은 서버 도구(backend/app/tools/**)가 내는 그대로. 사람·현장은 가상.
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { json } from '../../../test-helpers';
import { callsTo, openSpy, routes, setup } from '../testKit';
import { CARDS, CardView, type CardCtx } from './index';

let sendText = vi.fn<CardCtx['sendText']>();

function renderCard(event: string, data: Record<string, unknown>) {
  sendText = vi.fn<CardCtx['sendText']>(async () => true);
  const ctx: CardCtx = { sessionId: 1, sendText, failedQuestionnaire: null, retryResume: () => {} };
  return render(<CardView event={event} data={data} ctx={ctx} />);
}

const opt = (key: string, id: number, recommended: boolean) => ({
  scenario_id: id,
  key,
  name: `${key}안 병행 작업`,
  finish: '2027-11-20',
  gain: 3,
  reached: key === 'B',
  moves: ['A2020 → A2030 병행(SS+5)', '골조 기간 20% 압축'],
  violations: key === 'A' ? 1 : 0,
  uncheckable: 0,
  recommended,
  note: '병행으로 크리티컬을 줄입니다.',
});
const optionRow = (key: string) => screen.getByRole('group', { name: new RegExp(`^안 ${key}`) });

beforeEach(() => setup());
afterEach(() => vi.unstubAllGlobals());

describe('evidence', () => {
  test('evidence card links open in a new tab', () => {
    renderCard('card', { kind: 'evidence', query: '층당 골조 공기', mode: 'web', results: [{ evidence_id: 1, title: '골조 공기 기준', url: 'https://example.com/a', hostname: 'example.com', date: '2026-03-01' }] });
    expect(screen.getByRole('link', { name: '골조 공기 기준' })).toHaveAttribute('target', '_blank');
    expect(screen.getByText('[근거 1]')).toBeVisible();
    expect(screen.getByText('웹')).toBeVisible();
    expect(screen.getByText(/example\.com/)).toBeVisible();
  });

  test('field search badge and the fallback note', () => {
    renderCard('card', { kind: 'evidence', query: '건축법 공사기간', mode: 'legal', results: [], note: '분야 검색 실패 → 웹 검색' });
    expect(screen.getByText('법령')).toBeVisible();
    expect(screen.getByText('분야 검색 실패 → 웹 검색')).toBeVisible();
  });
});

describe('actual recorded', () => {
  const ACTUAL = { kind: 'actual_recorded', schedule_id: 1, activity_id: 'A2020', name: '지상 골조', progress: 0.6, assumed: ['실제 시작일을 2027-05-06로 두었습니다(계획 시작일).'], delay: { activity_id: 'A2020', late_days: 3, finish_delta: 2 }, version: 4 };

  test('actual card shows assumptions and delay', async () => {
    renderCard('card', ACTUAL);
    expect(screen.getByText(/진도 60%로 넣었습니다\(자동 적용 · 버전 4\)/)).toBeVisible();
    expect(screen.getByText(/실제 시작일을 2027-05-06로 두었습니다/)).toBeVisible();
    expect(screen.getByText(/Plan보다 3일 늦어졌습니다 · 준공 \+2일/)).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: '지연 기록 열기' }));
    expect(openSpy).toHaveBeenCalledWith('delays', { id: '1', activity: 'A2020', days: '3' });
  });

  test('passes before_version as before when the card has it', async () => {
    renderCard('card', { ...ACTUAL, before_version: 3 });
    await userEvent.click(screen.getByRole('button', { name: '지연 기록 열기' }));
    expect(openSpy).toHaveBeenCalledWith('delays', { id: '1', activity: 'A2020', days: '3', before: '3' });
  });

  test('no delay, no delay line', () => {
    renderCard('card', { ...ACTUAL, delay: null });
    expect(screen.queryByText(/늦어졌습니다/)).toBeNull();
    expect(screen.queryByRole('button', { name: '지연 기록 열기' })).toBeNull();
  });
});

describe('delay impact', () => {
  const IMPACT = {
    kind: 'delay_impact', schedule_id: 1, event_id: 2, activity_id: 'A2020', name: '지상 골조', status: 'open', days: 3,
    impact: {
      applied: true, note: '', finish_before: '2027-11-24', finish_after: '2027-11-29', finish_delta: 3, absorbed: 0, milestones: [],
      critical_added: [{ id: 'A2030', name: '지붕 방수' }], critical_removed: [], affected: ['A2030'],
      new_clashes: [{ resource_id: 'crane', name: '타워크레인', first: '2027-06-02', days: 4, over: 1 }], cost: 9_300_000,
    },
    totals: {},
  };

  test('delay impact card', () => {
    renderCard('card', { kind: 'delay_impact', schedule_id: 1, event_id: 2, status: 'open', days: 3, impact: { finish_delta: 3, absorbed: 0, critical_added: [], critical_removed: [], new_clashes: [], cost: 9_300_000 } });
    expect(screen.getByText('+3일')).toBeVisible();
    expect(screen.getByText('930만 원')).toBeVisible();
    expect(screen.getByRole('button', { name: '만회 계획 요청' })).toBeVisible();
  });

  test('critical change and new clashes use the server names; recovery request goes to the chat', async () => {
    renderCard('card', IMPACT);
    expect(screen.getByText(/지붕 방수/)).toBeVisible();
    expect(screen.getByText(/타워크레인/)).toBeVisible();
    expect(screen.getByText('0일')).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: '만회 계획 요청' }));
    expect(sendText).toHaveBeenCalledWith('지연 기록을 반영한 만회 계획을 만들어 줘');
  });

  test('open delay: compare opens the delay copy the server makes', async () => {
    routes['POST /api/schedules/1/delays/scenario'] = () => json(200, { scenario_id: 7 });
    renderCard('card', IMPACT);
    await userEvent.click(screen.getByRole('button', { name: '비교판에서 보기' }));
    await waitFor(() => expect(openSpy).toHaveBeenCalledWith('compare', { id: '1', base: 'current', other: 's:7' }));
    expect(callsTo('/api/schedules/1/delays/scenario', 'POST')).toHaveLength(1);
  });

  test('reflected delay: no recovery button, compare Plan with the current version, open the log', async () => {
    renderCard('card', { ...IMPACT, status: 'reflected' });
    expect(screen.queryByRole('button', { name: '만회 계획 요청' })).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: '비교판에서 보기' }));
    expect(openSpy).toHaveBeenCalledWith('compare', { id: '1', base: 'plan', other: 'current' });
    await userEvent.click(screen.getByRole('button', { name: '지연 기록 열기' }));
    expect(openSpy).toHaveBeenCalledWith('delays', { id: '1', event: '2' });
  });
});

describe('shorten options', () => {
  test('shorten card marks the recommendation and opens compare', async () => {
    renderCard('card', { kind: 'shorten_options', schedule_id: 1, base: 's:3', options: [opt('A', 4, false), opt('B', 5, true)] });
    expect(within(optionRow('B')).getByText('추천')).toBeVisible();
    expect(within(optionRow('A')).queryByText('추천')).toBeNull();
    expect(within(optionRow('B')).getByText('−3일')).toBeVisible();
    expect(within(optionRow('A')).getByText(/위반 1/)).toBeVisible();
    await userEvent.click(within(optionRow('B')).getByRole('button', { name: '비교판에서 보기' }));
    expect(openSpy).toHaveBeenCalledWith('compare', { id: '1', base: 's:3', other: 's:5' });
  });

  test('moves are folded under 「바꾸는 것」', () => {
    renderCard('card', { kind: 'shorten_options', schedule_id: 1, base: 'current', options: [opt('A', 4, true)] });
    expect(within(optionRow('A')).getByText('바꾸는 것 2개')).toBeVisible();
    expect(within(optionRow('A')).getByText('골조 기간 20% 압축')).not.toBeVisible();
  });

  test('broken data does not throw', () => {
    renderCard('card', { kind: 'shorten_options' });
    expect(screen.queryByText(/보일 수 없는 카드/)).toBeNull();
  });
});

describe('scenario, rule and additions', () => {
  test('scenario card: name, finish, against Plan and compare', async () => {
    renderCard('card', { kind: 'scenario_created', scenario_id: 9, schedule_id: 1, name: '크레인 2대면?', summary: { finish: '2027-11-19', finish_delta: -3, plan_delta: 2, violations: [], uncheckable: 0 } });
    expect(screen.getByText('크레인 2대면?')).toBeVisible();
    expect(screen.getByText(/2027\.11\.19/)).toBeVisible();
    expect(screen.getByText('+2일')).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: '비교판에서 보기' }));
    expect(openSpy).toHaveBeenCalledWith('compare', { id: '1', base: 'current', other: 's:9' });
  });

  test('rule saved card', () => {
    renderCard('card', { kind: 'rule_saved', approval_id: 3, rule: { scope: 'domain', domain: 'construction', schedule_id: null, condition: { text: '동절기 양생 7일 이상' } } });
    expect(screen.getByText('내 규칙 저장: 동절기 양생 7일 이상 (분야 전체)')).toBeVisible();
  });

  test('result card shows evidence numbers on assumptions', () => {
    renderCard('card', { kind: 'generation_result', ok: true, finish: '2027-11-24', activity_count: 10, critical_count: 3, assumptions: [{ label: '층당 골조', value: '7일', source: '근거 검색', evidence_ids: [1, 3] }] });
    expect(screen.getByText('[근거 1]')).toBeVisible();
    expect(screen.getByText('[근거 3]')).toBeVisible();
  });

  test('approval card shows the rule to save', () => {
    renderCard('approval', { id: 5, title: '내 규칙 저장 — 동절기 양생 7일 이상', reasons: ['rule_save'], summary: { rule: { scope: 'domain', domain: 'construction', text: '동절기 양생 7일 이상', kind: 'min_gap', params: {} } } });
    expect(screen.getByText('내 규칙 저장: 동절기 양생 7일 이상 (분야 전체)')).toBeVisible();
  });

  test.each(['evidence', 'actual_recorded', 'delay_impact', 'scenario_created', 'rule_saved'])('broken %s data does not throw', (kind) => {
    renderCard('card', { kind });
    expect(screen.queryByText(/보일 수 없는 카드/)).toBeNull();
  });
});

// 서버 원본을 맥에서 직접 읽는다(vite 는 frontend 밖 파일을 import 하지 못하고, 이 저장소에는 node 형 정의가 없어 이름을 글로 넘긴다).
// Docker 의 frontend 컨테이너에는 backend 폴더가 없다 — 그때는 건너뛴다.
interface Fs {
  existsSync(p: string): boolean;
  readdirSync(p: string, o: { recursive: true }): string[];
  readFileSync(p: string, e: 'utf8'): string;
}
const fs = (await import(/* @vite-ignore */ ['node', 'fs'].join(':'))) as Fs;
// new URL(…, import.meta.url) 은 vite 가 /@fs/ 경로로 바꾸므로 글로 자른다.
const BACKEND = `${decodeURIComponent(import.meta.url.replace(/^file:\/\//, '')).split('/frontend/src/')[0]}/backend/app/`;

test.skipIf(!fs.existsSync(BACKEND))('every card kind the backend emits has a card here', () => {
  const kinds = new Set<string>();
  for (const file of fs.readdirSync(BACKEND, { recursive: true }).filter((f) => f.endsWith('.py'))) {
    const code = fs.readFileSync(BACKEND + file, 'utf8');
    if (!code.includes('AgentEvent("card"')) continue;
    for (const m of code.matchAll(/"kind":\s*"(\w+)"/g)) kinds.add(m[1]);
    for (const m of code.matchAll(/kind:\s*Literal\["(\w+)"\]/g)) kinds.add(m[1]);
  }
  expect(kinds.size).toBeGreaterThanOrEqual(11);
  const missing = [...kinds].filter((k) => !CARDS[`card:${k}`]).sort();
  expect(missing).toEqual([]);
});
