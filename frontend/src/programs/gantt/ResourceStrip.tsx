// 아래 자원 줄(R7): 주요 자원마다 그 자원을 쓰는 액티비티의 Plan 기간(겹치면 진해진다).
// 날마다 필요량·용량 넘침은 서버가 아직 주지 않는다(계획 2 Task 21) — 화면이 세거나 지어내지 않는다.
import { LaneBar } from '../../shared/gantt/Bars';
import { barRect, type Scale } from '../../shared/gantt/scale';
import { dot } from '../../shared/schedule/format';
import type { ScheduleView } from '../../shared/schedule/scheduleApi';
import { planOf } from './model';
import type { Viewport } from './useViewport';

const LANE_H = 24;

export default function ResourceStrip({ view, scale, total, nameWidth, vp }: { view: ScheduleView; scale: Scale; total: number; nameWidth: number; vp: Viewport }) {
  if (view.resources.length === 0) return null;
  const used = new Map(view.resources.map((r) => [r.id, view.activities.filter((a) => a.resources.includes(r.id))]));
  return (
    <section className="gt-res" aria-label="주요 자원">
      <div className="gt-res-names" style={{ width: nameWidth }}>
        {view.resources.map((r) => (
          <div key={r.id} className="gt-res-name" title={`${r.name} (${r.capacity}${r.unit})`}>
            <b>{`${r.name} (${r.capacity}${r.unit})`}</b>
            <span className="sch-muted">{`액티비티 ${used.get(r.id)!.length}개`}</span>
          </div>
        ))}
      </div>
      <div className="gt-res-lanes" ref={vp.resRef}>
        <svg className="gantt-svg" width={total} height={view.resources.length * LANE_H} aria-hidden="true">
          {view.resources.map((r, i) => (
            <g key={r.id} data-res={r.id}>
              {used.get(r.id)!.map((a) => {
                const p = planOf(a);
                if (!p) return null;
                const b = barRect(scale, p.start, p.finish);
                return <LaneBar key={a.id} data-use={a.id} x={b.x} w={b.w} y={i * LANE_H + 6} h={LANE_H - 12} title={`${a.id} ${a.name} ${dot(p.start)}~${dot(p.finish)}`} />;
              })}
            </g>
          ))}
        </svg>
      </div>
    </section>
  );
}
