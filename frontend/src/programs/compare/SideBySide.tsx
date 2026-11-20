// 좌우 비교: 기준·비교 간트를 같은 척도로 나란히. 두 판의 세로 스크롤이 맞물린다.
// 두 판은 같은 폭이고 차트는 그 안에 꼭 맞춘다(창이 가로로 밀리지 않는다). 날짜 → px 는 shared/gantt 눈금만 쓴다.
import { useRef } from 'react';
import Header from '../../shared/gantt/Header';
import { makeScale, type Scale } from '../../shared/gantt/scale';
import type { CompareOut, RowOut, SideOut } from './compareApi';
import Bar, { dueX, ROW_H } from './Bar';
import { deadlinesOf, spanOf } from './rows';
import { useWidth } from './useWidth';

interface PaneProps {
  side: 'base' | 'other';
  info: SideOut;
  rows: RowOut[];
  scale: Scale;
  labelW: number;
  chartW: number;
}

function PaneBody({ side, info, rows, scale, labelW, chartW }: PaneProps) {
  const lines = deadlinesOf([[side === 'base' ? '기준' : '비교', info]]);
  const h = rows.length * ROW_H;
  return (
    <>
      <div className="cmp-pane-head">
        <div className="cmp-pane-title" title={info.label}>
          <i className={`cmp-swatch is-${side === 'base' ? 'base' : 'other'}`} />
          {side === 'base' ? '기준' : '비교'} · {info.label}
        </div>
        <div className="cmp-pane-axis" style={{ gridTemplateColumns: `${labelW}px ${chartW}px` }}>
          <div className="cmp-cell">액티비티</div>
          <Header scale={scale} marks={lines.map((l) => ({ key: l.label, x: dueX(scale, l.date), label: l.label, tone: 'deadline' }))} />
        </div>
      </div>
      <div className="cmp-pane-body" style={{ height: h }}>
        {rows.map((r) => {
          const cell = side === 'base' ? r.base : r.other;
          return (
            <div key={r.activity_id} className="cmp-pane-row" style={{ gridTemplateColumns: `${labelW}px ${chartW}px` }}>
              <div className="cmp-cell" title={`${r.activity_id} ${r.name}`}>
                <b>{r.activity_id}</b> {r.name}
              </div>
              <svg className="gantt-svg cmp-rowsvg" width={chartW} height={ROW_H}>
                {cell && (
                  <Bar
                    scale={scale}
                    cell={cell}
                    y={12}
                    h={12}
                    className={side === 'base' ? 'is-base' : r.change}
                    testId={`bar-${r.activity_id}-${side}`}
                    what={`${r.name} — ${side === 'base' ? '기준' : '비교'}`}
                  />
                )}
                {!cell && (
                  <text className="cmp-delta" x={6} y={ROW_H / 2 + 4}>
                    {side === 'base' ? '기준에 없음' : '비교에 없음'}
                  </text>
                )}
              </svg>
            </div>
          );
        })}
        {h > 0 && (
          <svg className="cmp-lines" style={{ left: labelW }} width={chartW} height={h} aria-hidden="true">
            {lines.map((l) => (
              <line key={l.label} className="gantt-vline is-deadline" x1={dueX(scale, l.date)} x2={dueX(scale, l.date)} y1={0} y2={h} />
            ))}
          </svg>
        )}
      </div>
    </>
  );
}

export default function SideBySide({ data, rows }: { data: CompareOut; rows: RowOut[] }) {
  const left = useWidth<HTMLDivElement>(600);
  const right = useRef<HTMLDivElement>(null);
  const panes = [left.ref, right];
  // 옮겨 준 판: 그 판에서 돌아오는 스크롤 한 번은 다시 옮기지 않는다(끝에서 값이 맞춰져도 서로 밀고 당기지 않게).
  // 브라우저는 그 스크롤을 다음 그림 전에 알리므로 한 프레임 뒤에는 표를 지운다.
  const syncing = useRef<0 | 1 | null>(null);
  const sync = (from: 0 | 1) => () => {
    if (syncing.current === from) {
      syncing.current = null;
      return;
    }
    const a = panes[from].current;
    const b = panes[1 - from].current;
    if (!a || !b || b.scrollTop === a.scrollTop) return;
    const to = (1 - from) as 0 | 1;
    syncing.current = to;
    b.scrollTop = a.scrollTop;
    requestAnimationFrame(() => {
      if (syncing.current === to) syncing.current = null;
    });
  };
  const dues = deadlinesOf([
    ['기준', data.base],
    ['비교', data.other],
  ]);
  const span = spanOf(data.rows, dues.map((l) => l.date));
  if (!span) return <p className="cmp-empty">액티비티가 없습니다.</p>;
  const labelW = left.width >= 520 ? 180 : 96;
  const chartW = Math.max(60, left.width - labelW);
  const scale = makeScale(span.start, span.end, chartW, 5);
  const common = { rows, scale, labelW, chartW };
  return (
    <div className="cmp-sbs" role="region" aria-label="좌우 비교">
      <div className="cmp-pane" data-testid="pane" ref={left.ref} onScroll={sync(0)}>
        <PaneBody side="base" info={data.base} {...common} />
      </div>
      <div className="cmp-pane" data-testid="pane" ref={right} onScroll={sync(1)}>
        <PaneBody side="other" info={data.other} {...common} />
      </div>
      {rows.length === 0 && <p className="cmp-empty cmp-span">달라진 액티비티가 없습니다.</p>}
    </div>
  );
}
