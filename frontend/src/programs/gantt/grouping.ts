// 간트 줄: WBS 나무(기본) 또는 주요 자원별 줄. 묶음 줄의 요약 막대는 아래 액티비티의 Plan(plan_start~plan_finish) 범위다.
import type { Activity, ScheduleView, Wbs } from '../../shared/schedule/scheduleApi';
import { wbsLabel, wbsTree } from '../../shared/schedule/rows';

export type GroupBy = 'wbs' | 'resource';

export interface GanttRow {
  /** WBS 묶음 = WBS 코드, 자원 묶음 = 'res:<자원 id>'('res:' = 자원 없음), 액티비티 = id(자원 묶음 안에서는 '<묶음>/<id>'). */
  key: string;
  kind: 'group' | 'activity' | 'milestone';
  label: string;
  activity?: Activity;
  depth: number;
  /** 묶음 줄: 아래 액티비티의 가장 이른 Plan 시작 · 가장 늦은 Plan 종료(Plan 없는 액티비티는 빼고). */
  spanStart?: string;
  spanFinish?: string;
  /** 묶음 줄: 펼쳤는가 · 아래 액티비티 수. */
  open?: boolean;
  count?: number;
  /** 자원 묶음 줄: 그 자원을 쓰는 액티비티(접어도 줄 안에 막대로 보인다). */
  lane?: Activity[];
}

const NO_RESOURCE = 'res:';

function span(acts: Activity[]) {
  let spanStart: string | undefined;
  let spanFinish: string | undefined;
  for (const a of acts) {
    if (!a.plan_start || !a.plan_finish) continue;
    if (!spanStart || a.plan_start < spanStart) spanStart = a.plan_start;
    if (!spanFinish || a.plan_finish > spanFinish) spanFinish = a.plan_finish;
  }
  return { spanStart, spanFinish };
}

const actRow = (a: Activity, depth: number, key = a.id): GanttRow => ({
  key, kind: a.kind === 'task' ? 'activity' : 'milestone', label: a.name, activity: a, depth,
});

function byWbs(view: ScheduleView, collapsed: ReadonlySet<string>): GanttRow[] {
  const tree = wbsTree(view);
  const walk = (w: Wbs, depth: number): GanttRow[] => {
    const under = tree.under(w.code);
    const open = !collapsed.has(w.code);
    const group: GanttRow = { key: w.code, kind: 'group', label: wbsLabel(w), depth, open, count: under.length, ...span(under) };
    if (!open) return [group];
    const own = (tree.acts.get(w.code) ?? []).map((a) => actRow(a, depth + 1));
    return [group, ...own, ...(tree.children.get(w.code) ?? []).flatMap((c) => walk(c, depth + 1))];
  };
  return tree.roots.flatMap((w) => walk(w, 0));
}

/** 자원 줄 차례: 일정의 주요 자원, 그다음 목록에 없는 자원 id(만난 차례), 마지막에 자원 없음. */
function lanes(view: ScheduleView): { key: string; label: string; acts: Activity[] }[] {
  const known = new Map(view.resources.map((r) => [r.id, `${r.name} (${r.capacity}${r.unit})`]));
  const ids = [...known.keys()];
  for (const a of view.activities) for (const id of a.resources) if (!ids.includes(id)) ids.push(id);
  const out = ids.map((id) => ({ key: `res:${id}`, label: known.get(id) ?? id, acts: view.activities.filter((a) => a.resources.includes(id)) }));
  const none = view.activities.filter((a) => a.resources.length === 0);
  return [...out.filter((l) => l.acts.length > 0 || known.has(l.key.slice(4))), ...(none.length ? [{ key: NO_RESOURCE, label: '자원 없음', acts: none }] : [])];
}

function byResource(view: ScheduleView, collapsed: ReadonlySet<string>): GanttRow[] {
  return lanes(view).flatMap(({ key, label, acts }) => {
    const open = !collapsed.has(key);
    const group: GanttRow = { key, kind: 'group', label, depth: 0, open, count: acts.length, lane: acts, ...span(acts) };
    return open ? [group, ...acts.map((a) => actRow(a, 1, `${key}/${a.id}`))] : [group];
  });
}

/** 보일 줄. 접은 묶음은 묶음 줄만(요약 막대·자원 줄 막대는 남는다). */
export function rowsFor(view: ScheduleView, by: GroupBy, collapsed: ReadonlySet<string>): GanttRow[] {
  return by === 'wbs' ? byWbs(view, collapsed) : byResource(view, collapsed);
}

/** 모든 묶음 줄의 열쇠(모두 접기). */
export function groupKeys(view: ScheduleView, by: GroupBy): string[] {
  if (by === 'resource') return lanes(view).map((l) => l.key);
  return [...wbsTree(view).children.values()].flat().map((w) => w.code);
}
