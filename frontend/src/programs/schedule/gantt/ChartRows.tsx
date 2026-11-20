// 차트 줄 그림(SVG 안쪽): first~last 줄의 바탕·막대·Actual·◆·점선·관계선·세로선. 화면(보이는 줄)과 그림 내보내기(모든 줄)가 같이 쓴다.
import type { PointerEvent as ReactPointerEvent } from 'react';
import {
  ActualLine, Band, Bar, Blocked, Due, EndHandle, FloatTail, Ghost, Label, LaneBar, Milestone, PlanMark, ROW_H, Summary, VLine, Weekends,
} from '../../../shared/gantt/Bars';
import Links from '../../../shared/gantt/Links';
import { barRect, weekends, x, type Scale } from '../../../shared/gantt/scale';
import { dot, statusBadge } from '../format';
import type { Activity, ScheduleView } from '../scheduleApi';
import type { GanttRow } from './grouping';
import { anchorOf, linkItems, type Layers, type VMark } from './model';
import { dragLabel, dragRules, draggedOd, draggedStart, type DragMode, type DragState } from './useDrag';

export interface ChartModel {
  view: ScheduleView;
  rows: GanttRow[];
  scale: Scale;
  total: number;
  layers: Layers;
  selected: string | null;
  /** 미리 보기 이전 자리(액티비티 id → 날짜). */
  ghosts: Map<string, { start: string; finish: string }>;
  /** 마일스톤 기한 조건(액티비티 id → 기한들). */
  dues: Map<string, { date: string; text: string }[]>;
  rowOf: Map<string, number>;
  vmarks: VMark[];
  /** 끌어 고칠 수 있는가(미리 보기 중·그림 내보내기에서는 아니다). */
  editable: boolean;
  drag?: DragState | null;
  onBar?(e: ReactPointerEvent, a: Activity, rowKey: string, mode: DragMode): void;
  onEdit?(rowKey: string): void;
  onPick?(aid: string): void;
}

function ActivityBar({ m, row, a, y }: { m: ChartModel; row: GanttRow; a: Activity; y: number }) {
  const r = barRect(m.scale, a.es, a.ef);
  const critical = m.layers.cpm && a.critical;
  if (a.kind !== 'task') return <Milestone id={a.id} cx={anchorOf(m.scale, a).x} y={y} critical={critical} />;
  const rules = dragRules(a, m.editable);
  return (
    <Bar
      id={a.id}
      x={r.x}
      w={r.w}
      y={y}
      critical={critical}
      progress={a.progress}
      data-movable={rules.move ? a.id : undefined}
      className={rules.move ? 'gt-movable' : undefined}
      onPointerDown={m.onBar && ((e) => m.onBar!(e, a, row.key, rules.move ? 'move' : 'click'))}
      onDoubleClick={m.editable ? () => m.onEdit?.(row.key) : undefined}
    >
      {rules.resize && m.onBar && <EndHandle id={a.id} x={r.x + r.w} y={y} onPointerDown={(e) => m.onBar!(e, a, row.key, 'od')} />}
    </Bar>
  );
}

function DragGhost({ m, a, y, d }: { m: ChartModel; a: Activity; y: number; d: DragState }) {
  const r = barRect(m.scale, a.es, a.ef);
  const g = d.mode === 'od' ? { x: r.x, w: (draggedOd(a, d.dx, m.scale) * r.w) / a.od } : { x: x(m.scale, draggedStart(a, d.dx, m.scale)), w: r.w };
  return (
    <g data-drag={a.id}>
      <Ghost className="gantt-ghost is-drag" x={g.x} w={g.w} y={y} />
      <text className="gantt-drag-label" x={g.x + g.w + 8} y={y + 19}>
        {dragLabel(a, d, m.scale)}
      </text>
    </g>
  );
}

function ActivityShapes({ m, row, y }: { m: ChartModel; row: GanttRow; y: number }) {
  const a = row.activity!;
  const at = anchorOf(m.scale, a);
  const ghost = m.ghosts.get(a.id);
  const gr = ghost && barRect(m.scale, ghost.start, ghost.finish);
  const late = statusBadge(a.status);
  const plan = a.plan_start && a.plan_finish && (a.plan_start !== a.es || a.plan_finish !== a.ef) ? barRect(m.scale, a.plan_start, a.plan_finish) : null;
  const actualEnd = a.actual_finish ?? (m.view.data_date && m.view.data_date > a.actual_start! ? m.view.data_date : null);
  return (
    <>
      {m.layers.plan && plan && <PlanMark id={a.id} x={plan.x} w={plan.w} y={y} />}
      {gr && <Ghost data-ghost={a.id} x={gr.x} w={gr.w} y={y} />}
      {m.layers.plan && <ActivityBar m={m} row={row} a={a} y={y} />}
      {m.layers.plan && m.layers.cpm && a.lf && a.lf > a.ef && (
        <FloatTail id={a.id} x={at.x + at.w} w={x(m.scale, a.lf) + m.scale.pxPerDay - at.x - at.w} y={y} title={`여유 ${a.tf}일 · LF ${dot(a.lf)}`} />
      )}
      {m.layers.actual && a.actual_start && (
        <ActualLine
          id={a.id}
          x={x(m.scale, a.actual_start)}
          w={a.actual_finish ? barRect(m.scale, a.actual_start, a.actual_finish).w : actualEnd ? x(m.scale, actualEnd) - x(m.scale, a.actual_start) : 0}
          y={y}
        />
      )}
      {(m.dues.get(a.id) ?? []).map((d) => (
        <Due key={d.date} id={a.id} cx={x(m.scale, d.date) + m.scale.pxPerDay} y={y} title={`${d.text} — 기한 ${dot(d.date)}`} />
      ))}
      {m.drag?.rowKey === row.key ? (
        <DragGhost m={m} a={a} y={y} d={m.drag} />
      ) : (
        <Label x={at.x + at.w + (a.kind === 'task' ? 6 : 10)} y={y} text={a.status.startsWith('late') ? `${a.name} · ${late.label}` : a.name} tone={a.status.startsWith('late') ? 'danger' : undefined} />
      )}
    </>
  );
}

function GroupShapes({ m, row, y }: { m: ChartModel; row: GanttRow; y: number }) {
  if (row.lane)
    return (
      <g data-lane={row.key}>
        {row.lane.map((a) => {
          const r = barRect(m.scale, a.es, a.ef);
          return <LaneBar key={a.id} data-lane-bar={a.id} x={r.x} w={r.w} y={y + 9} title={`${a.id} ${a.name} ${dot(a.es)}~${dot(a.ef)}`} />;
        })}
      </g>
    );
  if (!m.layers.plan || !row.spanStart || !row.spanFinish) return null;
  const r = barRect(m.scale, row.spanStart, row.spanFinish);
  return <Summary id={row.key} x={r.x} w={r.w} y={y} />;
}

/** first~last 줄. y 는 first 줄을 0 으로 센다. */
export default function ChartRows({ m, first, last }: { m: ChartModel; first: number; last: number }) {
  const h = (last - first + 1) * ROW_H;
  const shown = m.rows.slice(first, last + 1);
  return (
    <>
      {shown.map((row, i) => {
        const aid = row.activity?.id;
        const sel = aid !== undefined && aid === m.selected;
        return (
          <Band
            key={`b-${row.key}`}
            y={i * ROW_H}
            w={m.total}
            className={sel ? 'is-selected' : row.kind === 'group' ? 'is-group' : undefined}
            data-sel={sel ? aid : undefined}
            onClick={aid && m.onPick ? () => m.onPick!(aid) : undefined}
          />
        );
      })}
      {(m.view.calendar?.blocked ?? []).map((b) => {
        const r = barRect(m.scale, b.start, b.finish);
        return <Blocked key={`${b.tag}-${b.start}`} tag={b.tag} x={r.x} w={r.w} h={h} title={`작업 금지(${b.tag}) ${dot(b.start)}~${dot(b.finish)}`} />;
      })}
      {m.scale.pxPerDay >= 3 && <Weekends days={weekends(m.scale, m.view.calendar?.days_per_week)} pxPerDay={m.scale.pxPerDay} h={h} />}
      {m.vmarks.map((v) => (
        <VLine key={v.key} kind={v.kind} x={v.x} h={h} />
      ))}
      {m.layers.plan && m.layers.cpm && <Links items={linkItems(m.view, m.scale, m.rowOf, first, last)} rowH={ROW_H} />}
      {shown.map((row, i) => (
        <g key={row.key}>
          {row.kind === 'group' ? <GroupShapes m={m} row={row} y={i * ROW_H} /> : <ActivityShapes m={m} row={row} y={i * ROW_H} />}
        </g>
      ))}
    </>
  );
}
