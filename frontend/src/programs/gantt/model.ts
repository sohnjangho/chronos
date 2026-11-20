// 간트 그리기 자료: 보일 기간 · 관계선 · 세로선 · 표 칸 글. 날짜는 서버 값을 자리로 바꾸기만 한다.
import type { HeaderMark } from '../../shared/gantt/Header';
import type { LinkEnd } from '../../shared/gantt/layout';
import type { LinkItem } from '../../shared/gantt/Links';
import { barRect, x, type Scale } from '../../shared/gantt/scale';
import { dot } from '../../shared/schedule/format';
import type { Activity, PredItem, ScheduleView } from '../../shared/schedule/scheduleApi';
import type { CellCtx } from '../../shared/schedule/columns';
import { format } from '../../shared/schedule/predecessors';
import { wbsLabel } from '../../shared/schedule/rows';
import type { GanttRow } from './grouping';
import type { ConditionMarks } from './marks';

export interface Layers {
  plan: boolean;
  actual: boolean;
  cpm: boolean;
}

/** 오늘(이 컴퓨터의 날짜) YYYY-MM-DD. */
export function todayIso(now = new Date()): string {
  const p = (n: number) => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${p(now.getMonth() + 1)}-${p(now.getDate())}`;
}

/** 일정에 나오는 가장 이른 날 ~ 가장 늦은 날(Plan·지금·Actual·Data Date·준공·기한). */
export function rangeOf(view: ScheduleView, marks: ConditionMarks): { start: string; end: string } {
  const days: string[] = [view.finish, ...marks.finishBy.map((m) => m.date), ...marks.milestoneBy.map((m) => m.date)];
  if (view.data_date) days.push(view.data_date);
  if (view.plan_finish) days.push(view.plan_finish);
  for (const a of view.activities) {
    days.push(a.es, a.ef);
    for (const d of [a.plan_start, a.plan_finish, a.actual_start, a.actual_finish]) if (d) days.push(d);
  }
  days.sort();
  return { start: days[0], end: days[days.length - 1] };
}

/**
 * Plan 날짜(서버 plan_start~plan_finish = 지금 일정을 실적 없이 계산한 것, PM 결정 11-20). 간트의 막대·◆·관계선·요약·자원 줄은
 * 모두 이 날짜에 그린다. 실적을 넣은 지금 계산(ES~EF)은 따로 그리지 않는다. 계산할 수 없으면 null(Plan 없음).
 */
export const planOf = (a: Activity): { start: string; finish: string } | null =>
  a.plan_start && a.plan_finish ? { start: a.plan_start, finish: a.plan_finish } : null;

/** 그 액티비티 Plan 막대의 자리(마일스톤은 ◆ 자리, 폭 0). Plan 이 없으면 null. */
export function anchorOf(scale: Scale, a: Activity): { x: number; w: number } | null {
  const p = planOf(a);
  if (!p) return null;
  if (a.kind === 'start_ms') return { x: x(scale, p.start), w: 0 };
  if (a.kind === 'finish_ms') return { x: x(scale, p.finish) + scale.pxPerDay, w: 0 };
  return barRect(scale, p.start, p.finish);
}

/** 액티비티 id → 처음 나오는 줄 번호. */
export function rowIndex(rows: GanttRow[]): Map<string, number> {
  const out = new Map<string, number>();
  rows.forEach((r, i) => r.activity && !out.has(r.activity.id) && out.set(r.activity.id, i));
  return out;
}

const lagText = (lag: number) => (lag > 0 ? `+${lag}` : lag < 0 ? String(lag) : '');

/** first~last 줄을 지나는 관계선(줄 번호는 first 에서 센다). 크리티컬 = 두 끝이 모두 크리티컬(서버 값). Plan 이 없는 끝은 잇지 않는다. */
export function linkItems(view: ScheduleView, scale: Scale, rowOf: Map<string, number>, first: number, last: number): LinkItem[] {
  const acts = new Map(view.activities.map((a) => [a.id, a]));
  const out: LinkItem[] = [];
  for (const r of view.relations) {
    const [pi, si] = [rowOf.get(r.pred), rowOf.get(r.succ)];
    const [p, s] = [acts.get(r.pred), acts.get(r.succ)];
    if (pi === undefined || si === undefined || !p || !s || Math.min(pi, si) > last || Math.max(pi, si) < first) continue;
    const [pa, sa] = [anchorOf(scale, p), anchorOf(scale, s)];
    if (!pa || !sa) continue;
    const end = (at: { x: number; w: number }, row: number): LinkEnd => ({ ...at, row: row - first });
    out.push({
      key: `${r.pred}>${r.succ}`, from: end(pa, pi), to: end(sa, si), type: r.type, lag: r.lag,
      critical: p.critical && s.critical, title: `${r.pred} → ${r.succ} ${r.type}${lagText(r.lag)}`,
    });
  }
  return out;
}

export interface VMark {
  kind: 'data' | 'deadline' | 'today';
  key: string;
  x: number;
  label: string;
  title?: string;
}

const md = (iso: string) => dot(iso).slice(5);

/** 세로선과 머리 이름표: Data Date(그날 0시) · 준공 기한(그날 끝) · 오늘(보이는 기간 안일 때만). */
export function vmarks(view: ScheduleView, marks: ConditionMarks, scale: Scale, today: string, total: number): VMark[] {
  const out: VMark[] = [];
  if (view.data_date) out.push({ kind: 'data', key: 'data', x: x(scale, view.data_date), label: `Data Date ${md(view.data_date)}` });
  for (const f of marks.finishBy)
    out.push({ kind: 'deadline', key: `deadline-${f.id}`, x: x(scale, f.date) + scale.pxPerDay, label: `기한 ${md(f.date)}`, title: `${f.text} — 기한 ${dot(f.date)}` });
  const t = x(scale, today);
  if (t >= 0 && t <= total) out.push({ kind: 'today', key: 'today', x: t, label: '오늘' });
  return out;
}

export const headerMarks = (ms: VMark[]): HeaderMark[] => ms.map((m) => ({ key: m.key, x: m.x, label: m.label, tone: m.kind, title: m.title }));

/** 표 칸 글(선행·WBS 이름·주요 자원 이름). 스케줄표와 같은 글이다. */
export function cellTexts(view: ScheduleView): Map<string, Omit<CellCtx, 'a'>> {
  const preds = new Map<string, PredItem[]>();
  for (const r of view.relations) preds.set(r.succ, [...(preds.get(r.succ) ?? []), { pred: r.pred, type: r.type, lag: r.lag }]);
  const wbs = new Map(view.wbs.map((w) => [w.code, wbsLabel(w)]));
  const res = new Map(view.resources.map((r) => [r.id, r.name]));
  return new Map(
    view.activities.map((a) => [
      a.id,
      { preds: format(preds.get(a.id) ?? []), wbsLabel: wbs.get(a.wbs) ?? a.wbs, resources: a.resources.map((id) => res.get(id) ?? id).join(', ') },
    ]),
  );
}
