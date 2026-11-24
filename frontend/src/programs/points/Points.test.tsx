// 「관리 포인트」 창(계획 5 Task 11, 시안 B 3주 보드): 주 칸·카드·위 띠·바뀜 띠 → 카드를 누르면 자세히(여유 흐름·외부 영향·근거 문장·
// 당김 효과·담당자 연락·만회안). 현장 관리자는 읽기만. 폰은 주 하나씩. 서버는 가짜(fetch) — 회사·사람·기사는 모두 가상이다.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { useCurrentSchedule } from '../../os/currentSchedule';
import { programs, register } from '../../os/registry';
import { useDeviceMode } from '../../os/useIsMobile';
import { useUiContext } from '../../os/uiContext';
import { useWindows } from '../../os/windowStore';
import { json, signInAsDemo } from '../../test-helpers';
import manifest from './index';
import Points from './Points';
import css from './points.css?raw';
import type { AccelResult, History, PointsView } from './pointsApi';

const P = (activity_id: string, name: string, critical: boolean, tf: number, es: string, ef: string) => ({ activity_id, name, critical, tf, es, ef });

const VIEW: PointsView = {
  schedule_id: 1, version: 8, basis: { tf_days: 3, window_weeks: 3 },
  points: [
    P('A1510', '커튼월 공장 제작', false, 1, '2027-06-08', '2027-06-18'),
    P('A1210', '4층 철근 배근', true, 0, '2027-06-02', '2027-06-07'),
    P('A1500', '커튼월 제작 도면 승인', false, 1, '2027-05-27', '2027-06-04'),
    P('A1310', '5층 철근 배근', true, 0, '2027-06-15', '2027-06-19'),
  ],
  diff: { added: [P('A1510', '커튼월 공장 제작', false, 1, '2027-06-08', '2027-06-18')], removed: ['A1400'], tightened: [['A1500', 3, 1]],
    became_critical: [], before_tf: { A1510: 4 } },
  risk_status: 'done', risk_message: '',
  risks: [
    { activity_id: 'A1510', kind: 'materials', line: '알루미늄 3개월 +5.0%', as_of: '2026-10', source: 'The World Bank', status: 'ok', why: '프레임이 알루미늄 압출재' },
    { activity_id: 'A1510', kind: 'fx', line: '외장 유리 · 외부 자료 없음', as_of: null, source: null, status: 'none' },
    { activity_id: 'A1510', kind: 'weather', line: '프로젝트 주소가 없어 날씨를 보지 않음', as_of: null, source: null, status: 'skipped' },
  ],
  quotes: { 'A1510/materials': null },
  card: { new: [{ activity_id: 'A1510', responsible: ['(주)가람커튼월'] }], tightened: [] },
};

const HIST: History = {
  schedule_id: 1, version: 8, basis: { tf_days: 3, window_weeks: 3 },
  window: { data_date: '2027-06-01', weeks: [{ start: '2027-06-01', end: '2027-06-07' }, { start: '2027-06-08', end: '2027-06-14' }, { start: '2027-06-15', end: '2027-06-22' }] },
  versions: [
    { version: 8, what_if: false, saved_at: '2026-11-24T08:05:00Z', note: '도면 승인 +3일', recorded: true, count: 4, critical: 2,
      new: [{ activity_id: 'A1510', name: '커튼월 공장 제작', tf: 1, before_tf: 4 }], more: 0,
      tightened: [{ activity_id: 'A1500', name: '커튼월 제작 도면 승인', tf: 1, before_tf: 3 }],
      removed: [{ activity_id: 'A1400', name: '경량 벽체 1~3층', reason: 'out_of_window', label: '창 밖으로 밀림', before_tf: 2 }] },
    { version: 7, what_if: false, saved_at: '2026-11-20T01:00:00Z', note: 'Data Date 05.25 → 06.01', recorded: true, count: 4, critical: 2,
      new: [], more: 0, tightened: [], removed: [] },
    { version: 1, what_if: false, saved_at: '2026-11-01T01:00:00Z', note: '', recorded: false, count: 3, critical: 2, new: [], more: 0, tightened: [], removed: [] },
  ],
  preview: { version: 8, what_if: true, saved_at: '2026-11-24T08:10:00Z', note: '열린 지연을 넣은 가정', recorded: true, count: 5, critical: 3,
    new: [{ activity_id: 'A1600', name: '커튼월 자재 반입', tf: 0, became_critical: true }], more: 0, tightened: [], removed: [] },
  float: null,
};

const FLOAT = [
  { version: 6, tf: 6, critical: false, point: false },
  { version: 7, tf: 4, critical: false, point: false },
  { version: 8, tf: 1, critical: false, point: true },
];

const ACCEL: AccelResult = {
  activity_id: 'A1510', name: '커튼월 공장 제작', od_before: 9, od_after: 6, pulled_days: 3, reached_days: 0, warn: true,
  warn_line: '당긴 3일 중 0일만 준공에 반영됩니다', summary_line: '커튼월 공장 제작 3일 당김 → 준공 0일 당겨짐',
  finish_before: '2027-11-08', finish_after: '2027-11-08',
  next_chain: [{ activity_id: 'A1320', name: '5층 골조', point: true }, { activity_id: 'A1330', name: '옥탑 골조', point: false }], same_chain: true,
};

const QUOTE = { status: 'ready', message: '', error_code: null, quotes: [{ text: '“알루미늄 가격이 올랐다.”', url: 'https://example.com/a', title: '가상경제' }] };
const PEOPLE = { activity_id: 'A1510', name: '커튼월 공장 제작', people: [
  { contact_id: 7, name: '이가람', role_title: '공장장', company: '(주)가람커튼월', trade: '커튼월', do_not_contact: false, channels: ['sms', 'call'] },
  { contact_id: 8, name: '박나래', role_title: null, company: '(주)가람커튼월', trade: '커튼월', do_not_contact: true, channels: [] },
] };

let calls: { method: string; url: string; body: unknown }[];
let viewReply: () => PointsView;
let retryReply: { status: number; body: unknown };
let historyFails: number;
let accelReply: AccelResult;
let whatIfReply: (() => PointsView) | null;
let histReply: () => History;
const open = vi.fn();

beforeEach(() => {
  calls = [];
  viewReply = () => VIEW;
  historyFails = 0;
  accelReply = ACCEL;
  whatIfReply = null;
  histReply = () => HIST;
  retryReply = { status: 200, body: { ...VIEW, risk_status: 'looking', risk_message: '외부 영향 찾는 중' } };
  signInAsDemo('admin');
  open.mockReset();
  useWindows.setState({ open, setTitle: vi.fn() } as never);
  useCurrentSchedule.setState({ current: { id: 1, name: '5층 사무동 신축' } });
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? 'GET';
    calls.push({ method, url, body: init?.body ? JSON.parse(String(init.body)) : null });
    if (url === '/api/schedules') return json(200, [{ id: 1, name: '5층 사무동 신축', level: 'L3' }, { id: 2, name: '가람 물류센터', level: 'L2' }]);
    if (url === '/api/schedules/1/points') return json(200, viewReply());
    if (url === '/api/schedules/1/points/risks/retry') return json(retryReply.status, retryReply.body);
    if (url === '/api/schedules/1/points/history') {
      if (historyFails > 0) {
        historyFails -= 1;
        return json(500, { code: 'http_error', message: '잠시 뒤 다시 해 주세요.' });
      }
      return json(200, histReply());
    }
    if (url === '/api/schedules/1/points?what_if=true')
      return whatIfReply ? json(200, whatIfReply()) : json(404, { code: 'no_what_if', message: '가정 관리 포인트가 없습니다.' });
    if (url === '/api/schedules/1/points/history?activity=A1510') return json(200, { ...HIST, float: FLOAT });
    if (url === '/api/schedules/1/points/A1510/accel') return json(200, accelReply);
    if (url === '/api/schedules/1/points/A1510/quotes/materials') return json(200, QUOTE);
    if (url === '/api/schedules/1/points/A1510/contact' && method === 'GET') return json(200, PEOPLE);
    if (url === '/api/schedules/1/points/A1510/contact') {
      const body = JSON.parse(String(init!.body));
      return json(200, body.preview ? { preview: true, channel: 'sms', body: '[5층 사무동] 이가람 님, 「커튼월 공장 제작」 여유가 4일에서 1일로 줄었습니다.' }
        : { preview: false, card: { kind: 'outreach_draft', message_id: 31 } });
    }
    return json(404, { code: 'not_found', message: '찾을 수 없습니다.' });
  }));
});
afterEach(() => {
  cleanup();
  useCurrentSchedule.setState({ current: null });
  useUiContext.getState().reset();
  useDeviceMode.getState().setMode('auto');
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const show = (params?: Record<string, string>) => render(<Points windowId="w1" params={params} />);
const column = (name: string) => screen.getByRole('region', { name });
const cardNames = (name: string) => within(column(name)).queryAllByRole('button').map((b) => b.querySelector('b')?.textContent);
const detail = () => screen.getByRole('region', { name: /자세히$/ });
const posts = () => calls.filter((c) => c.method === 'POST');

test('the manifest is 관리 포인트, a work program every role sees (field managers read only)', () => {
  expect(manifest).toMatchObject({ id: 'points', name: '관리 포인트', kind: 'work', tone: 'gold' });
  expect(manifest.noField).toBeFalsy();
  register(manifest);
  expect(programs('field').map((p) => p.id)).toContain('points');
});

test('the board puts point cards in this week / next week / the week after by start date, critical vs near-critical, with a change badge', async () => {
  show();
  await screen.findByRole('region', { name: '이번 주' });
  expect(within(column('이번 주')).getByText('06.01 ~ 06.07 · 2곳')).toBeVisible();
  expect(cardNames('이번 주')).toEqual(['커튼월 제작 도면 승인', '4층 철근 배근']); // 진행 중(데이터 날짜 앞 시작)은 첫 칸, 시작일 순
  expect(cardNames('다음 주')).toEqual(['커튼월 공장 제작']);
  expect(cardNames('그다음 주')).toEqual(['5층 철근 배근']);
  expect(within(column('그다음 주')).getByText('06.15 ~ 06.22 · 1곳')).toBeVisible();
  const approval = within(column('이번 주')).getByRole('button', { name: /커튼월 제작 도면 승인/ });
  expect(approval).toHaveClass('is-near');
  expect(approval).toHaveTextContent('05.27 ~ 06.04 · 진행 중');
  expect(approval).toHaveTextContent('바뀜 3 → 1');
  expect(within(column('이번 주')).getByRole('button', { name: /4층 철근 배근/ })).toHaveClass('is-crit');
  const factory = within(column('다음 주')).getByRole('button', { name: /커튼월 공장 제작/ });
  expect(factory).toHaveTextContent('바뀜 4 → 1');
  expect(within(factory).getByRole('img', { name: '자재' })).toBeInTheDocument(); // 자료가 있는 위험 갈래만
  expect(within(factory).queryByRole('img', { name: '환율' })).toBeNull();
  expect(factory).toHaveTextContent('(주)가람커튼월'); // 담당(카드에 있을 때) — 작업 ID 는 보이지 않는다
  expect(factory).not.toHaveTextContent('A1510');
});

test('the top strip shows the schedule, version, basis (admins: a link to the dev console settings card) and the counts', async () => {
  show();
  await screen.findByRole('region', { name: '이번 주' });
  expect(screen.getByRole('combobox', { name: '일정' })).toHaveValue('1');
  expect(screen.getByText(/^버전 8 · \d\d-\d\d \d\d:\d\d$/)).toBeVisible();
  expect(screen.getByText(/여유 3일 이하/).closest('.pt-basis')).toHaveTextContent('기준 여유 3일 이하 · 앞으로 3주 (06.01 ~ 06.22)');
  expect(screen.getByText('크리티컬').closest('.pt-count')).toHaveTextContent('크리티컬 2');
  expect(screen.getByText('크리티컬 직전').closest('.pt-count')).toHaveTextContent('크리티컬 직전 2');
  expect(screen.getByText('이번에 바뀜').closest('.pt-count')).toHaveTextContent('이번에 바뀜 2');
  await userEvent.click(screen.getByRole('button', { name: '설정에서 바꾸기' })); // 관리자: 개발 콘솔의 관리 포인트 설정 카드로
  expect(open).toHaveBeenCalledWith('devconsole', { tab: 'harness', focus: 'points' });
  expect(screen.queryByText('관리자가 바꿀 수 있습니다')).toBeNull();
  expect(useWindows.getState().setTitle).toHaveBeenCalledWith('w1', '관리 포인트 — 5층 사무동 신축');
});

test('search narrows the cards by name or id', async () => {
  show();
  await screen.findByRole('region', { name: '이번 주' });
  await userEvent.type(screen.getByRole('searchbox', { name: '포인트 찾기' }), '커튼월');
  expect(screen.getByText('2 / 4곳')).toBeVisible();
  expect(cardNames('이번 주')).toEqual(['커튼월 제작 도면 승인']);
  expect(cardNames('그다음 주')).toEqual([]);
  expect(within(column('그다음 주')).getByText('이 주에 시작하는 포인트가 없습니다.')).toBeVisible();
});

test('the history strip shows the preview and versions; 모두 보기 groups every version with reasons and is searchable', async () => {
  show();
  const strip = await screen.findByRole('group', { name: '바뀜 기록' });
  expect(within(strip).getByText('미리 보기').parentElement).toHaveClass('is-whatif');
  expect(strip).toHaveTextContent('도면 승인 +3일 · 들어옴 1 · 빠짐 1 · 여유 줄어듦 1');
  expect(strip).not.toHaveTextContent('Data Date 05.25'); // 바뀜 없는 버전은 띠에 없다
  await userEvent.click(within(strip).getByRole('button', { name: '모두 보기' }));
  expect(screen.queryByRole('region', { name: '이번 주' })).toBeNull();
  const v8 = screen.getByRole('region', { name: '버전 8' });
  expect(v8).toHaveTextContent('빠짐 · 경량 벽체 1~3층 — 창 밖으로 밀림');
  expect(v8).toHaveTextContent('들어옴 · 커튼월 공장 제작 · 여유 4일 → 1일');
  expect(screen.getByRole('region', { name: '미리 보기' })).toHaveTextContent('들어옴 · 커튼월 자재 반입 · 크리티컬이 됨 · 여유 0일');
  expect(screen.getByRole('region', { name: '버전 1' })).toHaveTextContent('앞과 견준 기록이 없습니다');
  await userEvent.type(screen.getByRole('searchbox', { name: '바뀜 기록 찾기' }), '경량');
  expect(screen.getAllByRole('region').map((r) => r.getAttribute('aria-label'))).toEqual(['버전 8']);
  await userEvent.click(screen.getByRole('button', { name: '보드로' }));
  expect(screen.getByRole('region', { name: '이번 주' })).toBeVisible();
});

test('a card opens the detail: float by version, risk lines (none visible, skipped folded) and quotes only when pressed', async () => {
  show();
  await userEvent.click(await screen.findByRole('button', { name: /커튼월 공장 제작/ }));
  expect(useUiContext.getState().byWindow.w1).toEqual({ program: 'points', schedule_id: 1, selected_activity: 'A1510' });
  const d = detail();
  expect(within(d).getByRole('heading', { name: '커튼월 공장 제작' })).toBeVisible();
  expect(d).toHaveTextContent('2027.06.08 ~ 06.18');
  expect(d).toHaveTextContent('담당(주)가람커튼월');
  const flow = await within(d).findByRole('list', { name: '여유 흐름' });
  expect(within(flow).getAllByRole('listitem').map((r) => r.lastElementChild?.textContent)).toEqual(['6일', '4일', '1일']);
  expect(within(d).getByText('외장 유리 · 외부 자료 없음')).toBeVisible();
  expect(within(d).queryByText('프로젝트 주소가 없어 날씨를 보지 않음')).toBeNull();
  await userEvent.click(within(d).getByRole('button', { name: '건너뛴 자료 1개 ▸' }));
  expect(within(d).getByText('날씨 · 프로젝트 주소가 없어 날씨를 보지 않음')).toBeVisible();
  expect(posts()).toEqual([]); // 근거 문장은 누르기 전엔 찾지 않는다
  await userEvent.click(within(d).getByRole('button', { name: '근거 문장 보기' }));
  expect(await within(d).findByText('“알루미늄 가격이 올랐다.”')).toBeVisible();
  expect(posts()).toEqual([{ method: 'POST', url: '/api/schedules/1/points/A1510/quotes/materials', body: { what_if: false, retry: false } }]);
});

test('the pull result shows how the same pull did before the open delays when the server says so', async () => {
  accelReply = { ...ACCEL, before_delays_line: '열린 지연을 빼고 보면 3일 중 2일' };
  show({ activity: 'A1510' });
  const d = await screen.findByRole('region', { name: /자세히$/ });
  await userEvent.click(within(d).getByRole('button', { name: '계산' }));
  expect(await within(d).findByText('열린 지연을 빼고 보면 3일 중 2일')).toBeVisible();
});

test('「당겨도 소용 있나」 asks the server and shows the result line and the next chain', async () => {
  show({ activity: 'A1510' });
  const d = await screen.findByRole('region', { name: /자세히$/ });
  const days = within(d).getByRole('textbox', { name: '당길 날 수' });
  await userEvent.clear(days);
  expect(within(d).getByRole('button', { name: '계산' })).toBeDisabled();
  await userEvent.type(days, '3');
  await userEvent.click(within(d).getByRole('button', { name: '계산' }));
  const result = await within(d).findByRole('status');
  expect(result).toHaveTextContent('당긴 3일 중 0일만 준공에 반영됩니다');
  expect(result).toHaveTextContent('기간 9일 → 6일 · 준공 11.08 → 11.08');
  expect(result).not.toHaveTextContent('준공 반영');
  expect(result).not.toHaveTextContent('열린 지연을 빼고'); // 없으면 줄도 없다
  expect(result).toHaveTextContent('당긴 뒤에도 같은 줄이 일정을 정합니다: 5층 골조관리 포인트 → 옥탑 골조');
  expect(result.querySelector('.pt-line')).toHaveClass('is-warn');
  expect(posts()).toEqual([{ method: 'POST', url: '/api/schedules/1/points/A1510/accel', body: { days: 3 } }]);
});

test('[담당자에게 확인 연락] picks a person (no numbers), previews and makes a draft only; 만회안 asks in chat', async () => {
  show({ activity: 'A1510' });
  const d = await screen.findByRole('region', { name: /자세히$/ });
  await userEvent.click(within(d).getByRole('button', { name: '만회안 보기' }));
  expect(open).toHaveBeenCalledWith('chat', { ask: 'A1510 「커튼월 공장 제작」 일정을 지킬 만회 계획을 만들어 줘' });
  await userEvent.click(within(d).getByRole('button', { name: '담당자에게 확인 연락' }));
  const people = await within(d).findByRole('radiogroup', { name: '받는 사람' });
  expect(within(people).getByRole('radio', { name: /박나래/ })).toBeDisabled();
  await userEvent.click(within(people).getByRole('radio', { name: /이가람/ }));
  expect(await within(d).findByText(/여유가 4일에서 1일로 줄었습니다/)).toBeVisible();
  await userEvent.click(within(d).getByRole('button', { name: '초안 만들기' }));
  expect(await within(d).findByText(/문자 초안을 만들었습니다. 아직 보내지 않았습니다/)).toBeVisible();
  expect(posts().map((c) => c.body)).toEqual([
    { contact_id: 7, channel: 'sms', preview: true }, { contact_id: 7, channel: 'sms', preview: false },
  ]);
  await userEvent.click(within(d).getByRole('button', { name: '연락처에서 보기' }));
  expect(open).toHaveBeenCalledWith('contacts', { id: '1', contact: '7', tab: 'messages' });
});

test('field managers read the board and detail but have no contact action and no settings link', async () => {
  signInAsDemo('field');
  show({ activity: 'A1510' });
  const d = await screen.findByRole('region', { name: /자세히$/ });
  expect(within(d).queryByRole('button', { name: '담당자에게 확인 연락' })).toBeNull();
  expect(within(d).getByRole('button', { name: '만회안 보기' })).toBeVisible();
  expect(screen.queryByRole('button', { name: '설정에서 바꾸기' })).toBeNull(); // 값은 읽기만
  expect(screen.getByText(/여유 3일 이하/).closest('.pt-basis')).toHaveTextContent('기준 여유 3일 이하 · 앞으로 3주');
  expect(screen.getByText('관리자가 바꿀 수 있습니다')).toBeVisible();
  expect(screen.queryByRole('button', { name: '준비 상태 확인 요청' })).toBeNull(); // G 가 생길 때까지 숨김
  expect(calls.some((c) => c.url.endsWith('/contact'))).toBe(false);
});

test('on a phone the board shows one week at a time (arrows and swipe) and a card opens the detail with a way back', async () => {
  act(() => useDeviceMode.getState().setMode('phone'));
  show();
  const list = await screen.findByRole('region', { name: '이번 주 포인트' });
  expect(within(list).getAllByRole('button').map((b) => b.querySelector('b')?.textContent)).toEqual(['커튼월 제작 도면 승인', '4층 철근 배근']);
  expect(screen.getByRole('button', { name: '앞 주' })).toBeDisabled();
  await userEvent.click(screen.getByRole('button', { name: '다음 주' }));
  expect(screen.getByRole('region', { name: '다음 주 포인트' })).toHaveTextContent('커튼월 공장 제작');
  const next = screen.getByRole('region', { name: '다음 주 포인트' });
  fireEvent.touchStart(next, { touches: [{ clientX: 300 }] });
  fireEvent.touchEnd(next, { changedTouches: [{ clientX: 100 }] });
  expect(screen.getByRole('region', { name: '그다음 주 포인트' })).toHaveTextContent('5층 철근 배근');
  fireEvent.touchStart(screen.getByRole('region', { name: '그다음 주 포인트' }), { touches: [{ clientX: 100 }] });
  fireEvent.touchEnd(screen.getByRole('region', { name: '그다음 주 포인트' }), { changedTouches: [{ clientX: 300 }] });
  await userEvent.click(within(screen.getByRole('region', { name: '다음 주 포인트' })).getByRole('button', { name: /커튼월 공장 제작/ }));
  expect(screen.queryByRole('region', { name: '다음 주 포인트' })).toBeNull();
  await userEvent.click(within(detail()).getByRole('button', { name: '‹ 보드' }));
  await waitFor(() => expect(screen.getByRole('region', { name: '다음 주 포인트' })).toBeVisible());
});

test('picking another schedule reads that schedule', async () => {
  show();
  await screen.findByRole('region', { name: '이번 주' });
  await userEvent.selectOptions(screen.getByRole('combobox', { name: '일정' }), '2');
  await waitFor(() => expect(calls.some((c) => c.url.startsWith('/api/schedules/2/points'))).toBe(true));
});

test('the window never scrolls sideways: columns and the detail scroll only up and down, long names wrap', () => {
  expect(css).toMatch(/\.pt-root \{[^}]*overflow: hidden/);
  expect(css).toMatch(/\.pt-col-b \{[^}]*overflow-y: auto; overflow-x: hidden/);
  expect(css).toMatch(/\.pt-side \{[^}]*overflow-y: auto; overflow-x: hidden/);
  expect(css).toMatch(/\.pt-card-h b \{[^}]*overflow-wrap: anywhere/);
});

const gets = (url: string) => calls.filter((c) => c.method === 'GET' && c.url === url).length;

test('while risks are being looked up it re-reads only the points every 3 s, and stops after 15 minutes', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  viewReply = () => ({ ...VIEW, risk_status: 'looking', risk_message: '외부 영향 찾는 중' });
  show();
  await screen.findByRole('region', { name: '이번 주' });
  expect(gets('/api/schedules/1/points')).toBe(1);
  await act(async () => void (await vi.advanceTimersByTimeAsync(3000)));
  await waitFor(() => expect(gets('/api/schedules/1/points')).toBe(2));
  expect(gets('/api/schedules/1/points/history')).toBe(1); // 같은 버전 — 기록은 다시 읽지 않는다
  await act(async () => void (await vi.advanceTimersByTimeAsync(16 * 60_000)));
  const stopped = gets('/api/schedules/1/points');
  await act(async () => void (await vi.advanceTimersByTimeAsync(30_000)));
  expect(gets('/api/schedules/1/points')).toBe(stopped);
  expect(stopped).toBeLessThanOrEqual(2 + 15 * 20 + 1);
});

test('when polling sees a new version it stops polling and re-reads the history too; my quote state is dropped', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  viewReply = () => ({ ...VIEW, risk_status: 'looking', risk_message: '외부 영향 찾는 중' });
  show();
  await screen.findByRole('region', { name: '이번 주' });
  viewReply = () => ({ ...VIEW, version: 9, quotes: {} });
  await act(async () => void (await vi.advanceTimersByTimeAsync(3000)));
  await waitFor(() => expect(gets('/api/schedules/1/points/history')).toBe(2));
  const after = gets('/api/schedules/1/points');
  await act(async () => void (await vi.advanceTimersByTimeAsync(10_000)));
  expect(gets('/api/schedules/1/points')).toBe(after); // 새 버전은 찾는 중이 아니다 — 폴링 끝
});

test('a delay change (delaysToken) re-reads the points and the history together', async () => {
  show();
  await screen.findByRole('region', { name: '이번 주' });
  act(() => useCurrentSchedule.getState().bumpDelays());
  await waitFor(() => expect(gets('/api/schedules/1/points/history')).toBe(2));
  expect(gets('/api/schedules/1/points')).toBe(2);
});

test('a failed risk lookup shows the server message and [다시 찾기] retries only when pressed', async () => {
  viewReply = () => ({ ...VIEW, risk_status: 'failed', risk_message: '외부 영향을 찾지 못했습니다' });
  show({ activity: 'A1510' });
  const d = await screen.findByRole('region', { name: /자세히$/ });
  expect(within(d).getByRole('alert')).toHaveTextContent('외부 영향을 찾지 못했습니다');
  expect(posts()).toEqual([]);
  await userEvent.click(within(d).getByRole('button', { name: '다시 찾기' }));
  await waitFor(() => expect(within(d).queryByRole('button', { name: '다시 찾기' })).toBeNull());
  expect(posts()).toEqual([{ method: 'POST', url: '/api/schedules/1/points/risks/retry', body: { what_if: false } }]);
});

test('a refused retry shows why', async () => {
  viewReply = () => ({ ...VIEW, risk_status: 'failed', risk_message: '외부 영향을 찾지 못했습니다' });
  retryReply = { status: 409, body: { code: 'not_failed', message: '다시 찾을 것이 없습니다.' } };
  show({ activity: 'A1510' });
  const d = await screen.findByRole('region', { name: /자세히$/ });
  await userEvent.click(within(d).getByRole('button', { name: '다시 찾기' }));
  expect(await within(d).findByText('다시 찾을 것이 없습니다.')).toBeVisible();
});

const advance = async (ms: number) => act(async () => void (await vi.advanceTimersByTimeAsync(ms)));

test('after the 15-minute cap it says so with 다시 불러오기, and a new delay restarts the cap and the polling', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  viewReply = () => ({ ...VIEW, risk_status: 'looking', risk_message: '외부 영향 찾는 중' });
  show();
  await screen.findByRole('region', { name: '이번 주' });
  await advance(16 * 60_000);
  expect(await screen.findByText(/오래 걸려 다시 읽기를 멈췄습니다/)).toBeVisible();
  const stopped = gets('/api/schedules/1/points');
  await advance(10_000);
  expect(gets('/api/schedules/1/points')).toBe(stopped);
  act(() => useCurrentSchedule.getState().bumpDelays()); // 새 지연 — 새 찾기가 시작된다
  await waitFor(() => expect(gets('/api/schedules/1/points/history')).toBe(2));
  await waitFor(() => expect(screen.queryByText(/오래 걸려 다시 읽기를 멈췄습니다/)).toBeNull());
  const fresh = gets('/api/schedules/1/points');
  await advance(3000);
  await waitFor(() => expect(gets('/api/schedules/1/points')).toBe(fresh + 1)); // 상한을 새로 재서 다시 폴링
});

test('다시 불러오기 re-reads both and polls again', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  viewReply = () => ({ ...VIEW, risk_status: 'looking', risk_message: '외부 영향 찾는 중' });
  show();
  await screen.findByRole('region', { name: '이번 주' });
  await advance(16 * 60_000);
  fireEvent.click(await screen.findByRole('button', { name: '다시 불러오기' }));
  await waitFor(() => expect(gets('/api/schedules/1/points/history')).toBe(2));
  const fresh = gets('/api/schedules/1/points');
  await advance(3000);
  await waitFor(() => expect(gets('/api/schedules/1/points')).toBe(fresh + 1));
});

test('a failed re-read after a new version tries once more on the next tick, then says it could not', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  viewReply = () => ({ ...VIEW, risk_status: 'looking', risk_message: '외부 영향 찾는 중' });
  show();
  await screen.findByRole('region', { name: '이번 주' });
  viewReply = () => ({ ...VIEW, version: 9, quotes: {} });
  historyFails = 1;
  await advance(3000); // 폴링이 버전 9 를 봄 → 둘 다 다시 읽기 → 기록 실패
  await waitFor(() => expect(gets('/api/schedules/1/points/history')).toBe(2));
  await advance(3000); // 다음 차례에 한 번 더 → 성공
  await waitFor(() => expect(gets('/api/schedules/1/points/history')).toBe(3));
  expect(screen.queryByText(/다시 읽지 못했습니다/)).toBeNull();
  expect(screen.getByRole('region', { name: '이번 주' })).toBeVisible();
  historyFails = 2;
  act(() => useCurrentSchedule.getState().bumpDelays());
  await waitFor(() => expect(gets('/api/schedules/1/points/history')).toBe(4));
  await advance(3000);
  await waitFor(() => expect(gets('/api/schedules/1/points/history')).toBe(5));
  expect(await screen.findByText(/다시 읽지 못했습니다 —/)).toBeVisible();
  expect(screen.getByRole('region', { name: '이번 주' })).toBeVisible(); // 보던 보드는 그대로
});

const WHAT_IF: PointsView = {
  ...VIEW, what_if: true,
  points: [...VIEW.points, P('A1520', '커튼월 자재 반입', false, 1, '2027-06-21', '2027-06-21')],
  diff: { ...VIEW.diff!, added: [...VIEW.diff!.added, P('A1520', '커튼월 자재 반입', false, 1, '2027-06-21', '2027-06-21')], before_tf: { A1510: 4, A1520: 4 } },
};

test('with open delays the board shows the what-if points first (지연 반영 미리 보기) and can go back to the saved version', async () => {
  histReply = () => ({ ...HIST, open_delays: 2 });
  whatIfReply = () => WHAT_IF;
  show();
  await screen.findByRole('region', { name: '그다음 주' });
  expect(screen.getByText('지연 반영 미리 보기 · 열린 지연 2건')).toBeVisible();
  expect(cardNames('그다음 주')).toEqual(['5층 철근 배근', '커튼월 자재 반입']);
  expect(within(column('그다음 주')).getByRole('button', { name: /커튼월 자재 반입/ })).toHaveTextContent('바뀜 4 → 1');
  await userEvent.click(within(column('다음 주')).getByRole('button', { name: /커튼월 공장 제작/ }));
  await userEvent.click(within(detail()).getByRole('button', { name: '근거 문장 보기' }));
  await waitFor(() => expect(posts()).toEqual([{ method: 'POST', url: '/api/schedules/1/points/A1510/quotes/materials', body: { what_if: true, retry: false } }]));
  await userEvent.click(screen.getByRole('button', { name: '저장된 버전 보기' }));
  await waitFor(() => expect(cardNames('그다음 주')).toEqual(['5층 철근 배근']));
  expect(screen.queryByText(/지연 반영 미리 보기 ·/)).toBeNull();
  await userEvent.click(screen.getByRole('button', { name: '지연 반영 미리 보기로' }));
  await waitFor(() => expect(cardNames('그다음 주')).toEqual(['5층 철근 배근', '커튼월 자재 반입']));
});

test('without open delays (no preview) the board reads only the saved version', async () => {
  histReply = () => ({ ...HIST, preview: null, open_delays: 0 });
  whatIfReply = () => WHAT_IF;
  show();
  await screen.findByRole('region', { name: '그다음 주' });
  expect(cardNames('그다음 주')).toEqual(['5층 철근 배근']);
  expect(calls.some((c) => c.url.includes('what_if=true'))).toBe(false);
  expect(screen.queryByRole('button', { name: '지연 반영 미리 보기로' })).toBeNull();
});

test('risks not looked up yet (seed card): no polling, 「외부 영향을 아직 찾지 않았습니다」 and [외부 영향 찾기] only when pressed', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  viewReply = () => ({ ...VIEW, risk_status: 'not_started', risk_message: '외부 영향을 아직 찾지 않았습니다' });
  show({ activity: 'A1510' });
  const d = await screen.findByRole('region', { name: /자세히$/ });
  expect(within(d).getByText('외부 영향을 아직 찾지 않았습니다')).toBeVisible();
  const reads = gets('/api/schedules/1/points');
  await advance(10_000);
  expect(gets('/api/schedules/1/points')).toBe(reads); // 찾는 중이 아니다 — 폴링 없음
  expect(posts()).toEqual([]);
  await userEvent.click(within(d).getByRole('button', { name: '외부 영향 찾기' }));
  await waitFor(() => expect(posts()).toEqual([{ method: 'POST', url: '/api/schedules/1/points/risks/retry', body: { what_if: false } }]));
  await waitFor(() => expect(within(d).queryByRole('button', { name: '외부 영향 찾기' })).toBeNull());
});
