// 이번 턴의 동적 ReAct · 워크플로우 · 하네스 · 내부 LLM 실행 흐름도(SVG).
// 각 노드를 누르면 해당 구조 칸의 상세(NodeDetail)로 연결된다. 연락 도구 걸음의 가지(조회·초안·위임 발송·막힘)는 그 걸음 옆 배지.
// 연락 하나(Task 109)는 OutreachFlow: 들어오는 문 → 도구 → 뒤 확인 → 나가는 문 → 통로 다섯 마디.
import type { NodeKey, OutreachFlowNode, TraceItem, TurnDetail } from './devApi';
import { seconds, tokens } from './format';
import { REFUSAL_SIGNALS, STEP_SIGNALS } from './signals';

interface FlowNode {
  id: string;
  kind: 'request' | 'context' | 'llm' | 'tool' | 'check' | 'approval' | 'inner_llm' | 'respond';
  targetKey: NodeKey;
  title: string;
  sub: string;
  ok: boolean;
  /** 도구 단계의 11-23 신호(signals.ts). 예전 서버는 없다. */
  signals?: string[];
}

const CHECK_SET = new Set(['harness.check', 'generate.run', 'schedule.import']);
const APPROVAL_SET = new Set(['out.submit_change', 'scenario.submit', 'rules.propose']);

function toolTarget(label: string): { kind: FlowNode['kind']; targetKey: NodeKey } {
  if (CHECK_SET.has(label)) return { kind: 'check', targetKey: 'check' };
  if (APPROVAL_SET.has(label)) return { kind: 'approval', targetKey: 'approval' };
  return { kind: 'tool', targetKey: 'tool' };
}

function buildFlow(detail: TurnDetail): FlowNode[] {
  const nodes: FlowNode[] = [
    {
      id: 'req',
      kind: 'request',
      targetKey: 'request',
      title: '요청 받기',
      sub: detail.turn.request || '사용자 요청',
      ok: true,
    },
  ];
  let llmIdx = 0;
  for (const item of detail.timeline) {
    nodes.push(fromTimeline(item, item.kind === 'llm' ? ++llmIdx : llmIdx));
  }
  nodes.push({
    id: 'res',
    kind: 'respond',
    targetKey: 'respond',
    title: '응답 · 기록',
    sub: detail.turn.ms !== null ? `전체 ${seconds(detail.turn.ms)}` : '진행 중',
    ok: detail.turn.status !== 'failed',
  });
  return nodes;
}

function fromTimeline(item: TraceItem, llmNum: number): FlowNode {
  const dur = item.ms !== null ? seconds(item.ms) : '진행 중';
  if (item.kind === 'context') {
    return { id: `t-${item.seq}`, kind: 'context', targetKey: 'context', title: '컨텍스트 조립', sub: dur, ok: item.ok };
  }
  if (item.kind === 'llm') {
    const tok = item.input_tokens + item.output_tokens;
    const tag = llmNum === 1 ? 'ReAct 1 (계획·판단)' : `ReAct ${llmNum} (관찰→판단)`;
    return {
      id: `t-${item.seq}`,
      kind: 'llm',
      targetKey: llmNum === 1 ? 'plan' : 'judge',
      title: `${tag} · ${item.model ?? '모델'}`,
      sub: `${dur}${tok ? ` · ${tokens(tok)} 토큰` : ''}`,
      ok: item.ok,
    };
  }
  if (item.kind === 'inner_llm') {
    return {
      id: `t-${item.seq}`,
      kind: 'inner_llm',
      targetKey: 'check',
      title: item.label,
      sub: `${item.model ?? ''} · ${dur}`,
      ok: item.ok,
    };
  }
  const { kind, targetKey } = toolTarget(item.label);
  const signals = (item.signals ?? []).filter((f) => STEP_SIGNALS[f]);
  const refused = signals.some((f) => REFUSAL_SIGNALS.has(f));
  return {
    id: `t-${item.seq}`,
    kind,
    targetKey,
    title: item.label,
    sub: item.ok ? dur : `${refused ? '거절' : '실패'} · ${item.error ?? ''}`,
    ok: item.ok,
    signals,
  };
}

/** 노드 오른쪽 빈 칸(SIDE_W)에 그 단계의 신호 배지. 둘이 넘으면 「+n」. */
function FlowSignals({ n, y }: { n: FlowNode; y: number }) {
  const flags = n.signals ?? [];
  if (!flags.length) return null;
  const shown = flags.slice(0, 2);
  return (
    <foreignObject x={PAD_X + NODE_W + 8} y={y} width={SIDE_W - 8} height={NODE_H}>
      <ul className="dc-sigbox is-flow" aria-label={`${n.title} 신호`} title={flags.map((f) => STEP_SIGNALS[f].label).join(' · ')}>
        {shown.map((f) => (
          <li key={f} className={`dc-sigbadge${STEP_SIGNALS[f].warn ? ' is-warn' : ''}`}>{STEP_SIGNALS[f].short}</li>
        ))}
        {flags.length > shown.length && <li className="dc-sigbadge">{`+${flags.length - shown.length}`}</li>}
      </ul>
    </foreignObject>
  );
}

interface Props {
  detail: TurnDetail;
  selected: NodeKey | null;
  onSelect(key: NodeKey): void;
}

const NODE_W = 280;
const NODE_H = 48;
const GAP_Y = 26;
const PAD_X = 24;
const PAD_Y = 16;
const SIDE_W = 120;

export default function TurnFlowDiagram({ detail, selected, onSelect }: Props) {
  const nodes = buildFlow(detail);
  const svgW = NODE_W + PAD_X * 2 + SIDE_W;
  const svgH = PAD_Y * 2 + nodes.length * NODE_H + Math.max(0, nodes.length - 1) * GAP_Y;
  const cx = PAD_X + NODE_W / 2;

  return (
    <div className="dc-canvas dc-flow-wrap">
      <svg
        role="group"
        aria-label="이번 턴 실행 흐름도"
        className="dc-svg"
        width={svgW}
        height={svgH}
        viewBox={`0 0 ${svgW} ${svgH}`}
      >
        <defs>
          <marker id="dc-flow-arrow" className="dc-arrow is-past" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">
            <path d="M0,0 L8,4 L0,8 z" />
          </marker>
        </defs>
        {nodes.slice(0, -1).map((n, i) => {
          const y1 = PAD_Y + i * (NODE_H + GAP_Y) + NODE_H;
          const y2 = y1 + GAP_Y;
          const label = n.kind === 'llm' ? '도구 호출' : n.kind === 'tool' || n.kind === 'check' ? '관찰 전달' : '';
          return (
            <g key={`e-${n.id}`} className="dc-edge is-past">
              <path d={`M${cx},${y1} V${y2}`} markerEnd="url(#dc-flow-arrow)" />
              {label && (
                <text x={cx + 8} y={(y1 + y2) / 2 + 4} className="dc-edge-label">
                  {label}
                </text>
              )}
            </g>
          );
        })}
        {nodes.map((n, i) => {
          const y = PAD_Y + i * (NODE_H + GAP_Y);
          const x = n.kind === 'inner_llm' ? PAD_X + 36 : PAD_X;
          const w = n.kind === 'inner_llm' ? NODE_W - 36 : NODE_W;
          return (
            <g key={n.id}>
              <foreignObject x={x - 2} y={y - 2} width={w + 4} height={NODE_H + 4}>
                <button
                  type="button"
                  className={`dc-node dc-flow-node is-${n.kind}${n.ok ? '' : ' is-fail'}`}
                  aria-pressed={selected === n.targetKey}
                  onClick={() => onSelect(n.targetKey)}
                >
                  <b className="dc-flow-title" title={n.title}>{n.title}</b>
                  <small className="dc-flow-sub" title={n.sub}>{n.sub}</small>
                </button>
              </foreignObject>
              <FlowSignals n={n} y={y} />
            </g>
          );
        })}
      </svg>
    </div>
  );
}

/** 연락 하나의 가지(서버가 기록으로 켠 것만): 받은 문자 줄에 받기 판정 사건이 있고 답 줄이 걸려 있음 — 응대했으면
 * inbound_handled, 막고 고정 안내만 했으면 inbound_refused(한 칸에 하나만 보인다). 통화 줄은 call_placed. */
const INBOUND_HANDLED = { key: 'inbound_handled', label: '받은 문자 응대', on: '답 줄로 이어짐', warn: false };
const INBOUND_REFUSED = { key: 'inbound_refused', label: '받은 문자 — 막고 안내함', on: '안내 답 줄로 이어짐', warn: true };
/** 통화 줄(Task 110): 걸기 직전 재확인을 지나 dialing 으로 차지됐을 때만 켜진다. */
const CALL_PLACED = { key: 'call_placed', label: 'AI 전화 걺', on: '걸기 직전 재확인을 지남', warn: false };
/** 받은 통화(Task 98): 받아 통화가 끝났으면 응대, 받기 전에 거절했으면 거절(한 칸에 하나만 보인다). */
const CALL_ANSWERED = { key: 'call_answered', label: '받은 통화 응대', on: '통화가 끝남', warn: false };
const CALL_REJECTED = { key: 'call_rejected', label: '받은 통화 — 받기 전 거절', on: '받기 판정이 막음', warn: true };

/** 연락 하나의 흐름도: 다섯 마디(차례는 서버가 준 대로)마다 그 줄의 사건 수와 판정(서버의 판정 글). 사건이 없는 마디와 꺼진 가지는
 * 흐리다. 넓으면 한 줄, 좁은 창에서는 다음 줄로 접혀 가로로 넘치지 않는다. */
export function OutreachFlow({ flow, lit, kind = 'message', direction = 'out' }: { flow: OutreachFlowNode[]; lit: string[]; kind?: 'message' | 'call'; direction?: string }) {
  // 통화: 거는 통화는 「AI 전화 걺」, 받은 통화는 응대 · 받기 전 거절 가운데 하나. 문자: 받은 문자 응대 · 막고 안내함 가운데 하나.
  const inbound = lit.includes(CALL_REJECTED.key) ? CALL_REJECTED : CALL_ANSWERED;
  const branch = kind === 'call' ? [direction === 'in' ? inbound : CALL_PLACED] : [lit.includes(INBOUND_REFUSED.key) ? INBOUND_REFUSED : INBOUND_HANDLED];
  return (
    <ol className="dc-o-flow" aria-label="연락 흐름도">
      {flow.map((n) => (
        <li key={n.key} className={`dc-o-fnode${n.count ? ' is-on' : ''}`} aria-label={`${n.label}, 사건 ${n.count}`}>
          <b>{n.label}</b>
          <small>{`사건 ${n.count}`}</small>
          {n.verdicts.length > 0 && (
            <span className="dc-o-verdicts">
              {n.verdicts.map((v) => (
                <span key={`${v.verdict}-${v.label}`} className={`dc-tag${v.verdict === 'blocked' ? ' is-danger' : v.verdict === 'noted' ? ' is-warn' : ''}`}>
                  {`${v.label} ${v.count}`}
                </span>
              ))}
            </span>
          )}
        </li>
      ))}
      {branch.map((b) => {
        const on = lit.includes(b.key);
        return (
          <li key={b.key} className={`dc-o-branch ${on ? 'is-lit' : 'is-dim'}${b.warn ? ' is-warn' : ''}`} aria-label={`${b.label}, ${on ? b.on : '기록 없음'}`} title={b.key}>
            <b>{b.label}</b>
            <small>{`가지 · ${on ? b.on : '기록 없음'}`}</small>
          </li>
        );
      })}
    </ol>
  );
}
