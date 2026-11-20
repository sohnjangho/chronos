// 오른쪽 차트: 날짜 머리(가로로 따라옴) + 본문(이것만 스크롤, 보이는 줄만 SVG 로 그림).
import { ROW_H } from '../../shared/gantt/Bars';
import Header from '../../shared/gantt/Header';
import ChartRows, { type ChartModel } from './ChartRows';
import { headerMarks } from './model';
import type { Viewport } from './useViewport';

export default function Chart({ m, vp }: { m: ChartModel; vp: Viewport }) {
  const totalH = m.rows.length * ROW_H;
  const shownH = Math.max(0, vp.last - vp.first + 1) * ROW_H;
  return (
    <div className="gt-right">
      <div className="gt-head" ref={vp.headRef}>
        <Header scale={m.scale} marks={headerMarks(m.vmarks)} />
      </div>
      <div className="gt-body" ref={vp.bodyRef} onScroll={vp.sync} data-px-per-day={m.scale.pxPerDay}>
        <div className="gt-spacer" style={{ width: m.total, height: totalH }}>
          {shownH > 0 && (
            <svg
              className="gantt-svg gt-rows"
              width={m.total}
              height={shownH}
              style={{ top: vp.first * ROW_H }}
              role="img"
              aria-label="간트 차트"
            >
              <ChartRows m={m} first={vp.first} last={vp.last} />
            </svg>
          )}
        </div>
      </div>
    </div>
  );
}
