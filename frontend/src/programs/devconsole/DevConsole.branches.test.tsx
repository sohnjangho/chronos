// 개발 콘솔 ②(Task 109): 구조·흐름도의 연락 가지 · 연락 하나의 다섯 마디 흐름도 · 도구 목록의 연락 도구 · 글 쪽 사용량.
// 가지는 서버가 기록으로 켠 것(edges_lit·signals·branches_lit)만 켠다 — 화면이 설정으로 켜지 않는다.
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import DevConsole from './DevConsole';
import { done, harnessTool, mockCatalog, mockOutreach, mockTurn, mockUsage, outreachDetail, setup } from './testKit';

const show = (tab?: string) => render(<DevConsole windowId="w1" params={tab ? { tab } : undefined} />);
const structure = () => screen.findByRole('group', { name: '에이전트 구조' });

beforeEach(() => {
  localStorage.clear();
  setup();
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe('에이전트 구조 — 연락 가지', () => {
  test('with no recorded outreach step the contact branch is drawn dim', async () => {
    show();
    const svg = await structure();
    const box = within(svg).getByRole('group', { name: /^연락 가지/ });
    expect(box).toHaveAccessibleName('연락 가지, 기록 없음');
    expect(box.querySelector('.dc-side')).toHaveClass('is-dim');
    expect(svg.querySelector('.dc-edge.is-outreach')).toHaveClass('is-todo');
  });

  test('recorded lookup, draft and a blocked delegated send light the branch with their names', async () => {
    const d = done();
    d.structure.edges_lit = ['contact_lookup', 'outreach_draft', 'outreach_blocked'];
    mockTurn(d);
    show();
    const svg = await structure();
    const box = within(svg).getByRole('group', { name: /^연락 가지/ });
    expect(box).toHaveAccessibleName('연락 가지, 연락처 조회 · 초안 · 문이 막음');
    expect(box.querySelector('.dc-side')).toHaveClass('is-lit');
    expect(svg.querySelector('.dc-edge.is-outreach')).toHaveClass('is-past');
    expect(within(screen.getByLabelText('실행된 분기 및 하네스 요약')).getByText('위임 발송 — 문이 막음')).toBeVisible();
    // 연락 신호는 도구 실행 신호 칸에 겹쳐 그리지 않는다(연락 가지 칸이 보인다)
    expect(within(svg).queryByRole('list', { name: '도구 실행 신호' })).toBeNull();
  });

  test('an unknown result reads 결과 확인 필요 and a channel failure 보내지 못함 — neither is 문이 막음', async () => {
    const d = done();
    d.structure.edges_lit = ['outreach_unsure', 'outreach_failed'];
    mockTurn(d);
    show();
    const svg = await structure();
    const box = within(svg).getByRole('group', { name: /^연락 가지/ });
    expect(box).toHaveAccessibleName('연락 가지, 결과 확인 필요 · 보내지 못함');
    expect(box).not.toHaveAccessibleName(/문이 막음/);
    const row = screen.getByLabelText('실행된 분기 및 하네스 요약');
    expect(within(row).getByText('위임 발송 — 결과 확인 필요')).toBeVisible();
    expect(within(row).getByText('위임 발송 — 통로가 보내지 못함')).toBeVisible();
  });

  test('the turn flow puts the outreach outcome beside its tool step', async () => {
    const d = done();
    d.timeline = d.timeline.map((t) => (t.label === 'shorten.make' ? { ...t, label: 'notify.send_message', signals: ['outreach_delegated'] } : t));
    mockTurn(d);
    show();
    await structure();
    await userEvent.click(screen.getByRole('button', { name: '이번 턴 실행 흐름도' }));
    const flow = screen.getByRole('group', { name: '이번 턴 실행 흐름도' });
    const badges = within(flow).getByRole('list', { name: 'notify.send_message 신호' });
    expect(badges).toHaveTextContent('위임 발송');
  });
});

describe('연락 하나 — 다섯 마디 흐름도', () => {
  async function openContact() {
    show();
    await structure();
    await userEvent.click(screen.getByRole('tab', { name: '실행 추적' }));
    await screen.findByRole('list', { name: '실행 추적' });
    await userEvent.click(screen.getByRole('button', { name: /^요청:/ }));
    const dialog = screen.getByRole('dialog', { name: '요청 고르기' });
    await userEvent.click(within(dialog).getByRole('radio', { name: '연락' }));
    await userEvent.click(await within(dialog).findByRole('button', { name: /가상 담당 · 한빛전기/ }));
    return screen.findByRole('list', { name: '연락 흐름도' });
  }

  test('five nodes in order with each node’s event count and verdicts; the inbound branch stays dim without a record', async () => {
    const flow = await openContact();
    const nodes = within(flow).getAllByRole('listitem', { name: /사건/ });
    expect(nodes.map((n) => n.getAttribute('aria-label'))).toEqual([
      '들어오는 문, 사건 0', '도구, 사건 2', '뒤 확인, 사건 0', '나가는 문, 사건 3', '통로, 사건 1',
    ]);
    expect(nodes[1]).toHaveTextContent('지나감 1');
    expect(nodes[1]).toHaveTextContent('막음 1');
    expect(nodes[3]).toHaveClass('is-on');
    expect(nodes[0]).not.toHaveClass('is-on');
    const branch = within(flow).getByRole('listitem', { name: /^받은 문자 응대/ });
    expect(branch).toHaveAccessibleName('받은 문자 응대, 기록 없음');
    expect(branch).toHaveClass('is-dim');
  });

  test('the inbound branch lights when the server found the admit event and a linked reply', async () => {
    mockOutreach('message', 501, outreachDetail({ branches_lit: ['inbound_handled'] }));
    const flow = await openContact();
    const branch = within(flow).getByRole('listitem', { name: /^받은 문자 응대/ });
    expect(branch).toHaveAccessibleName('받은 문자 응대, 답 줄로 이어짐');
    expect(branch).toHaveClass('is-lit');
  });

  test('a refused inbound message with a linked notice reads 막고 안내함, not 응대', async () => {
    mockOutreach('message', 501, outreachDetail({ branches_lit: ['inbound_refused'] }));
    const flow = await openContact();
    const branch = within(flow).getByRole('listitem', { name: /^받은 문자/ });
    expect(branch).toHaveAccessibleName('받은 문자 — 막고 안내함, 안내 답 줄로 이어짐');
    expect(branch).toHaveClass('is-lit', 'is-warn');
    expect(within(flow).queryByRole('listitem', { name: /^받은 문자 응대/ })).toBeNull();
  });

  test('a harness tool line shows the shared Korean tool name', async () => {
    await openContact();
    const list = screen.getByRole('list', { name: '실행 추적' });
    expect(within(list).getByRole('button', { name: /도구 · 연락처 찾기/ })).toBeVisible();
    expect(within(list).getByRole('button', { name: /도구 거절 · 일정 사실 조회/ })).toBeVisible();
  });
});

describe('도구 목록 — 연락 도구', () => {
  beforeEach(() =>
    mockCatalog((c) => {
      c.registry.tools.push(
        {
          name: 'contacts.list', llm_name: 'contacts__list', program: 'contacts', category: '조회·계산·조작', enabled: true,
          calls: 0, failed: 0, avg_ms: null, description: '연락처를 찾는다.', schema: {}, roles: ['admin', 'user'],
          role_note: '관리자·사용자 — 현장 관리자 불가',
        } as never,
        harnessTool('schedule_fact', ['internal', 'contact', 'contact_multi', 'shared', 'outbound'], ['sms', 'call']) as never,
        harnessTool('end_call', ['internal', 'contact', 'unknown', 'outbound'], ['call']) as never,
      );
    }),
  );

  test('the harness chip narrows to the contact harness tools, which have no switch and show classes, media and role', async () => {
    show('registry');
    const table = await screen.findByRole('table', { name: '등록된 도구 목록' });
    await userEvent.click(screen.getByRole('button', { name: '연락 하네스 도구' }));
    const rows = within(table).getAllByRole('row').filter((r) => r.classList.contains('dc-cat-row'));
    expect(rows).toHaveLength(2);
    const fact = rows.find((r) => r.textContent?.includes('outreach.schedule_fact'))!;
    expect(fact).toHaveTextContent('일정 사실 조회');
    expect(fact).toHaveTextContent('음성·글 에이전트 — 사람이 직접 부르지 않음');
    expect(fact).toHaveTextContent('문자·통화');
    expect(fact).toHaveTextContent('내부 · 연락처');
    expect(fact).not.toHaveTextContent('모르는 번호');
    expect(within(fact).queryByRole('button', { name: /비활성화/ })).toBeNull();
    expect(fact).toHaveTextContent('끄기 없음');
    const end = rows.find((r) => r.textContent?.includes('outreach.end_call'))!;
    expect(end).toHaveTextContent('통화만');
  });

  test('a chat-agent contact tool shows its role note and is grouped under 연락', async () => {
    show('registry');
    await screen.findByRole('table', { name: '등록된 도구 목록' });
    await userEvent.type(screen.getByRole('searchbox', { name: '도구 찾기' }), '연락처 조회');
    const group = screen.getByRole('rowgroup', { name: '연락 도구' });
    expect(group).toHaveTextContent('관리자·사용자 — 현장 관리자 불가');
    expect(within(group).getByRole('button', { name: /contacts.list 비활성화/ })).toBeVisible();
  });
});

describe('사용량 — 글 쪽 모델', () => {
  test('auto replies and the text-side model usage show counts, tokens and only the fee the model reported', async () => {
    mockUsage({
      outreach: {
        sms: 4, long: 0, kakao: 0, auto_replies: 2, provider_cost: null,
        text_models: [
          { kind: 'text_reply', count: 3, input_tokens: 1200, output_tokens: 300, cost: 0.004 },
          { kind: 'draft', count: 0, input_tokens: 0, output_tokens: 0, cost: null },
          { kind: 'translation', count: 1, input_tokens: 90, output_tokens: 40, cost: null },
        ],
      },
    });
    show('usage');
    const table = await screen.findByRole('table', { name: '연락 글 모델 사용량' });
    expect(within(table).getByRole('row', { name: /^문자 답/ })).toHaveTextContent('3');
    expect(within(table).getByRole('row', { name: /^문자 답/ })).toHaveTextContent('1,200');
    expect(within(table).getByRole('row', { name: /^번역/ })).toHaveTextContent('알려 주지 않음');
    expect(within(screen.getByRole('table', { name: '연락 사용량' })).getByRole('row', { name: /^자동 답/ })).toHaveTextContent('2');
  });
});
