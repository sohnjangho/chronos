// 개발 콘솔 ⑤(Task 98): 하네스 탭의 「연락 하네스」 묶음 — 격자 · 칸 돌리기 · 가드 끄고 돌리기 · 줄/전부 돌리기 · 상한 · 받는 통화.
// 서버 응답은 모두 가짜(testKit). 칸은 서버에서 모래상자 자식 프로세스로 돈다 — 화면은 기존 차단 시험 길만 부른다.
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { json } from '../../test-helpers';
import DevConsole from './DevConsole';
import { OutreachFlow } from './TurnFlowDiagram';
import {
  callDetail,
  cellOut,
  mockCatalog,
  mockCells,
  mockHealth,
  mockUsage,
  notifyHealth,
  openCheck,
  outreachGrid,
  setup,
  urls,
  voiceHealth,
} from './testKit';

const openHarness = () => render(<DevConsole windowId="w1" params={{ tab: 'harness' }} />);
const grid = () => screen.findByRole('table', { name: '연락 하네스 격자' });
const cellOf = async (sid: string, column: string) => within(await grid()).getByRole('group', { name: `${sid} ${column}` });
const posted = () => urls().filter((u) => u.startsWith('/api/devconsole/harness/'));

beforeEach(() => {
  setup('admin');
  mockCatalog((c) => void (c.outreach_grid = outreachGrid()));
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe('연락 하네스 격자', () => {
  test('하네스 묶음에 한 묶음으로 들어가고 설계 표의 표시·아직 안 돌림·칸 말을 그린다', async () => {
    openHarness();
    const chips = await screen.findByRole('group', { name: '하네스 묶음 필터' });
    await userEvent.click(within(chips).getByRole('button', { name: /^연락 하네스/ }));
    expect(screen.queryByRole('table', { name: '하네스 규칙 목록' })).toBeNull(); // 그 묶음만
    const table = await grid();
    for (const label of ['전화 걸기', '전화 받기', '문자 받기', '우리 문자·카카오톡에 온 답']) {
      expect(within(table).getByRole('columnheader', { name: label })).toBeVisible();
    }
    expect(within(await cellOf('S-04', '전화 받기')).getByText('●')).toBeVisible();
    expect(within(await cellOf('S-21', '문자 받기')).getByText('30분 규칙')).toBeVisible();
    expect(within(table).getAllByText('—').length).toBeGreaterThanOrEqual(2);
    expect(within(await cellOf('S-04', '전화 받기')).getByText('아직 안 돌림')).toBeVisible();
    // 가짜에서만·하네스 갈라짐 칸은 운영 동작으로 읽히지 않게 표시가 붙는다 — 표시는 단추라 키보드·손가락으로 글 전체를 연다
    const sim = await cellOf('S-21', '전화 받기');
    const tag = within(sim).getByRole('button', { name: /가짜에서만/ });
    expect(tag).toHaveAttribute('aria-expanded', 'false');
    tag.focus();
    await userEvent.keyboard('{Enter}');
    expect(tag).toHaveAttribute('aria-expanded', 'true');
    expect(within(sim).getByText(/가짜 통화에서만 들린다/)).toBeVisible();
    expect(within(await cellOf('S-04', '전화 걸기')).getByText('하네스 갈라짐')).toBeVisible();
    expect(within(await cellOf('S-24', '전화 걸기')).getByText('공통 겹만')).toBeVisible();
    const only = screen.getByRole('table', { name: '채널에만 있는 것' });
    expect(within(only).getByText('음성사서함')).toBeVisible();
    expect(within(only).getByText('통화')).toBeVisible();
    expect(within(only).getByText('카카오톡')).toBeVisible();
    expect(screen.getAllByText(/대본이 적어 둔 상한/).length).toBeGreaterThan(0);
  });

  test('칸 돌리기 → 통과·실패 색, 기대마다의 결과', async () => {
    mockCells((id) => json(200, cellOut(id, id !== 'S-04@call_in')));
    openHarness();
    const ok = await cellOf('S-04', '문자 받기');
    await userEvent.click(within(ok).getByRole('button', { name: '돌리기' }));
    expect(await within(ok).findByText('통과')).toHaveClass('is-pass');
    const bad = await cellOf('S-04', '전화 받기');
    await userEvent.click(within(bad).getByRole('button', { name: '돌리기' }));
    expect(await within(bad).findByText('실패')).toHaveClass('is-fail');
    expect(posted()).toEqual(['/api/devconsole/harness/S-04@sms_in/test', '/api/devconsole/harness/S-04@call_in/test']);
    const result = screen.getByRole('region', { name: 'S-04@call_in 결과' });
    expect(within(result).getByText('그 칸의 기대')).toBeVisible();
    expect(within(result).getByText('나가는 문 판정')).toBeVisible();
  });

  test('가드 끄고 돌리기 → 무르니 실패하면 「가드 확인됨」, 물러도 통과하면 붉은 「가드 확인 안 됨」', async () => {
    mockCells((id, broken) => json(200, cellOut(id, broken ? id === 'S-04@call_in' : true, broken)));
    openHarness();
    const held = await cellOf('S-04', '문자 받기');
    await userEvent.click(within(held).getByRole('button', { name: '가드 끄고 돌리기' }));
    expect(await within(held).findByText('가드 확인됨')).toBeVisible();
    expect(posted()).toEqual(['/api/devconsole/harness/S-04@sms_in/test?broken=1']);
    const loose = await cellOf('S-04', '전화 받기');
    await userEvent.click(within(loose).getByRole('button', { name: '가드 끄고 돌리기' }));
    expect(await within(loose).findByText('가드 확인 안 됨')).toHaveClass('is-fail');
    // 지키는 곳이 없는 칸에는 그 단추가 없다
    expect(within(await cellOf('S-24', '전화 걸기')).queryByRole('button', { name: '가드 끄고 돌리기' })).toBeNull();
  });

  test('그냥 돌려도 실패하는 칸은 「가드 확인 불가」 — 초록도 빨강도 아니고 세지 않는다', async () => {
    mockCells((id, broken) => json(200, cellOut(id, false, broken, false)));
    openHarness();
    const cell = await cellOf('S-04', '전화 걸기');
    await userEvent.click(within(cell).getByRole('button', { name: '가드 끄고 돌리기' }));
    const tag = await within(cell).findByRole('button', { name: '가드 확인 불가' });
    expect(tag).not.toHaveClass('is-pass');
    expect(tag).not.toHaveClass('is-fail');
    expect(within(cell).queryByText('가드 확인됨')).toBeNull();
    expect(screen.getByRole('status', { name: '격자 진행' })).not.toHaveTextContent('가드 확인');
    const result = screen.getByRole('region', { name: 'S-04@call_out 결과' });
    expect(within(result).getByText(/그냥 돌려도 실패 — 가드를 확인할 수 없음/)).toBeVisible();
  });

  test('다시 돌리다 오류가 나면 옛 결과를 지금 결과처럼 보이지 않고 세지 않는다', async () => {
    let busy = false;
    mockCells((id) => (busy ? json(429, { code: 'sandbox_busy', message: '다른 칸을 돌리는 중입니다.', detail: null }) : json(200, cellOut(id, true))));
    openHarness();
    const cell = await cellOf('S-04', '문자 받기');
    await userEvent.click(within(cell).getByRole('button', { name: '돌리기' }));
    expect(await within(cell).findByText('통과')).toBeVisible();
    expect(screen.getByRole('status', { name: '격자 진행' })).toHaveTextContent('통과 1');
    busy = true;
    await userEvent.click(within(cell).getByRole('button', { name: '돌리기' }));
    expect(await within(cell).findByRole('button', { name: '오류' })).toHaveClass('is-fail');
    expect(within(cell).queryByText('통과')).toBeNull();
    expect(screen.getByRole('status', { name: '격자 진행' })).toHaveTextContent('통과 0');
    expect(within(screen.getByRole('region', { name: 'S-04@sms_in 결과' })).getByRole('alert')).toHaveTextContent('다른 칸을 돌리는 중입니다.');
  });

  test('줄 전체 돌리기는 그 줄의 칸만, 전부 돌리기는 하나씩 차례로(한꺼번에 하나)', async () => {
    let inFlight = 0;
    let most = 0;
    mockCells(async (id) => {
      inFlight += 1;
      most = Math.max(most, inFlight);
      await new Promise((r) => setTimeout(r, 1));
      inFlight -= 1;
      return json(200, cellOut(id, true));
    });
    openHarness();
    const row = within(await grid()).getByRole('row', { name: /S-24/ });
    await userEvent.click(within(row).getByRole('button', { name: '줄 전체 돌리기' }));
    await waitFor(() => expect(posted()).toEqual(['/api/devconsole/harness/S-24@call_out/test', '/api/devconsole/harness/S-24@sms_reply/test']));
    await userEvent.click(screen.getByRole('button', { name: '전부 돌리기' }));
    await waitFor(() => expect(screen.getByRole('status', { name: '격자 진행' })).toHaveTextContent('통과 13'));
    expect(posted()).toHaveLength(2 + 13); // 칸 10 + 채널에만 3
    expect(most).toBe(1);
  });

  test('상한은 공용 상한 칸(알림 연결 API)으로 보이고 고친다', async () => {
    openHarness();
    const box = await screen.findByRole('region', { name: '운영 상한' });
    const field = await within(box).findByRole('spinbutton', { name: /하루 문자/ });
    expect(urls()).toContain('/api/notify/connections/3/limits');
    await userEvent.clear(field);
    await userEvent.type(field, '40{Enter}');
    await waitFor(() => expect(urls().filter((u) => u === '/api/notify/connections/3/limits').length).toBeGreaterThanOrEqual(2));
    const put = vi.mocked(fetch).mock.calls.find(([u, i]) => String(u).endsWith('/limits') && i?.method === 'PUT');
    expect(JSON.parse(String(put?.[1]?.body))).toEqual({ daily_sms_total: 40 });
    expect(urls().every((u) => !u.includes('limits') || u === '/api/notify/connections/3/limits')).toBe(true);
  });

  test('기본 알림 연결이 없으면 상한 자리에 까닭만', async () => {
    mockCatalog((c) => void (c.outreach_grid = outreachGrid({ connection_id: null })));
    openHarness();
    const box = await screen.findByRole('region', { name: '운영 상한' });
    expect(within(box).getByText(/기본 알림 연결이 없어/)).toBeVisible();
    expect(urls().some((u) => u.includes('/limits'))).toBe(false);
  });

  test('격자를 읽지 못했으면 그 까닭을 보인다', async () => {
    mockCatalog((c) => void (c.outreach_grid = outreachGrid({ rows: [], channel_only: [], error: '격자 모양을 읽지 못했습니다.' })));
    openHarness();
    expect(await screen.findByText('격자 모양을 읽지 못했습니다.')).toBeVisible();
  });
});

describe('받는 통화', () => {
  test('흐름도 가지: 받은 통화 응대 · 받기 전 거절 — 기록으로만 켜짐', () => {
    const flow = callDetail().flow ?? [];
    const { rerender } = render(<OutreachFlow flow={flow} lit={['call_answered']} kind="call" direction="in" />);
    expect(screen.getByRole('listitem', { name: /받은 통화 응대, 통화가 끝남/ })).toHaveClass('is-lit');
    rerender(<OutreachFlow flow={flow} lit={['call_rejected']} kind="call" direction="in" />);
    expect(screen.getByRole('listitem', { name: /받은 통화 — 받기 전 거절, 받기 판정이 막음/ })).toHaveClass('is-lit');
    rerender(<OutreachFlow flow={flow} lit={[]} kind="call" direction="in" />);
    expect(screen.getByRole('listitem', { name: /받은 통화 응대, 기록 없음/ })).toHaveClass('is-dim');
    expect(screen.queryByText('AI 전화 걺')).toBeNull();
  });

  test('진단의 통화 일꾼 칸에 「받는 중(번호 묶임)」', async () => {
    const v = voiceHealth();
    mockHealth({ notify: notifyHealth({ voice: { ...v, worker: { ...(v.worker ?? {}), listening: true, listen_reason: null } } }) });
    render(<DevConsole windowId="w1" params={{ tab: 'health' }} />);
    const worker = within(await openCheck('AI 전화')).getByRole('group', { name: '통화 일꾼' });
    expect(within(worker).getByText('받는 중(번호 묶임)')).toBeVisible();
  });

  test('사용량에 받은 통화·거절한 통화 수', async () => {
    mockUsage({ outreach: { sms: 0, long: 0, kakao: 0, auto_replies: 0, provider_cost: null, text_models: [],
      calls: { call_seconds: 95, calls_placed: 2, models: [], calls_answered: 3, calls_rejected: 1 } } });
    render(<DevConsole windowId="w1" params={{ tab: 'usage' }} />);
    expect(await screen.findByText(/받은 통화 3통 · 받기 전 거절 1통/)).toBeVisible();
  });
});

// act 경고 없이 끝까지(전부 돌리기의 남은 약속)
afterEach(async () => {
  await act(async () => {});
});
