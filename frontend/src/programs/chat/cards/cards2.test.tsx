// 묶음 2 카드(Task 39). 사건 모양은 서버 도구(backend/app/tools/**)가 내는 그대로. 사람·현장은 가상.
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { json } from '../../../test-helpers';
import { callsTo, openSpy, routes, setup } from '../testKit';
import { won } from './Card';
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
    expect(screen.getByRole('link', { name: '골조 공기 기준 (새 탭)' })).toHaveAttribute('target', '_blank');
    expect(screen.getByText('[근거 1]')).toBeVisible();
    expect(screen.getByText('웹')).toBeVisible();
    expect(screen.getByText(/example\.com/)).toBeVisible();
  });

  test('field search badge and the fallback note', () => {
    renderCard('card', { kind: 'evidence', query: '건축법 공사기간', mode: 'legal', results: [], note: '분야 검색 실패 → 웹 검색' });
    expect(screen.getByText('법령 검색')).toBeVisible(); // 검색 방식 이름표(A8)
    expect(screen.getByText('분야 검색 실패 → 웹 검색')).toBeVisible();
  });

  test('weather evidence shows the 날씨 badge', () => {
    renderCard('card', { kind: 'evidence', query: '서울 12월 평균기온', mode: 'weather', results: [] });
    expect(screen.getByText('날씨')).toBeVisible();
  });

  test('generic info-API evidence shows the 정보 API badge', () => {
    renderCard('card', { kind: 'evidence', query: '2026년 12월 공휴일', mode: 'info', results: [] });
    expect(screen.getByText('정보 API')).toBeVisible();
  });
});

describe('actual recorded', () => {
  const ACTUAL = { kind: 'actual_recorded', schedule_id: 1, activity_id: 'A2020', name: '지상 골조', progress: 0.6, assumed: ['실제 시작일을 2027-05-06로 두었습니다(계획 시작일).'], delay: { activity_id: 'A2020', late_days: 3, finish_delta: 2 }, version: 4, before_version: 3 };

  test('actual card shows assumptions and delay', async () => {
    renderCard('card', ACTUAL);
    expect(screen.getByText(/진도 60%로 넣었습니다\(자동 적용 · 버전 4\)/)).toBeVisible();
    expect(screen.getByText(/실제 시작일을 2027-05-06로 두었습니다/)).toBeVisible();
    expect(screen.getByText(/Plan보다 3일 늦어졌습니다 · 준공 \+2일/)).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: '지연 기록 열기' }));
    expect(openSpy).toHaveBeenCalledWith('delays', { id: '1', activity: 'A2020', days: '3', before: '3' });
  });

  test('an older card without before_version opens without before', async () => {
    renderCard('card', { ...ACTUAL, before_version: undefined });
    await userEvent.click(screen.getByRole('button', { name: '지연 기록 열기' }));
    expect(openSpy).toHaveBeenCalledWith('delays', { id: '1', activity: 'A2020', days: '3' });
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

  test('the recovery request button waits while the request is sent', async () => {
    renderCard('card', IMPACT);
    let done!: (ok: boolean) => void;
    sendText.mockImplementation(() => new Promise<boolean>((r) => (done = r)));
    await userEvent.click(screen.getByRole('button', { name: '만회 계획 요청' }));
    expect(screen.getByRole('button', { name: '만회 계획 요청' })).toBeDisabled();
    done(true);
    await waitFor(() => expect(screen.getByRole('button', { name: '만회 계획 요청' })).toBeEnabled());
    expect(sendText).toHaveBeenCalledTimes(1);
  });

  test('missing impact: no critical or clash lines (not 「없음」)', () => {
    renderCard('card', { ...IMPACT, impact: null });
    expect(screen.queryByText('크리티컬 변화')).toBeNull();
    expect(screen.queryByText('새 자원 겹침')).toBeNull();
  });

  test('compare asks the server for a copy with this event only', async () => {
    routes['POST /api/schedules/1/delays/scenario'] = () => json(200, { scenario_id: 7 });
    renderCard('card', IMPACT);
    await userEvent.click(screen.getByRole('button', { name: '비교판에서 보기' }));
    await waitFor(() => expect(openSpy).toHaveBeenCalledWith('compare', { id: '1', base: 'current', other: 's:7' }));
    const calls = callsTo('/api/schedules/1/delays/scenario', 'POST');
    expect(calls).toHaveLength(1);
    expect(JSON.parse(String(calls[0][1]!.body))).toEqual({ event_ids: [2] });
  });

  test('reflected delay: no recovery button, compare shows the server refusal, open the log', async () => {
    routes['POST /api/schedules/1/delays/scenario'] = () => json(422, { code: 'no_open_delays', message: '열린 지연 사건이 없습니다.', detail: null });
    renderCard('card', { ...IMPACT, status: 'reflected' });
    expect(screen.queryByRole('button', { name: '만회 계획 요청' })).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: '비교판에서 보기' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('열린 지연 사건이 없습니다.');
    expect(openSpy).not.toHaveBeenCalledWith('compare', expect.anything());
    await userEvent.click(screen.getByRole('button', { name: '지연 기록 열기' }));
    expect(openSpy).toHaveBeenCalledWith('delays', { id: '1', event: '2' });
  });

  test('won: under 10,000, 만 원, and 억', () => {
    expect(won(9_000)).toBe('9,000원');
    expect(won(9_300_000)).toBe('930만 원');
    expect(won(12_400_000)).toBe('1,240만 원');
    expect(won(120_000_000)).toBe('1억 2,000만 원');
    expect(won(100_000_000)).toBe('1억 원');
    expect(won(1_234_567_890)).toBe('12억 3,457만 원');
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

  const RULE = { scope: 'domain', domain: 'construction', text: '동절기 양생 7일 이상', kind: 'min_gap', params: {} };

  test('rule approval card does not repeat the title: only the scope', () => {
    renderCard('approval', { id: 5, title: '내 규칙 저장 — 동절기 양생 7일 이상', reasons: ['rule_save'], summary: { rule: RULE } });
    expect(screen.getByText('내 규칙 범위: 분야 전체')).toBeVisible();
    expect(screen.queryByText(/내 규칙 저장: /)).toBeNull();
  });

  test('approval card with another title shows the whole rule line', () => {
    renderCard('approval', { id: 5, title: '5층 사무동 신축 일정', reasons: ['rule_save'], summary: { rule: RULE } });
    expect(screen.getByText('내 규칙 저장: 동절기 양생 7일 이상 (분야 전체)')).toBeVisible();
  });

  test('auto applied card shows the schedule rule line', () => {
    renderCard('card', { kind: 'auto_applied', schedule_id: 1, version: 5, count: 0, summary: { changed_count: 0, rule: { ...RULE, scope: 'schedule' } } });
    expect(screen.getByText('내 규칙 저장: 동절기 양생 7일 이상 (이 일정)')).toBeVisible();
  });

  test.each(['evidence', 'actual_recorded', 'delay_impact', 'scenario_created', 'rule_saved'])('broken %s data does not throw', (kind) => {
    renderCard('card', { kind });
    expect(screen.queryByText(/보일 수 없는 카드/)).toBeNull();
  });
});

// 공정표 파일 요약 카드(Task 53 서버 사건). 제대로 된 그림은 Task 55 — 지금은 흐린 줄 대신 제목만 보이는 자리.
test('schedule file card shows its title instead of the muted unknown line', () => {
  renderCard('card', { kind: 'schedule_file', file_id: 12, sheet: '공정표', rows: 120, columns_found: ['작업명'], missing: ['기간'] });
  expect(screen.getByRole('region', { name: '공정표 파일' })).toBeVisible();
  expect(screen.queryByText(/보일 수 없는 카드/)).toBeNull();
});

// I1(재확인): 단추로 가져올 때 쓸 기본 분야·정밀도를 카드에 보인다(서버가 모델이 뺀 값을 이 값으로 채운다).
test('schedule file card shows the domain and level the import button will use', () => {
  renderCard('card', { kind: 'schedule_file', file_id: 1, sheet: null, rows: 5, columns_found: ['작업명'], missing: [], domain: 'construction', level: 'L1' });
  expect(screen.getByText('가져올 때: 분야 건설 · 정밀도 L1')).toBeVisible();
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

// 재확인 2(#45): 현장 관리자의 답으로 닫힌 새 일정 질문 카드는 닫힌 까닭을 보이고 답을 받지 않는다.
test('a closed mini question card shows why and takes no answer', () => {
  const closed = '현장 관리자는 일정을 고치거나 승인·거부할 수 없습니다.';
  renderCard('card', { kind: 'mini_questions', title: '새 프로젝트 — 분야와 범위', questions: [{ id: 'kind', question: '어떤 일정인가요?', options: [], assumption: '건설' }], closed });
  expect(screen.getByText(`닫힌 질문입니다 — ${closed}`)).toBeVisible();
  expect(screen.queryByRole('button', { name: '답 보내기' })).toBeNull();
});
