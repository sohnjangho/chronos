// 관리 포인트 카드·당김 효과 카드(계획 5 Task 6). 사건 모양은 서버 그대로(backend/app/points/card.py payload,
// backend/app/tools/points/accel_check.py AccelCheckOut). 사람·회사·기사는 가상이다.
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { json } from '../../../test-helpers';
import { callsTo, openSpy, routes, setup } from '../testKit';
import { CardView, type CardCtx } from './index';
import { POLL_CAP_MS, POLL_MS } from './PointsChangedCard';
import { signInAsDemo } from '../../../test-helpers';

let sendText = vi.fn<CardCtx['sendText']>();
/** 그 주소로 보낸 요청 본문들(JSON). */
const bodies = (url: string, method = 'GET') => callsTo(url, method).map(([, init]) => JSON.parse(String((init as RequestInit).body)));

function renderCard(data: Record<string, unknown>) {
  sendText = vi.fn<CardCtx['sendText']>(async () => true);
  const ctx: CardCtx = { sessionId: 1, sendText, failedQuestionnaire: null, retryResume: () => {} };
  return render(<CardView event="card" data={data} ctx={ctx} />);
}

const READY = { status: 'ready', message: '', error_code: null, quotes: [{ text: '“새솔커튼월은 2주간 압출 라인을 점검한다.”', url: 'https://example.com/n1', title: '커튼월 업계 설비 점검' }] };
const PENDING = { status: 'pending', message: '근거 문장 찾는 중', error_code: null, quotes: [] };
const FAILED = { status: 'failed', message: '근거 문장을 찾지 못했습니다', error_code: 'stale', quotes: [] };

const risk = (aid: string, kind: string, line: string, extra: Record<string, unknown> = {}) => ({
  activity_id: aid, kind, line, evidence_id: 3, as_of: '2026-10', source: 'The World Bank', status: 'ok', why: '', quote: null,
  actions: kind === 'weather' ? ['quote', 'condition'] : ['quote'], ...extra,
});

function card(over: Record<string, unknown> = {}) {
  return {
    kind: 'points_changed', schedule_id: 1, version: 8, what_if: false, basis: { tf_days: 3, window_weeks: 3 },
    new: [
      {
        activity_id: 'A1500', name: '커튼월 공장 제작', critical: false, tf: 1, es: '2027-06-03', ef: '2027-06-18', became_critical: false, before_tf: 4,
        risks: [
          risk('A1500', 'materials', '알루미늄 3개월 +5.0%', { why: '커튼월 프레임 자재' }),
          risk('A1500', 'business', '(주)새솔커튼월, 압출 설비 점검으로 출하 조정', { source: '한빛경제', as_of: '2026-11-21', quote: READY }),
          risk('A1500', 'fx', '원·달러 · 바깥 자료 없음', { status: 'none', source: null, as_of: null, evidence_id: null, actions: [], why: '수입 자재' }),
        ],
        actions: ['contact', 'recovery'],
      },
      {
        activity_id: 'A1600', name: '커튼월·외장 패널 1~3층', critical: true, tf: 0, es: '2027-06-21', ef: '2027-07-09', became_critical: true,
        risks: [risk('A1600', 'weather', '6월 강수일 평년 11일', { source: '기상청', as_of: '2026-11-24', quote: FAILED })],
        actions: ['contact', 'recovery'],
      },
    ],
    more: 0,
    tightened: [],
    removed: [
      { activity_id: 'A1400', name: '경량 벽체 1~3층', reason: 'relief', label: '여유가 늘어남', before_tf: 3, tf: 6 },
      { activity_id: 'A1450', name: '설비 배관 4층', reason: 'out_of_window', label: '창 밖으로 밀림', before_tf: 2 },
    ],
    skipped: [{ activity_id: 'A1600', name: '커튼월·외장 패널 1~3층', kind: 'materials', line: '외장 패널 · 바깥 자료를 건너뜀' }],
    skipped_count: 1,
    risk_status: 'done',
    risk_message: '',
    ...over,
  };
}

const view = (c: Record<string, unknown> | null, quotes: Record<string, unknown> = {}) => ({
  schedule_id: 1, version: 8, what_if: false, basis: { tf_days: 3, window_weeks: 3 }, points: [], risk_status: 'done', quotes, card: c,
});
const point = (name: string) => screen.getByRole('group', { name });

beforeEach(() => setup());
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('points_changed card', () => {
  test('new points show float before → after, critical badge, and omit 「여유 n일 →」 when before_tf is missing', () => {
    renderCard(card());
    expect(screen.getByRole('region', { name: '관리 포인트' })).toBeVisible();
    expect(screen.getByText('관리 포인트 2곳이 바뀌었습니다')).toBeVisible();
    expect(screen.getByText(/버전 8 · 기준: 여유 3일 이하, 앞으로 3주/)).toBeVisible();
    const a = point('커튼월 공장 제작');
    expect(within(a).getByText('크리티컬 직전')).toBeVisible();
    expect(within(a).getByText('4일')).toBeVisible();
    expect(within(a).getByText('1일')).toBeVisible();
    expect(within(a).getByText('06.03 ~ 06.18')).toBeVisible();
    const b = point('커튼월·외장 패널 1~3층');
    expect(within(b).getByText('크리티컬')).toBeVisible();
    expect(within(b).getByText(/여유/).textContent).toBe('여유 0일');
  });

  test('risk lines carry source · as-of time; none lines stay in the body without numbers or buttons', () => {
    renderCard(card());
    const a = point('커튼월 공장 제작');
    expect(within(a).getByText('알루미늄 3개월 +5.0%')).toBeVisible();
    expect(within(a).getByText('The World Bank · 2026-10')).toBeVisible();
    expect(within(a).getByText('커튼월 프레임 자재')).toBeVisible();
    const fx = within(a).getByText('원·달러 · 바깥 자료 없음').closest('li')!;
    expect(within(fx as HTMLElement).queryByRole('button')).toBeNull();
    expect(within(a).getAllByRole('button', { name: '근거 문장 보기' })).toHaveLength(2);
  });

  test('skipped sources are collapsed by default under 「건너뛴 자료 n개」', async () => {
    renderCard(card());
    const summary = screen.getByText('건너뛴 자료 1개');
    expect(summary.closest('details')).not.toHaveAttribute('open');
    expect(screen.getByText(/외장 패널 · 바깥 자료를 건너뜀/)).not.toBeVisible();
    await userEvent.click(summary);
    expect(screen.getByText(/외장 패널 · 바깥 자료를 건너뜀/)).toBeVisible();
  });

  test('removed points show the reason; only relief shows the float change', () => {
    renderCard(card());
    expect(screen.getByText('경량 벽체 1~3층 — 여유가 늘어남 (여유 3일 → 6일)')).toBeVisible();
    expect(screen.getByText('설비 배관 4층 — 창 밖으로 밀림')).toBeVisible();
  });

  test('[조건으로 넣어 보기] only on the weather line', async () => {
    renderCard(card());
    const buttons = screen.getAllByRole('button', { name: '조건으로 넣어 보기' });
    expect(buttons).toHaveLength(1);
    expect(within(point('커튼월·외장 패널 1~3층')).getByRole('button', { name: '조건으로 넣어 보기' })).toBeVisible();
    await userEvent.click(buttons[0]);
    expect(sendText).toHaveBeenCalledWith(expect.stringContaining('6월 강수일 평년 11일'));
  });

  test('polling stops on a different version: frozen 「지난 버전 카드」, no new quote search', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    routes['POST /api/schedules/1/points/A1500/quotes/materials'] = () => json(200, PENDING);
    routes['/api/schedules/1/points?what_if=false'] = { ...view(card({ version: 9 })), version: 9 };
    routes['/api/schedules/1/delays'] = { events: [] };
    renderCard(card());
    const a = point('커튼월 공장 제작');
    fireEvent.click(within(a).getAllByRole('button', { name: '근거 문장 보기' })[0]);
    expect(await screen.findByText(/근거 문장 찾는 중/)).toBeVisible();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_MS + 10);
    });
    expect(await screen.findByText('지난 버전 카드 —')).toBeVisible();
    expect(screen.getByText('지난 버전 카드라 결과를 더 읽지 않습니다.')).toBeVisible();
    const gets = () => callsTo('/api/schedules/1/points?what_if=false').length;
    const after = gets();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_MS * 3);
    });
    expect(gets()).toBe(after); // 멈춤
    const other = within(a).getByRole('button', { name: '근거 문장 보기' });
    expect(other).toBeDisabled();
    expect(other).toHaveAttribute('title', expect.stringContaining('지난 버전 카드'));
    // 지금 포인트 보기 → 지금 포인트 목록
    fireEvent.click(screen.getByRole('button', { name: '지금 포인트 보기' }));
    expect(await screen.findByRole('region', { name: '지금 관리 포인트' })).toBeVisible();
  });

  test('polling stops on 404 (the what-if is gone)', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    routes['/api/schedules/1/points?what_if=true'] = () => json(404, { code: 'no_what_if', message: '가정 관리 포인트가 없습니다.', detail: null });
    renderCard(card({ what_if: true, risk_status: 'looking', risk_message: '바깥 위험 찾는 중' }));
    expect(screen.getByText('바깥 위험 찾는 중')).toBeVisible();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_MS + 10);
    });
    expect(await screen.findByText('지난 버전 카드 —')).toBeVisible();
    expect(screen.queryByText('바깥 위험 찾는 중')).toBeNull();
    const n = callsTo('/api/schedules/1/points?what_if=true').length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_MS * 3);
    });
    expect(callsTo('/api/schedules/1/points?what_if=true')).toHaveLength(n);
  });

  test('polling stops after the time cap and skips ticks while a read is in flight', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let release = () => {};
    let hold = true;
    routes['/api/schedules/1/points?what_if=false'] = () =>
      hold ? new Promise<Response>((r) => (release = () => r(json(200, view(card({ risk_status: 'looking' })))))) : json(200, view(card({ risk_status: 'looking' })));
    renderCard(card({ risk_status: 'looking', risk_message: '바깥 위험 찾는 중' }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_MS * 4 + 10);
    });
    expect(callsTo('/api/schedules/1/points?what_if=false')).toHaveLength(1); // 앞 읽기가 안 끝나 건너뜀
    hold = false;
    await act(async () => {
      release();
      await vi.advanceTimersByTimeAsync(POLL_CAP_MS + POLL_MS);
    });
    expect(await screen.findByText('오래 걸려 다시 읽기를 멈췄습니다 —')).toBeVisible();
    const n = callsTo('/api/schedules/1/points?what_if=false').length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_MS * 3);
    });
    expect(callsTo('/api/schedules/1/points?what_if=false')).toHaveLength(n);
  });

  test('a created draft stays under its point after the chat is reopened', async () => {
    routes['/api/schedules/1/points/A1500/contact?what_if=false'] = {
      activity_id: 'A1500', name: '커튼월 공장 제작',
      people: [{ contact_id: 21, name: '최민준', role_title: '생산 관리', company: '(주)새솔커튼월', trade: '커튼월', do_not_contact: false, channels: ['sms'] }],
    };
    routes['POST /api/schedules/1/points/A1500/contact'] = (init?: RequestInit) =>
      JSON.parse(String(init?.body)).preview
        ? json(200, { preview: true, channel: 'sms', body: '다시 열어도 남는 초안' })
        : json(200, { preview: false, card: { kind: 'outreach_draft', schedule_id: 1, message_id: 78, contact: { id: 21, name: '최민준' }, channel: 'sms', body: '다시 열어도 남는 초안', body_ko: null, needs_approval: true } });
    const data = card({ version: 31 });
    const first = renderCard(data);
    await userEvent.click(within(point('커튼월 공장 제작')).getByRole('button', { name: '담당자에게 확인 연락' }));
    await userEvent.click(await screen.findByRole('radio', { name: /최민준/ }));
    await screen.findByText('다시 열어도 남는 초안');
    await userEvent.click(screen.getByRole('button', { name: '초안 만들기' }));
    expect(await screen.findByRole('region', { name: '문자 초안' })).toBeVisible();
    first.unmount();
    renderCard(data);
    expect(within(point('커튼월 공장 제작')).getByRole('region', { name: '문자 초안' })).toBeVisible();
  });

  test('[근거 문장 보기] pending → 「근거 문장 찾는 중」, then polling shows the sentence and link', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    routes['POST /api/schedules/1/points/A1500/quotes/materials'] = () => json(200, PENDING);
    routes['/api/schedules/1/points?what_if=false'] = view(card(), { 'A1500/materials': READY });
    renderCard(card());
    fireEvent.click(within(point('커튼월 공장 제작')).getAllByRole('button', { name: '근거 문장 보기' })[0]);
    expect(await screen.findByText(/근거 문장 찾는 중/)).toBeVisible();
    expect(bodies('/api/schedules/1/points/A1500/quotes/materials', 'POST')[0]).toEqual({ what_if: false, retry: false });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_MS + 10);
    });
    expect(await screen.findByText('“새솔커튼월은 2주간 압출 라인을 점검한다.”')).toBeVisible();
    expect(screen.queryByText(/근거 문장 찾는 중/)).toBeNull();
    // 폴링은 GET 만 — 근거 문장 채우기(POST)를 다시 부르지 않는다
    expect(bodies('/api/schedules/1/points/A1500/quotes/materials', 'POST')).toHaveLength(1);
  });

  test('a ready quote opens without calling the server; links open in a new tab', async () => {
    renderCard(card());
    await userEvent.click(within(point('커튼월 공장 제작')).getAllByRole('button', { name: '근거 문장 보기' })[1]);
    expect(screen.getByText('“새솔커튼월은 2주간 압출 라인을 점검한다.”')).toBeVisible();
    const link = screen.getByRole('link', { name: /커튼월 업계 설비 점검/ });
    expect(link).toHaveAttribute('href', 'https://example.com/n1');
    expect(link).toHaveAttribute('target', '_blank');
    expect(bodies('/api/schedules/1/points/A1500/quotes/business', 'POST')).toHaveLength(0);
    await userEvent.click(screen.getByRole('button', { name: '근거 문장 접기' }));
    expect(screen.queryByText('“새솔커튼월은 2주간 압출 라인을 점검한다.”')).toBeNull();
  });

  test('failed → 「근거 문장을 찾지 못했습니다」 and 「다시 찾기」 retries', async () => {
    routes['POST /api/schedules/1/points/A1600/quotes/weather'] = () => json(200, PENDING);
    renderCard(card());
    await userEvent.click(within(point('커튼월·외장 패널 1~3층')).getByRole('button', { name: '근거 문장 보기' }));
    expect(screen.getByText('근거 문장을 찾지 못했습니다.')).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: '다시 찾기' }));
    await waitFor(() => expect(bodies('/api/schedules/1/points/A1600/quotes/weather', 'POST')[0]).toEqual({ what_if: false, retry: true }));
    expect(await screen.findByText(/근거 문장 찾는 중/)).toBeVisible();
  });

  test('risk search still running → 「바깥 위험 찾는 중」, polling swaps in the finished card', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const looking = card({ risk_status: 'looking', risk_message: '바깥 위험 찾는 중', new: card().new.map((n) => ({ ...n, risks: [] })) });
    routes['/api/schedules/1/points?what_if=false'] = view(card());
    renderCard(looking);
    expect(screen.getByText('바깥 위험 찾는 중')).toBeVisible();
    expect(screen.queryByText('알루미늄 3개월 +5.0%')).toBeNull();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_MS + 10);
    });
    expect(await screen.findByText('알루미늄 3개월 +5.0%')).toBeVisible();
    expect(screen.queryByText('바깥 위험 찾는 중')).toBeNull();
  });

  test('what-if card says it is an assumption and asks the API with what_if=true', async () => {
    routes['POST /api/schedules/1/points/A1500/quotes/materials'] = () => json(200, READY);
    renderCard(card({ what_if: true }));
    expect(screen.getByText(/지연 가정\(저장 전\)/)).toBeVisible();
    await userEvent.click(within(point('커튼월 공장 제작')).getAllByRole('button', { name: '근거 문장 보기' })[0]);
    await waitFor(() => expect(bodies('/api/schedules/1/points/A1500/quotes/materials', 'POST')[0]).toEqual({ what_if: true, retry: false }));
  });

  test('[만회안 보기] asks the agent', async () => {
    renderCard(card());
    await userEvent.click(within(point('커튼월 공장 제작')).getByRole('button', { name: '만회안 보기' }));
    expect(sendText).toHaveBeenCalledWith(expect.stringContaining('커튼월 공장 제작'));
  });

  test('[담당자에게 확인 연락] → pick a contact (no numbers) → preview → draft card', async () => {
    routes['/api/schedules/1/points/A1500/contact?what_if=false'] = {
      activity_id: 'A1500', name: '커튼월 공장 제작',
      people: [
        { contact_id: 21, name: '최민준', role_title: '생산 관리', company: '(주)새솔커튼월', trade: '커튼월', do_not_contact: false, channels: ['sms', 'call'] },
        { contact_id: 22, name: '한지우', role_title: '영업', company: '(주)새솔커튼월', trade: '커튼월', do_not_contact: true, channels: [] },
      ],
    };
    const body = '[5층 사무동 신축] 최민준 님, 「커튼월 공장 제작」(06.03~06.18) 여유가 4일에서 1일로 줄었습니다. 일정대로 진행할 수 있는지 알려 주시겠어요?';
    routes['POST /api/schedules/1/points/A1500/contact'] = (init?: RequestInit) => {
      const b = JSON.parse(String(init?.body));
      if (b.preview) return json(200, b.channel === 'sms' ? { preview: true, channel: 'sms', body } : { preview: true, channel: 'call', purpose: '「커튼월 공장 제작」 일정 확인', questions: ['일정대로 마칠 수 있나요?'] });
      return json(200, { preview: false, card: { kind: 'outreach_draft', schedule_id: 1, message_id: 77, contact: { id: 21, name: '최민준', role_title: '생산 관리', company: '(주)새솔커튼월' }, channel: 'sms', body, body_ko: null, needs_approval: true } });
    };
    renderCard(card());
    await userEvent.click(within(point('커튼월 공장 제작')).getByRole('button', { name: '담당자에게 확인 연락' }));
    const picker = await screen.findByRole('group', { name: '담당자에게 확인 연락' });
    expect(within(picker).getByText(/연락처 2명 · 번호는 보이지 않습니다/)).toBeVisible();
    expect(picker.textContent).not.toMatch(/\d{3}-?\d{3,4}-?\d{4}/);
    expect(within(picker).getByRole('radio', { name: /한지우/ })).toBeDisabled();
    expect(within(picker).getByText('수신 거부')).toBeVisible();
    await userEvent.click(within(picker).getByRole('radio', { name: /최민준/ }));
    expect(await within(picker).findByText(body)).toBeVisible();
    expect(bodies('/api/schedules/1/points/A1500/contact', 'POST')[0]).toEqual({ contact_id: 21, channel: 'sms', what_if: false, preview: true });
    await userEvent.click(within(picker).getByRole('radio', { name: '전화' }));
    expect(await within(picker).findByText('일정대로 마칠 수 있나요?')).toBeVisible();
    await userEvent.click(within(picker).getByRole('radio', { name: '문자' }));
    expect(await within(picker).findByText(body)).toBeVisible();
    await userEvent.click(within(picker).getByRole('button', { name: '초안 만들기' }));
    const draft = await screen.findByRole('region', { name: '문자 초안' });
    expect(within(draft).getByText(body)).toBeVisible();
    expect(bodies('/api/schedules/1/points/A1500/contact', 'POST').at(-1)).toEqual({ contact_id: 21, channel: 'sms', what_if: false, preview: false });
    expect(screen.queryByRole('group', { name: '담당자에게 확인 연락' })).toBeNull();
  });

  test('field managers do not see the contact button (server also refuses)', () => {
    signInAsDemo('field');
    renderCard(card());
    expect(within(point('커튼월 공장 제작')).queryByRole('button', { name: '담당자에게 확인 연락' })).toBeNull();
    expect(within(point('커튼월 공장 제작')).getByRole('button', { name: '만회안 보기' })).toBeVisible();
  });

  test('contact picker shows a server refusal and 「주소록에서 다른 사람 고르기」 opens contacts', async () => {
    routes['/api/schedules/1/points/A1500/contact?what_if=false'] = () => json(403, { code: 'field_no_contacts', message: '현장 관리자는 연락처를 볼 수 없습니다.', detail: null });
    renderCard(card());
    await userEvent.click(within(point('커튼월 공장 제작')).getByRole('button', { name: '담당자에게 확인 연락' }));
    expect(await screen.findByText('현장 관리자는 연락처를 볼 수 없습니다.')).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: '주소록에서 다른 사람 고르기' }));
    expect(openSpy).toHaveBeenCalledWith('contacts', { id: '1' });
    await userEvent.click(screen.getByRole('button', { name: '취소' }));
    expect(screen.queryByRole('group', { name: '담당자에게 확인 연락' })).toBeNull();
  });

  test('Task 5 fix-round fields: delay headline, 담당, 「실외 작업」 only for construction weather-sensitive points', () => {
    const base = card();
    renderCard({
      ...base, domain: 'construction', what_if: true,
      trigger: { kind: 'delay', version: 8, delay_ids: [5, 6], latest: { id: 6, activity_id: 'A1490', name: '커튼월 제작 도면 승인', days: 3 } },
      new: [{ ...base.new[0], responsible: ['(주)새솔커튼월'] }, { ...base.new[1], responsible: ['(주)한결외장', '(주)가상실링'] }],
    });
    expect(screen.getByText('3일 지연 외 1건으로 관리 포인트 2곳이 바뀌었습니다')).toBeVisible();
    expect(screen.getByText(/커튼월 제작 도면 승인 \+3일 · 지연 가정\(저장 전\)/)).toBeVisible();
    expect(within(point('커튼월 공장 제작')).getByText('06.03 ~ 06.18 · 담당 (주)새솔커튼월')).toBeVisible();
    // 날씨 줄이 있는 포인트만(날씨는 바깥 작업일 때만 찾는다) · 건설 일정만
    expect(within(point('커튼월·외장 패널 1~3층')).getByText('06.21 ~ 07.09 · 실외 작업 · 담당 (주)한결외장, (주)가상실링')).toBeVisible();
  });

  test('「실외 작업」 is not shown outside construction; version trigger shows n-1 → n', () => {
    renderCard({ ...card(), domain: 'manufacturing', trigger: { kind: 'version', from: 7, to: 8 } });
    expect(screen.queryByText(/실외 작업/)).toBeNull();
    expect(screen.getByText(/버전 7 → 8 · 기준/)).toBeVisible();
  });

  test('failed risk search offers 「다시 찾기」 (risk_retry) and polls the new state', async () => {
    const failed = card({ risk_status: 'failed', risk_message: '바깥 위험을 찾지 못했습니다', risk_retry: true, new: card().new.map((n) => ({ ...n, risks: [] })) });
    routes['POST /api/schedules/1/points/risks/retry'] = () => json(200, view({ ...failed, risk_status: 'looking', risk_message: '바깥 위험 찾는 중', risk_retry: false }));
    renderCard(failed);
    expect(screen.getByText('바깥 위험을 찾지 못했습니다')).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: '바깥 위험 다시 찾기' }));
    expect(await screen.findByText('바깥 위험 찾는 중')).toBeVisible();
    expect(bodies('/api/schedules/1/points/risks/retry', 'POST')[0]).toEqual({ what_if: false });
    expect(screen.queryByRole('button', { name: '바깥 위험 다시 찾기' })).toBeNull();
  });

  test('tightened points are listed; buttons follow the allowed actions', () => {
    renderCard(card({
      new: [],
      tightened: [{ activity_id: 'A1700', name: '옥탑 골조', critical: false, tf: 2, es: '2027-06-10', ef: '2027-06-10', before_tf: 3, actions: [] }],
      removed: [], skipped: [], skipped_count: 0,
    }));
    expect(screen.getByText('여유가 준 포인트 1')).toBeVisible();
    const p = point('옥탑 골조');
    expect(within(p).getByText('06.10')).toBeVisible();
    expect(within(p).queryByRole('button')).toBeNull();
    expect(screen.queryByText(/건너뛴 자료/)).toBeNull();
  });
});

const ACCEL = {
  kind: 'accel_check', schedule_id: 1, activity_id: 'A1320', name: '5층 골조', od_before: 12, od_after: 7, pulled_days: 5, reached_days: 1,
  ratio: 0.2, warn: true, warn_line: '당긴 5일 중 1일만 준공에 반영됩니다', summary_line: '5층 골조 5일 당김 → 준공 1일 당겨짐',
  finish_before: '2027-10-29', finish_after: '2027-10-28',
  next_chain: [
    { activity_id: 'A1500', name: '커튼월 공장 제작', point: true },
    { activity_id: 'A1550', name: '커튼월 자재 반입', point: false },
  ],
  same_chain: false,
};

describe('accel_check card', () => {
  test('warning line, finish change, chain with point marks', () => {
    renderCard(ACCEL);
    const c = screen.getByRole('region', { name: '당김 효과' });
    expect(within(c).getByText('준공 반영 5일 중 1일')).toHaveClass('ui-badge-warning');
    expect(within(c).getByText('「5층 골조」 5일 당기면')).toBeVisible();
    expect(within(c).getByText('당긴 5일 중 1일만 준공에 반영됩니다')).toBeVisible();
    expect(within(c).getByText('−1일')).toBeVisible();
    expect(within(c).getByText(/2027\.10\.29 → 2027\.10\.28/)).toBeVisible();
    expect(within(c).getByText('남은 4일')).toBeVisible();
    const chain = within(c).getByRole('list', { name: '다음 결정 줄' });
    expect(within(chain).getByText('커튼월 공장 제작').closest('li')).toHaveClass('is-point');
    expect(within(chain).getByText('커튼월 자재 반입').closest('li')).not.toHaveClass('is-point');
  });

  test('ratio > 1 (resources mixed in) shows the numbers as they are without the warning tone', () => {
    renderCard({ ...ACCEL, pulled_days: 2, reached_days: 3, ratio: 1.5, warn: false, warn_line: null });
    const c = screen.getByRole('region', { name: '당김 효과' });
    expect(within(c).getByText('준공 반영 2일 중 3일')).not.toHaveClass('ui-badge-warning');
    expect(within(c).queryByText(/만 준공에 반영됩니다/)).toBeNull();
    expect(within(c).queryByText(/^남은/)).toBeNull();
  });

  test('same chain says so', () => {
    renderCard({ ...ACCEL, pulled_days: 3, reached_days: 3, ratio: 1, warn: false, warn_line: null, same_chain: true });
    expect(screen.getByText('당긴 뒤에도 같은 줄이 준공을 정합니다.')).toBeVisible();
  });

  test('[관리 포인트로 보기] shows the next-chain points first (highlighted), then the change card; button comes back', async () => {
    routes['/api/schedules/1/delays'] = { events: [{ status: 'reflected' }] }; // 열린 지연 없음 → 버전 포인트(가정은 묻지 않음)
    routes['/api/schedules/1/points?what_if=false'] = {
      ...view(card()),
      points: [
        { activity_id: 'A1700', name: '옥탑 골조', critical: false, tf: 3, es: '2027-06-01', ef: '2027-06-05' },
        { activity_id: 'A1500', name: '커튼월 공장 제작', critical: false, tf: 1, es: '2027-06-03', ef: '2027-06-18' },
      ],
    };
    renderCard(ACCEL);
    await userEvent.click(screen.getByRole('button', { name: '관리 포인트로 보기' }));
    const list = await screen.findByRole('list', { name: '지금 관리 포인트' });
    const items = within(list).getAllByRole('listitem');
    expect(items[0]).toHaveTextContent('커튼월 공장 제작');
    expect(items[0]).toHaveClass('pc-in-chain');
    expect(items[1]).toHaveTextContent('옥탑 골조');
    expect(items[1]).not.toHaveClass('pc-in-chain');
    expect(screen.getByText(/다음 결정 줄의 포인트 1곳 · 버전 8/)).toBeVisible();
    expect(screen.getByRole('region', { name: '관리 포인트' })).toBeVisible(); // 바뀜 카드도
    expect(callsTo('/api/schedules/1/points?what_if=true')).toHaveLength(0);
    expect(screen.getByRole('button', { name: '관리 포인트로 보기' })).toBeEnabled();
  });

  test('[관리 포인트로 보기] uses the what-if points only while a delay is open', async () => {
    routes['/api/schedules/1/delays'] = { events: [{ status: 'open' }] };
    routes['/api/schedules/1/points?what_if=true'] = {
      ...view(null), what_if: true,
      points: [{ activity_id: 'A1500', name: '커튼월 공장 제작', critical: false, tf: 1, es: '2027-06-03', ef: '2027-06-18' }],
    };
    renderCard(ACCEL);
    await userEvent.click(screen.getByRole('button', { name: '관리 포인트로 보기' }));
    const c = await screen.findByRole('region', { name: '지금 관리 포인트' });
    expect(within(c).getByText('커튼월 공장 제작')).toBeVisible();
    expect(within(c).getByText('여유 1일 · 06.03')).toBeVisible();
    expect(within(c).getByText(/지연 가정\(저장 전\)/)).toBeVisible();
    expect(screen.queryByRole('region', { name: '관리 포인트' })).toBeNull();
  });

  test('[만회안 보기] asks the agent', async () => {
    renderCard(ACCEL);
    await userEvent.click(screen.getByRole('button', { name: '만회안 보기' }));
    expect(sendText).toHaveBeenCalled();
  });
});
