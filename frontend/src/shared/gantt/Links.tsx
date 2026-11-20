import { useId } from 'react';
import { linkPath, type LinkEnd, type RelType } from './layout';
import './gantt.css';

export interface LinkItem {
  /** 'pred>succ'. */
  key: string;
  from: LinkEnd;
  to: LinkEnd;
  type: RelType;
  lag: number;
  critical: boolean;
  /** 마우스를 올리면 보이는 글(예 'A2020 → A3020 SS+30'). */
  title: string;
}

/** 관계선(꺾은선 + 화살표). 간격이 있으면 들어가는 곳 앞에 +n 을 적는다. */
export default function Links({ items, rowH }: { items: LinkItem[]; rowH: number }) {
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
            <path data-link={l.key} className={`gantt-link${l.critical ? ' critical' : ''}`} d={linkPath(l.from, l.to, l.type, rowH)} markerEnd={marker(l.critical)}>
              <title>{l.title}</title>
            </path>
            {l.lag !== 0 && (
              <text className="gantt-lag" x={toEnd ? ex + 8 : ex - 8} y={l.to.row * rowH + rowH / 2 - 4} textAnchor={toEnd ? 'start' : 'end'}>
                {l.lag > 0 ? `+${l.lag}` : String(l.lag)}
              </text>
            )}
          </g>
        );
      })}
    </g>
  );
}
