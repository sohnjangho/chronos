// 에이전트 구조 그림(SVG, 시안 A안): 흐름 칸 아홉 + 곁 칸(컨텍스트 재료 다섯, 스킬 실행·승인함).
// 칸 모양: past 채움 · now 강조 테두리와 빛 · todo 점선 · skipped 회색 + "묶음 3". 칸은 폭에 맞춰 자리를 다시 잡는다.
// 연락 가지(Task 109): 도구 실행 → 「연락」 곁 칸. 기록된 연락 신호가 있을 때만 켜고, 없으면 흐리게 둔다.
import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import type { HarnessSummary, NodeKey, StructureNode, Turn } from './devApi';
import { hourMinute, seconds, tokens } from './format';
import { contextParts, STATE } from './NodeDetail';
import { OUTREACH_SIGNALS, signalsAt, STEP_SIGNALS } from './signals';
import { edgeShape, edgesFor, nodeBoxes, signalBoxes, SOURCES, type Box, type Edge } from './structureLayout';

/** 그림 칸의 폭(창 크기를 바꾸면 다시). ResizeObserver 가 없으면(시험 환경) 처음 값을 쓴다. */
function useWidth(fallback: number) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const measure = () => setWidth(Math.max(Math.floor(el.clientWidth), 300));
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return { ref, width };
}

function sub(n: StructureNode, turn: Turn): string {
  const running = turn.status === 'running';
  const none = running ? '아직' : '들르지 않음';
  const { count, detail } = n;
  switch (n.key) {
    case 'request':
      return `${turn.user_name} · ${hourMinute(turn.started_at)}`;
    case 'context': {
      const parts = contextParts(n);
      if (!parts.length) return count ? '재료 기록 없음' : none;
      const sum = parts.reduce((s, p) => s + (p.tokens ?? 0), 0);
      return sum ? `재료 ${parts.length}가지 · ≈${tokens(sum)} 토큰` : `재료 ${parts.length}가지`;
    }
    case 'skill':
      return count && typeof detail.in === 'string' ? `적용 · ${detail.in}` : '일치 없음';
    case 'plan':
    case 'judge':
      if (!count) return n.state === 'now' ? '호출 중' : none;
      return `${count}번 · ${detail.model ?? '모델 없음'}`;
    case 'respond':
      return count && detail.ms !== null ? `요청 전체 ${seconds(detail.ms)}` : none;
    default:
      return count ? `${count}번${detail.ms !== null ? ` · ${seconds(detail.ms)}` : ''}` : none;
  }
}

const PAD = 4;
const fo = (b: Box) => ({ x: b.x - PAD, y: b.y - PAD, width: b.w + 2 * PAD, height: b.h + 2 * PAD });

function EdgeLine({ edge, boxes }: { edge: Edge; boxes: ReturnType<typeof nodeBoxes> }) {
  const s = edgeShape(edge, boxes);
  return (
    <g className={`dc-edge is-${edge.state}${edge.unknown ? ' is-unknown' : ''}${edge.to === 'outreach' ? ' is-outreach' : ''}`}>
      {edge.unknown && <title>기록에 남지 않는 길</title>}
      <path d={s.d} markerEnd={`url(#dc-arrow-${edge.state})`} />
      {edge.label && (
        <text x={s.lx} y={s.ly} textAnchor={s.anchor} className="dc-edge-label">
          {edge.label}
        </text>
      )}
    </g>
  );
}

function Sources({ boxes, node }: { boxes: ReturnType<typeof nodeBoxes>; node: StructureNode | undefined }) {
  const parts = contextParts(node);
  return SOURCES.map((s) => {
    const mine = parts.filter((p) => s.parts.includes(p.name));
    const share = mine.reduce((a, p) => a + p.share, 0);
    const title = mine.map((p) => `${p.name} ${p.chars.toLocaleString('ko-KR')}자`).join(' · ') || s.parts.join(' · ');
    return (
      <foreignObject key={s.key} {...fo(boxes[s.key])}>
        <div className="dc-src" title={title}>
          <span>{s.label}</span>
          {mine.length > 0 && <b>{`${Math.round(share)}%`}</b>}
        </div>
      </foreignObject>
    );
  });
}

const SIDE: { key: 'skillrun' | 'inbox'; label: string; sub: string }[] = [
  { key: 'skillrun', label: '스킬 실행', sub: '저장된 워크플로우 적용' },
  { key: 'inbox', label: '승인함', sub: '사람이 승인·거부' },
];

const BRANCH_LABELS: Record<string, string> = {
  skill_matched: '스킬 적용됨',
  self_corrected: '자가 수정 복구',
  vision_turn: '그림 읽기 전환 (vision)',
  files_used: '자료·파일 도구',
  weather_used: '기상청 날씨 근거',
  check_repair: '하네스 고침 루프',
  approval_inbox: '승인함 대기',
  approval_auto: '자동 반영',
};
const branchLabel = (flag: string) => BRANCH_LABELS[flag] ?? STEP_SIGNALS[flag]?.label ?? flag;

/** 11-23 신호 배지 칸: 도구 실행 바로 위 · 조건 점검 옆. 그 칸의 신호가 없으면 그리지 않는다. */
function SignalBoxes({ boxes, lit }: { boxes: ReturnType<typeof nodeBoxes>; lit: string[] }) {
  const at = signalBoxes(boxes);
  const groups = [
    { key: 'toolSig' as const, place: 'tool' as const, name: '도구 실행 신호', node: boxes.tool },
    { key: 'checkSig' as const, place: 'check' as const, name: '조건 점검 신호', node: boxes.check },
  ];
  return groups.map(({ key, place, name, node }) => {
    const flags = signalsAt(lit, place);
    if (!flags.length) return null;
    const b = at[key];
    const link = place === 'tool'
      ? `M${b.x + b.w / 2},${b.y + b.h} V${node.y}`
      : `M${node.x + node.w},${node.y + node.h / 2} H${b.x}`;
    return (
      <g key={key}>
        <path d={link} className="dc-sigbox-link" />
        <foreignObject x={b.x} y={b.y} width={b.w} height={b.h}>
          <ul className="dc-sigbox" aria-label={name} title={flags.map((f) => STEP_SIGNALS[f].label).join(' · ')}>
            {flags.map((f) => (
              <li key={f} className={`dc-sigbadge${STEP_SIGNALS[f].warn ? ' is-warn' : ''}`}>{STEP_SIGNALS[f].short}</li>
            ))}
          </ul>
        </foreignObject>
      </g>
    );
  });
}

/** 연락 가지 곁 칸: 켜진 연락 신호의 짧은 이름(기록 없으면 흐림). */
function OutreachBox({ boxes, lit }: { boxes: ReturnType<typeof nodeBoxes>; lit: string[] }) {
  const flags = OUTREACH_SIGNALS.filter((f) => lit.includes(f));
  const sub = flags.length ? flags.map((f) => STEP_SIGNALS[f].short).join(' · ') : '기록 없음';
  const warn = flags.some((f) => STEP_SIGNALS[f].warn);
  return (
    <g role="group" aria-label={`연락 가지, ${sub}`}>
      <foreignObject {...fo(boxes.outreach)}>
        <div className={`dc-side dc-o-side ${flags.length ? 'is-lit' : 'is-dim'}${warn ? ' is-warn' : ''}`} title={flags.map((f) => STEP_SIGNALS[f].label).join(' · ') || '이 턴에는 연락 도구 기록이 없습니다.'}>
          <b>연락 · 나가는 문</b>
          <small>
            {flags.length
              ? flags.map((f, i) => (
                  <Fragment key={f}>
                    {i ? ' · ' : ''}
                    <span className="dc-nowrap">{STEP_SIGNALS[f].short}</span>
                  </Fragment>
                ))
              : sub}
          </small>
        </div>
      </foreignObject>
    </g>
  );
}

interface Props {
  nodes: StructureNode[];
  turn: Turn;
  selected: NodeKey | null;
  edgesLit?: string[];
  harnessSummary?: HarnessSummary | null;
  onSelect(key: NodeKey): void;
}

export default function AgentStructure({ nodes, turn, selected, edgesLit = [], harnessSummary, onSelect }: Props) {
  const { ref, width } = useWidth(900);
  const nowKey = nodes.find((n) => n.state === 'now')?.key ?? null;
  const nowRef = useRef<HTMLButtonElement>(null);
  // 요청을 열 때와 지금 칸이 바뀔 때만 지금 칸을 보이게 옮긴다(읽을 때마다가 아니다).
  useEffect(() => {
    if (nowKey) nowRef.current?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
  }, [turn.turn_id, nowKey]);
  const boxes = useMemo(() => nodeBoxes(width), [width]);
  const edges = useMemo(() => edgesFor(nodes, edgesLit), [nodes, edgesLit]);
  const height = Math.max(...Object.values(boxes).map((b) => b.y + b.h)) + 20;
  const context = nodes.find((n) => n.key === 'context');
  return (
    <div ref={ref} className="dc-canvas">
      {(edgesLit.length > 0 || harnessSummary) && (
        <div className="dc-signals" aria-label="실행된 분기 및 하네스 요약">
          {edgesLit.map((flag) => (
            <span key={flag} className={`dc-sig is-${flag}`}>
              {branchLabel(flag)}
            </span>
          ))}
          {harnessSummary && (
            <span className="dc-sig is-harness">
              {`하네스 ${harnessSummary.rounds}회차 · 통과 ${harnessSummary.passed} · 위반 ${harnessSummary.violations} · 자동점검안됨 ${harnessSummary.uncheckable}`}
            </span>
          )}
        </div>
      )}
      <svg role="group" aria-label="에이전트 구조" className="dc-svg" width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
        <defs>
          {(['past', 'now', 'todo'] as const).map((s) => (
            <marker key={s} id={`dc-arrow-${s}`} className={`dc-arrow is-${s}`} viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M0,0 L8,4 L0,8 z" />
            </marker>
          ))}
        </defs>
        {edges.map((e) => (
          <EdgeLine key={`${e.from}-${e.to}`} edge={e} boxes={boxes} />
        ))}
        <Sources boxes={boxes} node={context} />
        <SignalBoxes boxes={boxes} lit={edgesLit} />
        <OutreachBox boxes={boxes} lit={edgesLit} />
        {SIDE.map((s) => (
          <foreignObject key={s.key} {...fo(boxes[s.key])}>
            <div className="dc-side">
              <b>{s.label}</b>
              <small>{s.sub}</small>
            </div>
          </foreignObject>
        ))}
        {nodes.map((n) => (
          <foreignObject key={n.key} {...fo(boxes[n.key])}>
            <button
              ref={n.key === nowKey ? nowRef : undefined}
              type="button"
              className={`dc-node ${n.state}`}
              aria-label={`${n.label}, ${STATE[n.state].label}, ${sub(n, turn)}`}
              aria-pressed={n.key === selected}
              onClick={() => onSelect(n.key)}
            >
              <b>{n.label}</b>
              <small>{sub(n, turn)}</small>
            </button>
          </foreignObject>
        ))}
      </svg>
    </div>
  );
}
