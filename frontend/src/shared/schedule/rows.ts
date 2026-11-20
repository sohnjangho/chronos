// 스케줄표의 줄: WBS 묶음 줄(나무, 접기)과 그 아래 액티비티 줄. 찾기·거르기도 여기서 한다.
import { statusKey, type StatusKey } from './format';
import type { Activity, ScheduleView, Wbs } from './scheduleApi';

export interface GroupSummary {
  weight: number;
  planStart: string | null;
  planFinish: string | null;
  actualStart: string | null;
  /** 모두 끝났을 때만. */
  actualFinish: string | null;
  /** 가중 진척(0~1). 가중치 합이 0 이면 null. */
  progress: number | null;
}

export type GridRow =
  | { kind: 'group'; key: string; wbs: Wbs; label: string; depth: number; open: boolean; sum: GroupSummary }
  | { kind: 'activity'; key: string; activity: Activity; depth: number };

export interface RowFilter {
  query: string;
  statuses: StatusKey[];
  criticalOnly: boolean;
  /** 이 WBS 와 그 아래만. */
  wbs: string | null;
}

export const NO_FILTER: RowFilter = { query: '', statuses: [], criticalOnly: false, wbs: null };

export const filterCount = (f: RowFilter) => (f.statuses.length ? 1 : 0) + (f.criticalOnly ? 1 : 0) + (f.wbs ? 1 : 0);

export const wbsLabel = (w: Wbs) => (w.name ? `${w.code} ${w.name}` : w.code);

/** 가중치 × 진도의 합 / 가중치 합(서버가 준 가중치를 그대로 쓴다). 가중치 합이 0 이면 null. */
export function weightedProgress(acts: Activity[]): number | null {
  const total = acts.reduce((n, a) => n + a.weight, 0);
  return total > 0 ? acts.reduce((n, a) => n + a.weight * a.progress, 0) / total : null;
}

const pick = (values: (string | null)[], fn: (a: string, b: string) => boolean) =>
  values.reduce<string | null>((best, v) => (v !== null && (best === null || fn(v, best)) ? v : best), null);

function summarize(acts: Activity[]): GroupSummary {
  const allDone = acts.length > 0 && acts.every((a) => a.actual_finish);
  return {
    weight: acts.reduce((n, a) => n + a.weight, 0),
    planStart: pick(acts.map((a) => a.plan_start), (a, b) => a < b),
    planFinish: pick(acts.map((a) => a.plan_finish), (a, b) => a > b),
    actualStart: pick(acts.map((a) => a.actual_start), (a, b) => a < b),
    actualFinish: allDone ? pick(acts.map((a) => a.actual_finish), (a, b) => a > b) : null,
    progress: weightedProgress(acts),
  };
}

/** WBS 나무. 목록에 없는 WBS 를 쓰는 액티비티가 있으면 그 코드로 된 묶음을 끝에 더한다. */
export function wbsTree(view: ScheduleView) {
  const known = new Set(view.wbs.map((w) => w.code));
  const extra = [...new Set(view.activities.map((a) => a.wbs))].filter((c) => !known.has(c)).map((code) => ({ code, name: '', parent: null }));
  const all = [...view.wbs, ...extra];
  const children = new Map<string | null, Wbs[]>();
  for (const w of all) {
    const parent = w.parent !== null && known.has(w.parent) ? w.parent : null;
    children.set(parent, [...(children.get(parent) ?? []), w]);
  }
  const acts = new Map<string, Activity[]>();
  for (const a of view.activities) acts.set(a.wbs, [...(acts.get(a.wbs) ?? []), a]);
  const under = (code: string): Activity[] => [...(acts.get(code) ?? []), ...(children.get(code) ?? []).flatMap((w) => under(w.code))];
  const parentOf = new Map(all.map((w) => [w.code, w.parent]));
  return { roots: children.get(null) ?? [], children, acts, under, parentOf };
}

/** code 와 그 위 WBS 코드들. */
export function ancestors(parentOf: Map<string, string | null>, code: string): string[] {
  const out: string[] = [];
  for (let c: string | null | undefined = code; c && !out.includes(c); c = parentOf.get(c)) out.push(c);
  return out;
}

function matcher(f: RowFilter, inWbs: (code: string) => boolean) {
  const q = f.query.trim().toLowerCase();
  return (a: Activity) =>
    (!q || a.id.toLowerCase().includes(q) || a.name.toLowerCase().includes(q)) &&
    (!f.statuses.length || f.statuses.includes(statusKey(a.status) as StatusKey)) &&
    (!f.criticalOnly || a.critical) &&
    (!f.wbs || inWbs(a.wbs));
}

/** 보일 줄. 거르는 중이면 맞는 액티비티가 없는 묶음은 뺀다. 접은 묶음은 묶음 줄만. */
export function buildRows(view: ScheduleView, filter: RowFilter, collapsed: ReadonlySet<string>): GridRow[] {
  const tree = wbsTree(view);
  const active = filter.query.trim() !== '' || filterCount(filter) > 0;
  const matches = matcher(filter, (code) => ancestors(tree.parentOf, code).includes(filter.wbs!));
  const walk = (w: Wbs, depth: number): GridRow[] => {
    const own = (tree.acts.get(w.code) ?? []).filter(matches);
    const sub = (tree.children.get(w.code) ?? []).flatMap((c) => walk(c, depth + 1));
    if (active && own.length === 0 && !sub.some((r) => r.kind === 'activity' || !r.open)) return [];
    const open = !collapsed.has(w.code);
    const group: GridRow = { kind: 'group', key: `wbs:${w.code}`, wbs: w, label: wbsLabel(w), depth, open, sum: summarize(tree.under(w.code)) };
    if (!open) return [group];
    return [group, ...own.map((a): GridRow => ({ kind: 'activity', key: a.id, activity: a, depth: depth + 1 })), ...sub];
  };
  return tree.roots.flatMap((w) => walk(w, 0));
}
