// CPM 관계선(SVG): 꺾은선 + 화살촉 + 관계 글(FS·SS+15). 누르면 관계 고치기. 두 끝 자리가 바뀐 선만 다시 계산한다(memo).
import { memo, type KeyboardEvent } from 'react';
import type { RelType } from '../../shared/schedule/scheduleApi';
import { edgeKey, route, type NetEdge, type Pos } from './layout';
import { textWidth } from './NodeCard';

const TAG_H = 15;

/** 가장 긴 가로 토막의 가운데(관계 글 자리). 가로 토막이 없으면 첫 점. */
function tagAt(points: [number, number][]): [number, number] {
  let best: [number, number] = points[0];
  let len = -1;
  for (let i = 1; i < points.length; i += 1) {
    const [x0, y0] = points[i - 1];
    const [x1, y1] = points[i];
    if (y0 === y1 && Math.abs(x1 - x0) > len) {
      len = Math.abs(x1 - x0);
      best = [(x0 + x1) / 2, y0];
    }
  }
  return best;
}

interface EdgeProps {
  from: string;
  to: string;
  type: RelType;
  label: string;
  critical: boolean;
  fx: number;
  fy: number;
  tx: number;
  ty: number;
  editing: boolean;
  arrow: string;
  onPick(key: string): void;
}

const EdgeLine = memo(function EdgeLine({ from, to, type, label, critical, fx, fy, tx, ty, editing, arrow, onPick }: EdgeProps) {
  const key = edgeKey({ from, to, type });
  const points = route({ x: fx, y: fy }, { x: tx, y: ty }, type);
  const d = `M${points.map(([x, y]) => `${x} ${y}`).join(' L')}`;
  const [cx, cy] = tagAt(points);
  const w = textWidth(label, 11) + 8;
  const cls = critical ? ' critical' : '';
  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    e.preventDefault();
    onPick(key);
  };
  return (
    <g
      data-edge={key}
      className={`cpm-edge${editing ? ' is-editing' : ''}`}
      role="button"
      tabIndex={0}
      aria-label={`관계선 ${from} → ${to} ${label}`}
      onClick={() => onPick(key)}
      onKeyDown={onKeyDown}
    >
      <path className="cpm-edge-hit" d={d} />
      <path className={`cpm-edge-line${cls}`} d={d} markerEnd={`url(#${arrow}${critical ? '-c' : ''})`} />
      <g className={`cpm-edge-tag${cls}`}>
        <rect x={cx - w / 2} y={cy - TAG_H / 2} width={w} height={TAG_H} rx={3} />
        <text x={cx} y={cy + 4} textAnchor="middle">
          {label}
        </text>
      </g>
    </g>
  );
});

interface EdgesProps {
  edges: NetEdge[];
  pos: ReadonlyMap<string, Pos>;
  /** CPM 층이 꺼지면 크리티컬 빨강을 그리지 않는다. */
  cpm: boolean;
  editing: string | null;
  /** 화살촉 marker id 앞부분(창마다 다르게). */
  arrow: string;
  onPick(key: string): void;
}

export default function Edges({ edges, pos, cpm, editing, arrow, onPick }: EdgesProps) {
  return (
    <g className="cpm-edges">
      {edges.map((e) => {
        const f = pos.get(e.from)!;
        const t = pos.get(e.to)!;
        const key = edgeKey(e);
        return (
          <EdgeLine
            key={key} from={e.from} to={e.to} type={e.type} label={e.label} critical={cpm && e.critical}
            fx={f.x} fy={f.y} tx={t.x} ty={t.y} editing={editing === key} arrow={arrow} onPick={onPick}
          />
        );
      })}
    </g>
  );
}

/** 화살촉 둘(보통·크리티컬). */
export function ArrowDefs({ arrow }: { arrow: string }) {
  return (
    <defs>
      {['', '-c'].map((suffix) => (
        <marker key={suffix} id={`${arrow}${suffix}`} viewBox="0 0 8 8" refX={7} refY={4} markerWidth={8} markerHeight={8} markerUnits="userSpaceOnUse" orient="auto">
          <path className={`cpm-arrow${suffix ? ' critical' : ''}`} d="M0 0 L8 4 L0 8 z" />
        </marker>
      ))}
    </defs>
  );
}
