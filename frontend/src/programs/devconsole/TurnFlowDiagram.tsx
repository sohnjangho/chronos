// 이번 턴의 동적 ReAct · 워크플로우 · 하네스 · 내부 LLM 실행 흐름도(SVG).
// 각 노드를 누르면 해당 구조 칸의 상세(NodeDetail)로 연결된다.
import type { NodeKey, TraceItem, TurnDetail } from './devApi';
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
