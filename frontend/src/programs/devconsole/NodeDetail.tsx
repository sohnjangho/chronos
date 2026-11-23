// 고른 칸의 상세(시안 A안 오른쪽): 하는 일 · 모델 · 이번 요청 · 들어간 것·나온 것(접힘) · 컨텍스트 구성 · 관련 설정.
import { useWindows } from '../../os/windowStore';
import Badge from '../../shared/ui/Badge';
import type { ContextPart, NodeKey, NodeState, StructureNode } from './devApi';
import { seconds, tokens } from './format';
import RawBlock from './RawBlock';

const WHAT: Record<NodeKey, string> = {
  request: '대화창에서 받은 사용자 글을 모델에게 넘깁니다. 질문지 답과 승인 거부도 글로 바꿔 넣습니다.',
  context: '지시문·분야 지식·정밀도·지금 상황·날짜 도우미·대화 기록·도구 목록을 모아 모델에게 보낼 메시지를 만듭니다.',
  skill: '맞는 스킬(순서가 정해진 작업)이 있으면 그것을 쓰고, 없으면 건너뜁니다.',
  plan: '첫 모델 호출입니다. 요청을 읽고 어떤 도구를 어떤 차례로 부를지 정합니다.',
  judge: '도구 결과를 보고 다음 도구를 부를지, 답을 낼지 정합니다. 모델 호출 한 번이 루프 한 바퀴입니다.',
  tool: '모델이 고른 도구를 등록부에서 찾아 실행합니다. 날짜·여유 같은 계산은 여기서 코드가 합니다.',
  check: '조건 점검·일정 만들기처럼 조건을 코드로 하나씩 확인하는 도구입니다. 위반이 있으면 판단 단계로 돌려보냅니다.',
  approval: '일정 변경·시나리오·내 규칙 제안을 승인함에 냅니다. 승인 수준에 따라 바로 적용하거나 사람의 승인을 기다립니다.',
  respond: '마지막 답을 대화창에 보내고 실행 기록과 추적을 닫습니다.',
};
const MODEL_NODES = new Set<NodeKey>(['plan', 'judge']);
const TOOL_NODES = new Set<NodeKey>(['tool', 'check', 'approval']);
export const STATE: Record<NodeState, { label: string; tone: 'info' | 'success' | 'neutral' }> = {
  now: { label: '지금', tone: 'info' },
  past: { label: '지나감', tone: 'success' },
  todo: { label: '아직', tone: 'neutral' },
  skipped: { label: '건너뜀', tone: 'neutral' },
};
export const CONTEXT_MS_NOTE = '재료 비중을 세려고 컨텍스트 재료를 다시 만든 시간이 더해져, 실제 조립 시간보다 깁니다.';
/** 재료 색: 아이콘 타일 토큰(두 테마 모두 있음). */
export const PART_COLORS = ['--tile-indigo-from', '--tile-blue-from', '--tile-teal-from', '--tile-green-from', '--tile-amber-from', '--tile-rose-from', '--tile-slate-from'];

export function contextParts(node: StructureNode | undefined): ContextPart[] {
  const body = node?.detail.in as { parts?: ContextPart[] } | null | undefined;
  return Array.isArray(body?.parts) ? body.parts : [];
}

function ContextMix({ parts }: { parts: ContextPart[] }) {
  const sum = parts.reduce((s, p) => s + (p.tokens ?? 0), 0);
  const known = parts.some((p) => p.tokens !== null);
  return (
    <section className="dc-mix">
      <h4>컨텍스트 구성</h4>
      <div className="dc-mix-bar" aria-hidden="true">
        {parts.map((p, i) => (
          <i key={p.name} style={{ width: `${p.share}%`, background: `var(${PART_COLORS[i % PART_COLORS.length]})` }} />
        ))}
      </div>
      <p className="dc-mix-line">
        {parts.map((p, i) => (
          <span key={p.name} title={`${p.chars.toLocaleString('ko-KR')}자`}>
            <i className="dc-sw" style={{ background: `var(${PART_COLORS[i % PART_COLORS.length]})` }} />
            {`${p.name} ${Math.round(p.share)}%`}
          </span>
        ))}
      </p>
      <p className="dc-muted">
        {known ? `합 ≈${tokens(sum)} 토큰 — 첫 모델 호출의 입력 토큰을 글자 비중으로 나눈 어림입니다.` : '토큰 수가 없어 글자 비중만 보입니다.'}
      </p>
    </section>
  );
}

function ThisTurn({ node }: { node: StructureNode }) {
  const { count, state, detail } = node;
  // 스킬 칸: 맞으면 서버가 in 에 스킬 이름을 둔다(service.py).
  if (node.key === 'skill') return <>{count > 0 && typeof detail.in === 'string' ? `적용: ${detail.in}` : '맞는 스킬 없음'}</>;
  const parts = [`${count}번`];
  if (detail.ms !== null) parts.push(node.key === 'respond' ? `요청 전체 ${seconds(detail.ms)}` : seconds(detail.ms));
  if (state === 'now') parts.push('진행 중');
  return (
    <>
      {parts.join(' · ')}
      {node.key === 'context' && detail.ms !== null && (
        <span className="dc-tag is-warn" title={CONTEXT_MS_NOTE}>
          실제보다 김
        </span>
      )}
    </>
  );
}

function Model({ node, innerCalls }: { node: StructureNode; innerCalls: number }) {
  if (MODEL_NODES.has(node.key)) return <>{node.detail.model ?? '아직 부르지 않음'}</>;
  return (
    <>
      쓰지 않음 (코드)
      {TOOL_NODES.has(node.key) && innerCalls > 0 && <span className="dc-muted">{` · 이 요청의 도구 안 모델 호출 ${innerCalls}번은 실행 추적에`}</span>}
    </>
  );
}

function Settings({ node }: { node: StructureNode }) {
  const text = node.detail.settings;
  if (!text) return null;
  return (
    <section>
      <h4>관련 설정</h4>
      <div className="dc-kv">
        <span>{text}</span>
        {node.key === 'approval' ? (
          <button type="button" className="dc-btn" onClick={() => useWindows.getState().open('settings', { section: 'approval' })}>
            설정 열기
          </button>
        ) : (
          <span className="dc-muted">코드에 정해진 값</span>
        )}
      </div>
    </section>
  );
}

export default function NodeDetail({ node, innerCalls }: { node: StructureNode; innerCalls: number }) {
  const parts = node.key === 'context' ? contextParts(node) : [];
  return (
    <aside className="dc-detail" aria-label="칸 상세">
      <header className="dc-detail-head">
        <h3>{node.label}</h3>
        <Badge tone={STATE[node.state].tone}>{STATE[node.state].label}</Badge>
      </header>
      <dl className="dc-dl">
        <div>
          <dt>하는 일</dt>
          <dd>{WHAT[node.key]}</dd>
        </div>
        <div>
          <dt>모델</dt>
          <dd>
            <Model node={node} innerCalls={innerCalls} />
          </dd>
        </div>
        <div>
          <dt>이번 요청</dt>
          <dd>
            <ThisTurn node={node} />
          </dd>
        </div>
      </dl>
      <RawBlock key={`${node.key}-in`} label="들어간 것" value={node.detail.in} />
      <RawBlock key={`${node.key}-out`} label="나온 것" value={node.detail.out} empty={node.state === 'now' ? '아직 없음 (진행 중)' : '없음'} />
      {parts.length > 0 && <ContextMix parts={parts} />}
      <Settings node={node} />
    </aside>
  );
}
