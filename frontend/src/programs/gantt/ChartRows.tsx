// 차트 줄 그림(SVG 안쪽): first~last 줄의 바탕·막대·◆·점선·관계선·세로선. 화면(보이는 줄)과 그림 내보내기(모든 줄)가 같이 쓴다.
// 액티비티 줄은 두 칸(PM 결정 11-20): 위 = Plan(plan_start~plan_finish), 아래 = 「Actual·예측」(실적 진하게 + 지금 계산의 EF 까지 예측 옅게).
// CPM 층(크리티컬 빨강·여유 꼬리 EF→LF·관계선)은 아래 칸에 붙는다. 날짜는 모두 서버 값의 자리다.
import type { PointerEvent as ReactPointerEvent } from 'react';
import {
  Band, Bar, Blocked, Due, EndHandle, FloatTail, Ghost, Label, labelWidth, LaneBar, Milestone, ROW_H, Summary, TRACK_MID, TrackBar, VLine, Weekends,
} from '../../shared/gantt/Bars';
import Links from '../../shared/gantt/Links';
import { barRect, weekends, x, type Scale } from '../../shared/gantt/scale';
import { dot, statusBadge } from '../../shared/schedule/format';
import type { Activity, ScheduleView } from '../../shared/schedule/scheduleApi';
import type { GanttRow } from './grouping';
import { anchorOf, linkItems, planOf, trackOf, type Layers, type Track, type VMark } from './model';
import { dragLabel, dragRules, draggedOdRect, draggedStart, type DragMode, type DragState } from './useDrag';

type Dates = { start: string; finish: string };

export interface ChartModel {
  view: ScheduleView;
  rows: GanttRow[];
  scale: Scale;
  total: number;
  layers: Layers;
  selected: string | null;
  /** 미리 보기 이전 자리(저장된 보기와 미리 보기 보기가 다른 칸만): plan = Plan 칸, track = Actual·예측 칸(ES~EF). */
  ghosts: Map<string, { plan?: Dates; track?: Dates }>;
  /** 모든 액티비티의 Plan 이 없다(창에 한 번 알리므로 줄마다 「Plan 없음」을 쓰지 않는다). */
  noPlan: boolean;
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

/** 위 칸: Plan 막대(또는 ◆). 끌기 손잡이가 여기에 있다. */
function PlanShape({ m, row, a, y }: { m: ChartModel; row: GanttRow; a: Activity; y: number }) {
  const p = planOf(a);
  if (!p) return null;
  if (a.kind !== 'task') return <Milestone id={a.id} cx={anchorOf(m.scale, a)!.x} y={y} />;
  const r = barRect(m.scale, p.start, p.finish);
  const rules = dragRules(a, m.editable);
  return (
    <Bar
      id={a.id}
      x={r.x}
      w={r.w}
      y={y}
      data-movable={rules.move ? a.id : undefined}
      className={rules.move ? 'gt-movable' : undefined}
      onPointerDown={m.onBar && ((e) => m.onBar!(e, a, row.key, rules.move ? 'move' : 'click'))}
      onDoubleClick={m.editable ? () => m.onEdit?.(row.key) : undefined}
    >
      {rules.resize && m.onBar && <EndHandle id={a.id} x={r.x + r.w} y={y} onPointerDown={(e) => m.onBar!(e, a, row.key, 'od')} />}
    </Bar>
  );
}

/** 아래 칸: 실적·예측 막대(또는 ◆). CPM 층이면 예측을 크리티컬 빨강으로. */
function TrackShapes({ m, a, y, t }: { m: ChartModel; a: Activity; y: number; t: Track }) {
  const critical = m.layers.cpm && a.critical;
  if (t.ms) return <Milestone id={a.id} cx={t.ms.cx} y={y} lane="track" kind={t.ms.kind} critical={t.ms.kind === 'forecast' && critical} />;
  return (
    <>
      {t.actual && <TrackBar id={a.id} kind="actual" x={t.actual.x} w={t.actual.w} y={y} />}
      {t.forecast && <TrackBar id={a.id} kind="forecast" x={t.forecast.x} w={t.forecast.w} y={y} critical={critical} />}
    </>
  );
}

function DragGhost({ m, a, y, d }: { m: ChartModel; a: Activity; y: number; d: DragState }) {
  const r = barRect(m.scale, planOf(a)!.start, planOf(a)!.finish);
  const g = d.mode === 'od' ? draggedOdRect(a, d.dx, m.scale) : { x: x(m.scale, draggedStart(a, d.dx, m.scale)), w: r.w };
  return (
    <g data-drag={a.id}>
      <Ghost className="gantt-ghost is-drag" x={g.x} w={g.w} y={y} />
      <text className="gantt-drag-label" x={g.x + g.w + 8} y={y + 13}>
        {dragLabel(a, d, m.scale, m.view.calendar)}
      </text>
    </g>
  );
}

/**
 * 막대 옆 이름: 지연이면 「· 지연 +n일」(서버 status), Plan 이 없으면 「· Plan 없음」. 보이는 칸들의 오른쪽 끝 뒤에 쓰고,
 * 차트 오른쪽 끝을 넘으면 막대 왼쪽에 오른쪽 맞춤으로 쓴다(잘리지 않게).
 */
function NameLabel({ m, a, y, t }: { m: ChartModel; a: Activity; y: number; t: Track }) {
  const plan = m.layers.plan ? anchorOf(m.scale, a) : null;
  const ends = [plan && plan.x + plan.w, m.layers.actual ? t.end : null].filter((n): n is number => n !== null);
  const starts = [plan?.x, m.layers.actual ? (t.actual?.x ?? t.forecast?.x ?? t.ms?.cx) : undefined].filter((n): n is number => n !== undefined);
  const late = a.status.startsWith('late');
  const text = [a.name, late ? statusBadge(a.status).label : '', !planOf(a) && !m.noPlan ? 'Plan 없음' : ''].filter(Boolean).join(' · ');
  const right = (ends.length ? Math.max(...ends) : x(m.scale, a.es)) + (a.kind === 'task' ? 6 : 10);
  const fits = right + labelWidth(text) <= m.total;
  const at = fits ? right : (starts.length ? Math.min(...starts) : x(m.scale, a.es)) - (a.kind === 'task' ? 6 : 10);
  return <Label x={at} y={y} text={text} tone={late ? 'danger' : undefined} anchor={fits ? undefined : 'end'} />;
}

/** 여유 꼬리(CPM 층): 예측 끝(EF 다음 날 0시) → LF 끝. 끝난 것에는 없다. */
function Tail({ m, a, y }: { m: ChartModel; a: Activity; y: number }) {
  if (a.actual_finish || !a.lf || a.lf <= a.ef) return null;
  const x0 = x(m.scale, a.ef) + m.scale.pxPerDay;
  return <FloatTail id={a.id} x={x0} w={x(m.scale, a.lf) + m.scale.pxPerDay - x0} y={y} title={`여유 ${a.tf}일 · LF ${dot(a.lf)}`} />;
}

function ActivityShapes({ m, row, y }: { m: ChartModel; row: GanttRow; y: number }) {
  const a = row.activity!;
  const t = trackOf(m.scale, a, m.view.data_date);
  const g = m.ghosts.get(a.id);
  const ghost = (d: Dates, lane: 'plan' | 'track') => {
    const r = barRect(m.scale, d.start, d.finish);
    const data = lane === 'plan' ? { 'data-ghost': a.id } : { 'data-ghost-track': a.id };
    return <Ghost {...data} lane={lane} x={r.x} w={r.w} y={y} />;
  };
  return (
    <>
      {m.layers.plan && g?.plan && ghost(g.plan, 'plan')}
      {m.layers.actual && g?.track && ghost(g.track, 'track')}
      {m.layers.plan && <PlanShape m={m} row={row} a={a} y={y} />}
      {m.layers.actual && <TrackShapes m={m} a={a} y={y} t={t} />}
      {m.layers.actual && m.layers.cpm && <Tail m={m} a={a} y={y} />}
      {(m.dues.get(a.id) ?? []).map((d) => (
        <Due key={d.date} id={a.id} cx={x(m.scale, d.date) + m.scale.pxPerDay} y={y} title={`${d.text} — 기한 ${dot(d.date)}`} />
      ))}
      {m.drag?.rowKey === row.key ? <DragGhost m={m} a={a} y={y} d={m.drag} /> : <NameLabel m={m} a={a} y={y} t={t} />}
    </>
  );
}

/** 묶음 줄: WBS 는 Plan 범위 요약 막대, 자원 묶음은 그 자원을 쓰는 Plan 막대들(둘 다 Plan 층). */
function GroupShapes({ m, row, y }: { m: ChartModel; row: GanttRow; y: number }) {
  if (!m.layers.plan) return null;
  if (row.lane)
    return (
      <g data-lane={row.key}>
        {row.lane.map((a) => {
          const p = planOf(a);
          if (!p) return null;
          const r = barRect(m.scale, p.start, p.finish);
          return <LaneBar key={a.id} data-lane-bar={a.id} x={r.x} w={r.w} y={y + 9} title={`${a.id} ${a.name} ${dot(p.start)}~${dot(p.finish)}`} />;
        })}
      </g>
    );
  if (!row.spanStart || !row.spanFinish) return null;
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
      {m.layers.actual && m.layers.cpm && <Links items={linkItems(m.view, m.scale, m.rowOf, first, last)} rowH={ROW_H} mid={TRACK_MID} />}
      {shown.map((row, i) => (
        <g key={row.key}>
          {row.kind === 'group' ? <GroupShapes m={m} row={row} y={i * ROW_H} /> : <ActivityShapes m={m} row={row} y={i * ROW_H} />}
        </g>
      ))}
    </>
  );
}
