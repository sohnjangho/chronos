// 단계 그림: 완료 = 성공색 테두리 · 실행 중 = 강조색 + 빛 · 대기 = 점선 · 실패·멈춤 = 위험색·흐린 테두리.
// 한 답이 함께 부른 도구(같은 글·모델·토큰이 바로 이어짐)는 한 칸에 세로로 쌓는다. 폭이 좁으면 한 줄 칸 수를 줄인다.
import { useEffect, useRef, useState } from 'react';
import { columnsFor, layout, NODE_H, NODE_W, type LayoutNode } from './graphLayout';
import { circled, programLabel, seconds, stepStatus, toolLabel } from './labels';
import type { Step } from './wfApi';

interface Props {
  steps: Step[];
  selected?: number | null;
  onSelect?(n: number): void;
}

/** 한 답에서 나온 단계 묶음 열쇠(글이 없으면 묶지 않는다). */
const groupKey = (s: Step) => (s.why ? `${s.why}\u0000${s.model ?? ''}\u0000${s.tokens}` : null);

function useColumns() {
  const ref = useRef<HTMLDivElement>(null);
  const [cols, setCols] = useState(4);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => setCols(columnsFor(el.clientWidth)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return { ref, cols };
}

/** 같은 줄이면 오른쪽으로 꺾어 들어가고, 다음 줄이면 줄 사이 틈과 왼쪽 여백을 돌아 왼쪽에서 들어간다. */
function edgePath(a: LayoutNode, b: LayoutNode, rowTop: number): string {
  const ay = a.y + NODE_H / 2;
  const by = b.y + NODE_H / 2;
  const mx = a.x + NODE_W + 12;
  if (b.row === a.row) return `M${a.x + NODE_W} ${ay} H${mx} V${by} H${b.x}`;
  return `M${a.x + NODE_W} ${ay} H${mx} V${rowTop - 17} H${b.x - 12} V${by} H${b.x}`;
}

function timeText(s: Step): string {
  if (s.status === 'running') return '실행 중';
  if (s.status !== 'done') return stepStatus(s.status);
  return s.ms === null ? '—' : seconds(s.ms);
}

export default function StepGraph({ steps, selected = null, onSelect }: Props) {
  const { ref, cols } = useColumns();
  const g = layout(
    steps.map((s) => ({ id: String(s.n), parallel_group: groupKey(s) })),
    cols,
  );
  const at = new Map(g.nodes.map((n) => [n.id, n]));
  const rowTop = new Map<number, number>();
  for (const n of g.nodes) rowTop.set(n.row, Math.min(rowTop.get(n.row) ?? n.y, n.y));
  const byN = new Map(steps.map((s) => [String(s.n), s]));
  return (
    <div ref={ref} className="wf-graph-wrap">
      <div className="wf-canvas" style={{ width: g.width, height: g.height }}>
        <svg className="wf-edges" width={g.width} height={g.height} aria-hidden="true">
          {g.edges.map((e) => (
            <path key={`${e.from}-${e.to}`} d={edgePath(at.get(e.from)!, at.get(e.to)!, rowTop.get(at.get(e.to)!.row)!)} className={byN.get(e.to)?.status === 'running' ? 'is-live' : undefined} />
          ))}
        </svg>
        <ol className="wf-nodes" aria-label="단계 그림">
          {steps.map((s, i) => {
            const pos = at.get(String(s.n))!;
            const stacked = i > 0 && groupKey(s) !== null && groupKey(steps[i - 1]) === groupKey(s);
            return (
              <li key={s.n} style={{ left: pos.x, top: pos.y, width: NODE_W, height: NODE_H }}>
                <button type="button" className={`wf-node ${s.status}`} aria-pressed={selected === s.n} onClick={() => onSelect?.(s.n)}>
                  <span className="wf-node-n">
                    {`${circled(s.n)} ${programLabel(s.program)} · ${timeText(s)}${stacked ? ' (동시에)' : ''}`}
                  </span>
                  <b className="wf-node-t" title={toolLabel(s.tool)}>
                    {toolLabel(s.tool)}
                  </b>
                  <span className="wf-node-m" title={s.tool}>
                    {s.tool}
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      </div>
    </div>
  );
}
