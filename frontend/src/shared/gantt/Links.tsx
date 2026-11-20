import { useId } from 'react';
import { linkPath, type LinkEnd, type RelType } from './layout';
import './gantt.css';

export interface LinkItem {
  /** 'pred>succ:TYPE'(같은 두 액티비티 사이에 종류가 다른 관계가 있을 수 있다). */
  key: string;
  from: LinkEnd;
  to: LinkEnd;
  type: RelType;
  lag: number;
  critical: boolean;
  /** 마우스를 올리면 보이는 글(예 'A2020 → A3020 SS+30'). */
  title: string;
}

/** 관계선(꺾은선 + 화살표). 간격이 있으면 들어가는 곳 앞에 +n 을 적는다. mid: 줄 위쪽에서 선이 닿는 높이. */
export default function Links({ items, rowH, mid = rowH / 2 }: { items: LinkItem[]; rowH: number; mid?: number }) {
  const uid = useId().replace(/[^a-zA-Z0-9_-]/g, '');
  const marker = (critical: boolean) => `url(#${uid}${critical ? 'c' : 'n'})`;
  return (
    <g className="gantt-links">
      <defs>
        {(['n', 'c'] as const).map((k) => (
          <marker key={k} id={`${uid}${k}`} viewBox="0 0 6 6" refX={5} refY={3} markerWidth={6} markerHeight={6} orient="auto">
            <path className={`gantt-arrow${k === 'c' ? ' critical' : ''}`} d="M 0 0 L 6 3 L 0 6 Z" />
          </marker>
        ))}
      </defs>
      {items.map((l) => {
        const toEnd = l.type === 'FF' || l.type === 'SF';
        const ex = toEnd ? l.to.x + l.to.w : l.to.x;
        return (
          <g key={l.key}>
            <path data-link={l.key} className={`gantt-link${l.critical ? ' critical' : ''}`} d={linkPath(l.from, l.to, l.type, rowH, mid)} markerEnd={marker(l.critical)}>
              <title>{l.title}</title>
            </path>
            {l.lag !== 0 && (
              // 들어가는 선 아래(줄 아래쪽)에 — 위쪽 칸(Plan 막대)과 겹치지 않게.
              <text className="gantt-lag" x={toEnd ? ex + 8 : ex - 8} y={l.to.row * rowH + Math.min(rowH - 1, mid + 8)} textAnchor={toEnd ? 'start' : 'end'}>
                {l.lag > 0 ? `+${l.lag}` : String(l.lag)}
              </text>
            )}
          </g>
        );
      })}
    </g>
  );
}
