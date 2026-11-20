// 차트 줄 그림(SVG 안쪽): first~last 줄의 바탕·막대·◆·점선·관계선·세로선. 화면(보이는 줄)과 그림 내보내기(모든 줄)가 같이 쓴다.
// 액티비티 줄은 두 칸(PM 결정 11-20): 위 = Plan(plan_start~plan_finish), 아래 = 「Actual·예측」(실적 진하게 + 지금 계산의 EF 까지 예측 옅게).
// CPM 층(크리티컬 빨강·여유 꼬리 EF→LF·관계선)은 아래 칸에 붙는다. 날짜는 모두 서버 값의 자리다.
import type { PointerEvent as ReactPointerEvent } from 'react';
import {
  Band, Bar, Due, EndHandle, FloatTail, Ghost, GhostMilestone, Label, labelWidth, LaneBar, Milestone, ROW_H, Summary, TRACK_MID, TrackBar, VLine,
  Weekends,
} from '../../shared/gantt/Bars';
import Links from '../../shared/gantt/Links';
import { barRect, weekends, x, type Scale } from '../../shared/gantt/scale';
import { dot, statusBadge } from '../../shared/schedule/format';
import type { Activity, ScheduleView } from '../../shared/schedule/scheduleApi';
import { BlockedBands, BlockedLabels } from './BlockedBands';
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
  /** 작업 금지 이름표를 놓을 높이(그리는 줄들 안의 보이는 맨 위). 없으면 0(그림 내보내기). */
  labelY?: number;
  /** 끌어 고칠 수 있는가(미리 보기 중·그림 내보내기에서는 아니다). */
  editable: boolean;
  drag?: DragState | null;
  onBar?(e: ReactPointerEvent, a: Activity, rowKey: string, mode: DragMode): void;
  onEdit?(rowKey: string): void;
  onPick?(aid: string): void;
}

/** 막대 제목(가리키면 보임): 「A2020 이름 — 층 날짜」. 날짜는 서버 값을 점 표기로만 바꾼다. */
const tip = (a: Activity, what: string) => `${a.id} ${a.name} — ${what}`;
const span = (from: string, to: string) => (from === to ? dot(from) : `${dot(from)} ~ ${dot(to)}`);

/** 아래 칸 제목: 실적(끝났으면 ~ 실제 종료, 아니면 진행 중) · 예측(Data Date 나 ES ~ EF). */
function trackTitles(a: Activity, dataDate: string | null) {
  const actual = a.actual_start && `Actual ${dot(a.actual_start)} ~ ${a.actual_finish ? dot(a.actual_finish) : `진행 중(Data Date ${dot(dataDate)})`}`;
  const from = a.actual_start && dataDate ? dataDate : a.es;
  return { actual: tip(a, actual || ''), forecast: tip(a, `예측 ${span(from, a.ef)}`) };
}

/** 위 칸: Plan 막대(또는 ◆). 끌기 손잡이가 여기에 있다. */
function PlanShape({ m, row, a, y }: { m: ChartModel; row: GanttRow; a: Activity; y: number }) {
  const p = planOf(a);
  if (!p) return null;
  const title = tip(a, `Plan ${span(p.start, p.finish)}`);
  if (a.kind !== 'task') return <Milestone id={a.id} cx={anchorOf(m.scale, a)!.x} y={y} title={title} />;
  const r = barRect(m.scale, p.start, p.finish);
  const rules = dragRules(a, m.editable);
  return (
    <Bar
      id={a.id}
      x={r.x}
      w={r.w}
      y={y}
      title={title}
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
  const titles = trackTitles(a, m.view.data_date);
  if (t.ms) {
    const title = t.ms.kind === 'actual' ? tip(a, `Actual ${dot(a.actual_finish ?? a.actual_start)}`) : titles.forecast;
    return <Milestone id={a.id} cx={t.ms.cx} y={y} lane="track" kind={t.ms.kind} critical={t.ms.kind === 'forecast' && critical} title={title} />;
  }
  return (
    <>
      {t.actual && <TrackBar id={a.id} kind="actual" x={t.actual.x} w={t.actual.w} y={y} title={titles.actual} />}
      {t.forecast && <TrackBar id={a.id} kind="forecast" x={t.forecast.x} w={t.forecast.w} y={y} critical={critical} title={titles.forecast} />}
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

type Spot = { x: number; w: number };

/** 미리 보기 이전 자리(점선)의 자리: 막대는 그 날들, 마일스톤은 ◆ 자리(폭 0). */
function ghostSpot(m: ChartModel, a: Activity, d: Dates): Spot {
  if (a.kind === 'start_ms') return { x: x(m.scale, d.start), w: 0 };
  if (a.kind === 'finish_ms') return { x: x(m.scale, d.finish) + m.scale.pxPerDay, w: 0 };
  return barRect(m.scale, d.start, d.finish);
}

/** 보이는 칸들(막대·점선)이 차지하는 자리들. 이름은 이것들 밖에 쓴다(점선이 이름을 지나가지 않게). */
function spots(m: ChartModel, a: Activity, t: Track): Spot[] {
  const g = m.ghosts.get(a.id);
  const plan = m.layers.plan ? [anchorOf(m.scale, a), g?.plan && ghostSpot(m, a, g.plan)] : [];
  const track = m.layers.actual ? [t.actual, t.forecast, t.ms && { x: t.ms.cx, w: 0 }, g?.track && ghostSpot(m, a, g.track)] : [];
  return [...plan, ...track].filter((s): s is Spot => !!s);
}

/**
 * 막대 옆 이름: 지연이면 「· 지연 +n일」(서버 status), Plan 이 없으면 「· Plan 없음」. 보이는 칸들(점선 포함)의 오른쪽 끝 뒤에 쓰고,
 * 차트 오른쪽 끝을 넘으면 왼쪽 끝 앞에 오른쪽 맞춤으로 쓴다(잘리지 않게).
 */
function NameLabel({ m, a, y, t }: { m: ChartModel; a: Activity; y: number; t: Track }) {
  const all = spots(m, a, t);
  const ends = all.map((s) => s.x + s.w);
  const starts = all.map((s) => s.x);
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
    const r = ghostSpot(m, a, d);
    const data = lane === 'plan' ? { 'data-ghost': a.id } : { 'data-ghost-track': a.id };
    return a.kind === 'task' ? <Ghost {...data} lane={lane} x={r.x} w={r.w} y={y} /> : <GhostMilestone {...data} lane={lane} cx={r.x} y={y} />;
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
  const blocked = m.view.calendar?.blocked ?? [];
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
      <BlockedBands blocked={blocked} scale={m.scale} rows={shown} h={h} />
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
      <BlockedLabels blocked={blocked} scale={m.scale} total={m.total} y={Math.min(Math.max(0, m.labelY ?? 0), Math.max(0, h - ROW_H))} />
    </>
  );
}
