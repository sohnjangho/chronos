// 개발 콘솔 ③(Task 110): 통화 — 실행 추적의 통화 줄 · call_placed 가지 · 시스템 진단의 AI 전화 · 통화 사용량.
// 화면은 서버가 기록으로 켠 것·알려 준 숫자만 보인다. 결과를 모르는 통화는 「확인 필요」이지 실패·막음이 아니다.
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import DevConsole from './DevConsole';
import { callDetail, done, mockHealth, mockOutreach, mockOutreachList, mockTurn, mockUsage, notifyHealth, openCheck, outreachRow, setup, urls, voiceHealth } from './testKit';

const show = (tab?: string) => render(<DevConsole windowId="w1" params={tab ? { tab } : undefined} />);
const CALL = outreachRow({ kind: 'call', id: 77, channel: 'call', caller_class: 'outbound', status: 'failed', needs_check: true, contact_name: '나가상', company_name: '동해설비' });

beforeEach(() => {
  localStorage.clear();
  setup();
});
afterEach(() => {
  vi.unstubAllGlobals();
});

async function openCall(detail = callDetail()) {
  mockOutreachList([CALL]);
  mockOutreach('call', 77, detail);
  show();
  await screen.findByRole('group', { name: '에이전트 구조' });
  await userEvent.click(screen.getByRole('tab', { name: '실행 추적' }));
  await screen.findByRole('list', { name: '실행 추적' });
  await userEvent.click(screen.getByRole('button', { name: /^요청:/ }));
  const dialog = screen.getByRole('dialog', { name: '요청 고르기' });
  await userEvent.click(within(dialog).getByRole('radio', { name: '연락' }));
  const pick = await within(dialog).findByRole('button', { name: /나가상 · 동해설비/ });
  expect(pick).toHaveTextContent('확인 필요 — 걸렸는지 알 수 없음');
  expect(pick).not.toHaveTextContent('실패');
  await userEvent.click(pick);
  return screen.findByRole('group', { name: '이 연락' });
}

describe('실행 추적 — 통화', () => {
  test('the head shows starter, mode, class, status and talk time, and the transcript only as a line count', async () => {
    const head = await openCall();
    expect(head).toHaveTextContent('확인 필요 — 걸렸는지 알 수 없음');
    expect(head).toHaveTextContent('시작 에이전트');
    expect(head).toHaveTextContent('권한 위임');
    expect(head).toHaveTextContent('등급 우리가 먼저 연락');
    expect(head).toHaveTextContent('통화 1분 35초');
    expect(head).toHaveTextContent('AI 전화');
    expect(head).not.toHaveTextContent('전화 보냄');
    expect(screen.getByText('받아쓰기 12줄 — 연락처 프로그램에서 봅니다')).toBeVisible();
    expect(screen.getByText(/확인 필요 1건 — 걸렸는지\(끝났는지\) 알 수 없는 결과/)).toBeVisible();
  });

  test('the timeline runs gate → recheck → tool → silence → post-check, and the unknown end is 확인 필요, not red', async () => {
    await openCall();
    const list = screen.getByRole('list', { name: '실행 추적' });
    const names = within(list).getAllByRole('button').map((b) => b.textContent ?? '');
    const order = ['통로 고르기', '걸기 직전 재확인', '연락처 찾기', '침묵 확인', '도구 결과에 없는 날짜', '통화 결과'];
    const at = order.map((name) => names.findIndex((t) => t.includes(name)));
    expect(at.every((i) => i >= 0)).toBe(true);
    expect([...at].sort((a, b) => a - b)).toEqual(at);
    const end = within(list).getByRole('button', { name: /통화 결과 — 음성 서버 오류/ });
    expect(end).toHaveTextContent('확인 필요');
    expect(end.querySelector('.is-danger, .dc-danger')).toBeNull();
    await userEvent.click(end);
    expect(list.querySelector('.dc-error')).toBeNull(); // 펼쳐도 빨간 오류 줄이 없다
  });

  test('the call branch lights 「AI 전화 걺」 only when the server lit call_placed', async () => {
    await openCall();
    const flow = screen.getByRole('list', { name: '연락 흐름도' });
    const branch = within(flow).getByRole('listitem', { name: /^AI 전화 걺/ });
    expect(branch).toHaveAccessibleName('AI 전화 걺, 걸기 직전 재확인을 지남');
    expect(branch).toHaveClass('is-lit');
    expect(within(flow).queryByRole('listitem', { name: /^받은 문자/ })).toBeNull();
  });

  test('a call that never passed dialing keeps the branch dim', async () => {
    await openCall(callDetail({ branches_lit: [] }));
    const flow = screen.getByRole('list', { name: '연락 흐름도' });
    expect(within(flow).getByRole('listitem', { name: /^AI 전화 걺/ })).toHaveAccessibleName('AI 전화 걺, 기록 없음');
  });
});

test('an inbound call has no 「AI 전화 걺」 branch', async () => {
  const d = callDetail();
  await openCall({ ...d, head: { ...d.head, direction: 'in', origin: 'peer' }, branches_lit: [] });
  const flow = screen.getByRole('list', { name: '연락 흐름도' });
  expect(within(flow).queryByRole('listitem', { name: /^AI 전화 걺/ })).toBeNull();
});

describe('에이전트 구조 — call_placed', () => {
  test('call_placed lights the contact branch with 전화 걺', async () => {
    const d = done();
    d.structure.edges_lit = ['outreach_delegated', 'call_placed'];
    mockTurn(d);
    show();
    const svg = await screen.findByRole('group', { name: '에이전트 구조' });
    expect(within(svg).getByRole('group', { name: /^연락 가지/ })).toHaveAccessibleName('연락 가지, 위임 발송 · 전화 걺');
    expect(svg.querySelector('.dc-edge.is-outreach')).toHaveClass('is-past');
  });
});

describe('시스템 진단 — AI 전화', () => {
  test('shows the model, SDK, worker state and the stored voice diagnosis lines without calling anything', async () => {
    mockHealth({ notify: notifyHealth({ voice: voiceHealth() }) });
    show('health');
    const card = await openCheck('AI 전화');
    expect(card).toHaveTextContent('마지막 음성 진단 판정정상');
    expect(card).toHaveTextContent('구글(Gemini Live)');
    expect(card).toHaveTextContent('gemini-3.8-live');
    expect(card).toHaveTextContent('설치됨');
    const worker = within(card).getByRole('group', { name: '통화 일꾼' });
    expect(worker).toHaveTextContent('돌고 있음');
    expect(worker).toHaveTextContent('1통');
    expect(worker).toHaveTextContent('TimeoutError');
    expect(worker).toHaveTextContent('붙어 있지 않음');
    const lines = within(card).getByRole('list', { name: '마지막 음성 진단' });
    const rows = within(lines).getAllByRole('listitem');
    expect(rows.map((r) => within(r).getByText(/정상|확인 필요|실패|건너뜀/).textContent)).toEqual(['정상', '확인 필요', '실패', '건너뜀']);
    expect(within(await openCheck('문자 연결')).getByText('설정됨 — 「AI 전화」 줄')).toBeVisible();
    expect(urls().some((u) => u.includes('diagnose') || u.includes('/voice'))).toBe(false);
  });

  test('shows why the call listener is not listening and how to bring it back', async () => {
    const base = voiceHealth();
    mockHealth({ notify: notifyHealth({ voice: voiceHealth({ worker: { ...base.worker, listening: false, listen_reason: 'taken_over' } }) }) });
    show('health');
    const card = await openCheck('AI 전화');
    const worker = within(card).getByRole('group', { name: '통화 일꾼' });
    expect(worker).toHaveTextContent('붙어 있지 않음 — 다른 접속이 이 번호를 가져감');
    expect(within(card).getByRole('note')).toHaveTextContent('음성 설정을 바꾸거나, 받는 범위를 껐다 켜거나, 서버를 다시 시작하면 다시 붙습니다.');
  });

  test('no recovery hint while the listener only waits', async () => {
    const base = voiceHealth();
    mockHealth({ notify: notifyHealth({ voice: voiceHealth({ worker: { ...base.worker, listening: false, listen_reason: 'off' } }) }) });
    show('health');
    const card = await openCheck('AI 전화');
    expect(within(card).getByRole('group', { name: '통화 일꾼' })).toHaveTextContent('받는 범위가 「받지 않음」');
    expect(within(card).queryByRole('note')).toBeNull();
  });

  test('no AI 전화 card without voice settings', async () => {
    mockHealth({ notify: notifyHealth() });
    show('health');
    await openCheck('문자 연결');
    expect(screen.queryByRole('button', { name: /^AI 전화 —/ })).toBeNull();
  });
});

describe('사용량 — 통화', () => {
  test('talk time, placed calls and model usage — only reported tokens and fees, transcription only when recorded', async () => {
    mockUsage({
      outreach: {
        sms: 0, long: 0, kakao: 0, auto_replies: 0, provider_cost: null, text_models: [],
        calls: {
          call_seconds: 150, calls_placed: 2, models: [
            { kind: 'voice_model', count: 1, seconds: 120, input_tokens: 0, output_tokens: 0, cost: null },
            { kind: 'summary', count: 2, seconds: 0, input_tokens: 300, output_tokens: 70, cost: 0.001 },
          ],
        },
      },
    });
    show('usage');
    const table = await screen.findByRole('table', { name: '통화 사용량' });
    expect(screen.getByText(/통화 시간 2분 30초/)).toBeVisible();
    expect(screen.getByText(/건 통화 2통/)).toBeVisible();
    const voice = within(table).getByRole('row', { name: /^음성 모델/ });
    expect(voice).toHaveTextContent('120');
    expect(within(voice).getAllByText('알려 주지 않음')).toHaveLength(2);
    expect(within(table).getByRole('row', { name: /^통화 요약/ })).toHaveTextContent('300 · 70');
    expect(within(table).queryByRole('row', { name: /^받아쓰기/ })).toBeNull();
  });
});
