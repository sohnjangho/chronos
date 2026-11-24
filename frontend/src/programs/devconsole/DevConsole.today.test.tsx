// 11-23 에 더한 것(정보 API·근거 다시 쓰기·가져오기 단추·반복 위반 멈춤·역할 규칙)이 개발 콘솔에 보이는지.
// 예전 서버(새 칸이 없는 응답)에서도 화면이 깨지지 않는지 같이 본다.
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import DevConsole from './DevConsole';
import { done, mockCatalog, mockHealth, mockTurn, mockUsage, openCheck, setup } from './testKit';

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

const rule = (id: string, group: string, title: string, counts: [number | null, number | null] = [0, 0]) => ({
  id, group, area: '도구', title, description: `${title} 설명`, code: 'app/x.py', mode: '코드', feedback_sample: '{}',
  passed_count: counts[0], blocked_count: counts[1],
});

describe('하네스 — 묶음과 찾기', () => {
  beforeEach(() =>
    mockCatalog((c) => {
      c.harness = [
        rule('H-CPM-01', '일정 계산', '선후행 순환 차단'),
        rule('H-DATE-01', '일정 계산', '「착수 후 N주」 기한 날짜 계산', [null, null]),
        rule('H-INFO-02', '바깥 정보', '응답에 키가 되돌아와도 남기지 않음', [5, 1]),
        rule('H-ROLE-01', '권한', '현장 관리자 편집 거절'),
      ] as never;
    }),
  );

  test('rules are grouped with a header row per group, and a group chip narrows the list', async () => {
    show('harness');
    const table = await screen.findByRole('table', { name: '하네스 규칙 목록' });
    expect(within(table).getAllByRole('rowgroup').map((g) => g.getAttribute('aria-label')).filter(Boolean)).toEqual([
      '일정 계산 규칙', '바깥 정보 규칙', '권한 규칙',
    ]);
    await userEvent.click(screen.getByRole('button', { name: '권한 1' }));
    expect(within(screen.getByRole('table', { name: '하네스 규칙 목록' })).queryByText('H-CPM-01')).toBeNull();
    expect(screen.getByText('H-ROLE-01')).toBeVisible();
  });

  test('search finds a rule by its words and says so when nothing matches', async () => {
    show('harness');
    await screen.findByRole('table', { name: '하네스 규칙 목록' });
    await userEvent.type(screen.getByRole('searchbox', { name: '규칙 찾기' }), '키가');
    expect(screen.getByText('H-INFO-02')).toBeVisible();
    expect(screen.queryByText('H-CPM-01')).toBeNull();
    await userEvent.type(screen.getByRole('searchbox', { name: '규칙 찾기' }), '없는 말');
    expect(screen.getByText('찾는 규칙이 없습니다.')).toBeVisible();
  });

  test('a rule without a session record says 기록 없음 instead of a made-up count', async () => {
    show('harness');
    const table = await screen.findByRole('table', { name: '하네스 규칙 목록' });
    const row = within(table).getByText('H-DATE-01').closest('tr')!;
    expect(within(row).getByText('기록 없음')).toBeVisible();
    expect(within(row).queryByText(/통과/)).toBeNull();
    const counted = within(table).getByText('H-INFO-02').closest('tr')!;
    expect(within(counted).getByText('통과 5')).toBeVisible();
    expect(within(counted).getByText('차단 1')).toBeVisible();
  });

  test('a test result shows its observed values folded', async () => {
    show('harness');
    const table = await screen.findByRole('table', { name: '하네스 규칙 목록' });
    const row = within(table).getByText('H-INFO-02').closest('tr')!;
    await userEvent.click(within(row).getByRole('button', { name: '차단 시험' }));
    const res = await within(row).findByRole('status');
    expect(within(res).getByRole('button', { name: '관측값 펼치기' })).toBeVisible();
    expect(within(res).queryByRole('group', { name: '관측값 내용' })).toBeNull();
  });

  test('an older server (no group) still groups by area', async () => {
    mockCatalog((c) => {
      c.harness = [{ ...rule('H-LIM-01', '', '한도'), group: undefined, area: '루프' }] as never;
    });
    show('harness');
    const table = await screen.findByRole('table', { name: '하네스 규칙 목록' });
    expect(within(table).getByRole('rowgroup', { name: '에이전트 루프 규칙' })).toBeVisible();
  });
});

const tool = (name: string, category: string, mutates: boolean, roles: string[]) => ({
  name, llm_name: name.replace('.', '__'), program: null, category, enabled: true, calls: 0, failed: 0, avg_ms: null,
  description: `${name} 설명`, schema: { type: 'object' }, mutates, roles,
});

describe('도구·스킬 — 한글 이름·묶음·쓰기·역할', () => {
  beforeEach(() =>
    mockCatalog((c) => {
      c.registry.tools = [
        tool('info.call', '조회·계산·조작', true, ['admin', 'user', 'field']),
        tool('info.list', '조회·계산·조작', false, ['admin', 'user', 'field']),
        tool('out.submit_change', '승인 상신', true, ['admin', 'user']),
        tool('schedule.create_project', '조회·계산·조작', true, ['admin', 'user']),
        tool('progress.read', '조회·계산·조작', false, ['admin', 'user', 'field']),
        { ...tool('ask.questionnaire', '조회·계산·조작', false, ['admin', 'user', 'field']), field_limited: true },
      ] as never;
    }),
  );
  const table = () => screen.findByRole('table', { name: '등록된 도구 목록' });
  const row = (t: HTMLElement, id: string) => within(t).getByText(id).closest('tr')!;

  test('each tool shows its shared Korean label, write kind and the roles that may call it', async () => {
    show('registry');
    const t = await table();
    const call = row(t, 'info.call');
    expect(within(call).getByText('정보 API 조회')).toBeVisible();
    expect(within(call).getByText('쓰기')).toBeVisible();
    expect(within(call).getByText('관리자 · 사용자 · 현장 관리자')).toBeVisible();
    expect(within(row(t, 'info.list')).getByText('읽기 전용')).toBeVisible();
    const submit = row(t, 'out.submit_change');
    expect(within(submit).getByText('상신')).toBeVisible();
    expect(within(submit).getByText('관리자 · 사용자')).toBeVisible();
    expect(within(submit).getByText('현장 관리자 거절')).toBeVisible();
    const ask = row(t, 'ask.questionnaire');
    expect(within(ask).getByText('관리자 · 사용자 · 현장 관리자')).toBeVisible();
    expect(within(ask).getByText('현장 관리자 일부 거절')).toBeVisible();
    expect(within(row(t, 'info.list')).queryByText(/현장 관리자.*거절/)).toBeNull();
  });

  test('tools are grouped by area and search finds them by Korean label or id', async () => {
    show('registry');
    const t = await table();
    expect(within(t).getAllByRole('rowgroup').map((g) => g.getAttribute('aria-label')).filter(Boolean)).toEqual([
      '일정·공정 도구', '승인·규칙 상신 도구', '질문지 도구', '근거·정보 API 도구',
    ]);
    await userEvent.type(screen.getByRole('searchbox', { name: '도구 찾기' }), '정보 API');
    expect(within(await table()).queryByText('progress.read')).toBeNull();
    expect(within(await table()).getByText('info.list')).toBeVisible();
  });

  test('an older server without roles or write kind shows a dash, not a guess', async () => {
    mockCatalog((c) => {
      c.registry.tools = [{ ...tool('progress.read', '조회·계산·조작', false, []), mutates: undefined, roles: undefined }] as never;
    });
    show('registry');
    const r = row(await table(), 'progress.read');
    expect(within(r).getByText('공정률 조회')).toBeVisible();
    expect(within(r).getAllByText('—')).toHaveLength(2);
  });
});

describe('시스템 진단 — 정보 API·근거 다시 쓰기·공휴일 표·그림 읽기', () => {
  const NEW = {
    info_api: {
      status: 'warn', count: 2, message: '연결 2개 · 마지막 연결 시험 실패 1개',
      connections: [
        { id: 1, name: '공휴일 API', kind: 'generic', status: 'ok', checked_at: '2026-11-23T03:00:00Z' },
        { id: 2, name: '기상청', kind: 'kma', status: 'failed', checked_at: null },
      ],
    },
    evidence_reuse: { reusable: 4, reused_7d: 6, searches_7d: 9, days: 30 },
    holidays: { status: 'ok', years: [2026, 2027, 2028], counts: { 2026: 21, 2027: 20, 2028: 19 }, message: '달력 KR 공휴일 표: 2026·2027·2028년' },
    vision: { status: 'ok', model: 'liner-claude-router', connection_name: 'Liner 기본', stored: false, key_ready: true, message: '그림 읽기 모델 준비됨' },
  };

  test('new cards show info connections, reuse against searches, holiday years and the vision assignment', async () => {
    mockHealth(NEW);
    show('health');
    const info = await openCheck('정보 API');
    expect(within(info).getByText('공휴일 API (범용)')).toBeVisible();
    expect(within(info).getByText('기상청 (기상청 전용)').nextElementSibling).toHaveTextContent('실패 · 시험 안 함');
    const reuse = await openCheck('근거 다시 쓰기');
    expect(within(reuse).getByText('4건')).toBeVisible();
    expect(within(reuse).getByText('6회 / 9회')).toBeVisible();
    expect(within(await openCheck('공휴일 표')).getByText('2026 · 2027 · 2028')).toBeVisible();
    const vision = await openCheck('그림 읽기');
    expect(within(vision).getByText('liner-claude-router')).toBeVisible();
    expect(within(vision).getByText('기본값')).toBeVisible();
  });

  test('an older server without the new fields shows only the old cards', async () => {
    show('health');
    await screen.findByText('모두 정상');
    expect(screen.queryByRole('button', { name: /^정보 API —/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /^공휴일 표 —/ })).toBeNull();
  });
});

describe('사용량 — 따로 센 호출', () => {
  const zero = { calls: 0, input_tokens: 0, output_tokens: 0, cost: null, failed: 0 };
  async function openUsage() {
    show('usage');
    return screen.findByRole('table', { name: '사용량' });
  }

  test('info API, Liner searches against reuses, vision and embedding are counted apart with cost where recorded', async () => {
    mockUsage({
      counters: {
        info_api: { calls: 2, failed: 1 },
        weather: { calls: 1, failed: 0 },
        searches: { calls: 9, failed: 1 },
        reuses: { calls: 6 },
        vision: { ...zero, calls: 2, input_tokens: 150, output_tokens: 20, cost: 0.01, failed: 1 },
        embedding: { ...zero, calls: 1, input_tokens: 300 },
      },
    });
    await openUsage();
    const t = screen.getByRole('table', { name: '따로 센 호출' });
    const row = (name: RegExp) => within(t).getByRole('row', { name });
    expect(row(/정보 API 조회/)).toHaveTextContent('2');
    expect(within(row(/근거 다시 씀/)).getByText('6')).toBeVisible();
    expect(within(row(/근거 다시 씀/)).getByText('Liner 호출 6번 아낌')).toBeVisible();
    expect(within(row(/그림 읽기/)).getByText('$0.01')).toBeVisible();
    expect(within(row(/임베딩/)).getByText('—')).toBeVisible();
    expect(within(t).getAllByRole('rowgroup').map((g) => g.getAttribute('aria-label')).filter(Boolean)).toEqual([
      '바깥 정보', '근거 검색', '모델',
    ]);
  });

  test('an older server without counters shows only the usage table', async () => {
    await openUsage();
    expect(screen.queryByRole('table', { name: '따로 센 호출' })).toBeNull();
  });
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
