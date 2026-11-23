// 11-23 에 더한 것(정보 API·근거 다시 쓰기·가져오기 단추·반복 위반 멈춤·역할 규칙)이 개발 콘솔에 보이는지.
// 예전 서버(새 칸이 없는 응답)에서도 화면이 깨지지 않는지 같이 본다.
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import DevConsole from './DevConsole';
import { done, mockTurn, setup } from './testKit';

const structure = () => screen.findByRole('group', { name: '에이전트 구조' });
const show = (tab?: string) => render(<DevConsole windowId="w1" params={tab ? { tab } : undefined} />);
const items = (list: HTMLElement) => within(list).getAllByRole('listitem').map((li) => li.textContent);

beforeEach(() => {
  localStorage.clear();
  setup();
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe('실행 추적 — 11-23 신호', () => {
  async function traceList(d = done()) {
    mockTurn(d);
    show();
    await structure();
    await userEvent.click(screen.getByRole('tab', { name: '실행 추적' }));
    return screen.findByRole('list', { name: '실행 추적' });
  }
  const row = (list: HTMLElement, name: string) => within(list).getByRole('button', { name: new RegExp(name.replace('.', '\\.')) });

  test('a reused search is marked 저장된 근거 and a refused tool shows 거절 with its reason', async () => {
    const d = done();
    const why = '현장 관리자는 일정을 고치거나 승인·거부할 수 없습니다.';
    d.timeline = d.timeline.map((t) =>
      t.label === 'shorten.make'
        ? { ...t, label: 'evidence.search', signals: ['evidence_reused'], output_text: '{"search_id": 4, "reused": true, "results": []}' }
        : t.label === 'harness.check'
          ? { ...t, label: 'out.submit_change', ok: false, error: why, signals: ['role_blocked'] }
          : t,
    );
    const list = await traceList(d);
    expect(within(row(list, 'evidence.search')).getByText('저장된 근거')).toBeVisible();
    const refused = row(list, 'out.submit_change');
    expect(within(refused).getByText(`거절: ${why}`)).toBeVisible();
    expect(within(refused).getByText('역할 거절')).toBeVisible();
  });

  test('an info.call row shows its arguments and result as recorded (no key is ever recorded)', async () => {
    const d = done();
    const args = '{"connection_id": 2, "path": "/getRestDeInfo", "params": {"solYear": "2027"}}';
    d.timeline = d.timeline.map((t) =>
      t.label === 'shorten.make' ? { ...t, label: 'info.call', signals: ['info_used'], input_text: args, output_text: '{"ok": true, "body": "{}"}' } : t,
    );
    const list = await traceList(d);
    await userEvent.click(row(list, 'info.call'));
    expect(within(row(list, 'info.call')).getByText('정보 API')).toBeVisible();
    expect(within(list).getByText('입력 원문')).toBeVisible();
  });

  test('an older server without signals shows plain rows', async () => {
    const list = await traceList();
    expect(within(list).queryByText('저장된 근거')).toBeNull();
    expect(within(list).queryByText(/^거절:/)).toBeNull();
  });
});

describe('에이전트 구조 — 11-23 신호', () => {
  test('signals show in the signal row and as badges by the tool and check nodes', async () => {
    const d = done();
    d.structure.edges_lit = ['info_used', 'evidence_reused', 'repair_stopped', 'role_blocked', 'import_confirmed'];
    mockTurn(d);
    show();
    const svg = await structure();
    const row = screen.getByLabelText('실행된 분기 및 하네스 요약');
    expect(within(row).getByText('정보 API 조회')).toBeVisible();
    expect(within(row).getByText('같은 위반 반복 → 고치기 멈춤')).toBeVisible();
    expect(items(within(svg).getByRole('list', { name: '도구 실행 신호' }))).toEqual(['정보 API', '저장된 근거', '역할 거절']);
    expect(items(within(svg).getByRole('list', { name: '조건 점검 신호' }))).toEqual(['반복 위반 멈춤', '단추 확인']);
  });

  test('an older server without the new signals draws no signal boxes', async () => {
    show();
    const svg = await structure();
    expect(within(svg).queryByRole('list', { name: '도구 실행 신호' })).toBeNull();
    expect(within(svg).queryByRole('list', { name: '조건 점검 신호' })).toBeNull();
  });

  test('the turn flow puts each step signal beside its tool node', async () => {
    const d = done();
    d.timeline = d.timeline.map((t) => (t.label === 'shorten.make' ? { ...t, signals: ['evidence_reused'] } : t));
    mockTurn(d);
    show();
    await structure();
    await userEvent.click(screen.getByRole('button', { name: '이번 턴 실행 흐름도' }));
    const flow = screen.getByRole('group', { name: '이번 턴 실행 흐름도' });
    expect(items(within(flow).getByRole('list', { name: 'shorten.make 신호' }))).toEqual(['저장된 근거']);
    expect(within(flow).getAllByRole('list')).toHaveLength(1);
  });
});
