// CPM 네트워크 배치: 보이는 노드를 고르고(전체·크리티컬·선택 이웃·WBS), 가장 긴 선행 사슬 깊이를 열로, 같은 열은 (ES, WBS, ID) 차례로 줄을 둔다.
// 관계선은 꺾은선(가로·세로만). 날짜는 계산하지 않는다 — ES 는 차례를 정할 때 글자로 견줄 뿐이다.
import { format } from '../../shared/schedule/predecessors';
import type { Activity, Relation, RelType, ScheduleView } from '../../shared/schedule/scheduleApi';

export const CARD_W = 248, CARD_H = 168, GAP_X = 96, GAP_Y = 32, PAD = 24;
/** 카드 옆으로 나갔다 들어오는 짧은 꺾임 길이. */
const STUB = 16;

export type ViewMode = 'all' | 'critical' | 'selected';
export interface Pos {
  x: number;
  y: number;
}
export interface NetNode extends Pos {
  id: string;
  col: number;
  row: number;
}
export interface NetEdge {
  from: string;
  to: string;
  type: RelType;
  lag: number;
  critical: boolean;
  label: string;
  points: [number, number][];
}
export interface Network {
  nodes: NetNode[];
  edges: NetEdge[];
  width: number;
  height: number;
}

/** 관계 열쇠(같은 두 액티비티에 종류가 다른 관계가 둘일 수 있다). */
export const edgeKey = (e: { from: string; to: string; type: RelType } | Relation) =>
  'pred' in e ? `${e.pred}>${e.succ}:${e.type}` : `${e.from}>${e.to}:${e.type}`;

/** 관계 글: 선행 칸 글(format)의 관계 부분 — "FS", "SS+15". */
export function relLabel(type: RelType, lag: number): string {
  const text = format([{ pred: '·', type, lag }]).slice(1).trim();
  return text || 'FS';
}

/** WBS 코드 → 맨 위 묶음 코드(부모를 따라 올라감, 끊긴·고리 부모면 거기서 멈춤). */
export function topWbs(view: ScheduleView): (code: string) => string {
  const parent = new Map(view.wbs.map((w) => [w.code, w.parent]));
  return (code) => {
    const seen = new Set<string>();
    let c = code;
    while (parent.get(c) && !seen.has(c)) {
      seen.add(c);
      c = parent.get(c)!;
    }
    return c;
  };
}

function visibleIds(view: ScheduleView, opt: { mode: ViewMode; selected?: string | null; wbs?: string | null }): Set<string> {
  const { mode, selected, wbs } = opt;
  if (mode === 'selected' && selected && view.activities.some((a) => a.id === selected)) {
    const ids = new Set([selected]);
    for (const r of view.relations) {
      if (r.succ === selected) ids.add(r.pred);
      if (r.pred === selected) ids.add(r.succ);
    }
    return ids;
  }
  const top = topWbs(view);
  return new Set(
    view.activities.filter((a) => (!wbs || top(a.wbs) === wbs) && (mode !== 'critical' || a.critical)).map((a) => a.id),
  );
}

/** 보이는 관계만으로 가장 긴 선행 사슬 깊이(Kahn 차례). */
function columns(ids: string[], rels: Relation[]): Map<string, number> {
  const col = new Map(ids.map((id) => [id, 0]));
  const indeg = new Map(ids.map((id) => [id, 0]));
  const next = new Map<string, string[]>(ids.map((id) => [id, []]));
  for (const r of rels) {
    next.get(r.pred)!.push(r.succ);
    indeg.set(r.succ, indeg.get(r.succ)! + 1);
  }
  const queue = ids.filter((id) => indeg.get(id) === 0);
  for (let i = 0; i < queue.length; i += 1) {
    const id = queue[i];
    for (const s of next.get(id)!) {
      col.set(s, Math.max(col.get(s)!, col.get(id)! + 1));
      indeg.set(s, indeg.get(s)! - 1);
      if (indeg.get(s) === 0) queue.push(s);
    }
  }
  return col;
}

const byEsWbsId = (a: Activity, b: Activity) =>
  a.es !== b.es ? (a.es < b.es ? -1 : 1) : a.wbs !== b.wbs ? (a.wbs < b.wbs ? -1 : 1) : a.id < b.id ? -1 : a.id > b.id ? 1 : 0;

/** 카드 자리(왼쪽 위)에서 관계 type 의 꺾은선. FS 오른→왼, SS 왼→왼, FF 오른→오른, SF 왼→오른(모두 세로 가운데). */
export function route(from: Pos, to: Pos, type: RelType): [number, number][] {
  const outRight = type === 'FS' || type === 'FF';
  const inRight = type === 'FF' || type === 'SF';
  const ox = from.x + (outRight ? CARD_W : 0);
  const oy = from.y + CARD_H / 2;
  const ix = to.x + (inRight ? CARD_W : 0);
  const iy = to.y + CARD_H / 2;
  const gap = ix - ox;
  if (outRight && !inRight && gap >= 2 * STUB && gap <= GAP_X + 2 * STUB) {
    const mx = ox + gap / 2;
    return tidy([[ox, oy], [mx, oy], [mx, iy], [ix, iy]]);
  }
  // 멀리 있거나 같은 쪽으로 들어가면 후행 카드 위 틈(줄 사이)으로 돈다 — 가운데 카드를 지나지 않게.
  const ex = ox + (outRight ? STUB : -STUB);
  const nx = ix + (inRight ? STUB : -STUB);
  const cy = to.y - GAP_Y / 2;
  return tidy([[ox, oy], [ex, oy], [ex, cy], [nx, cy], [nx, iy], [ix, iy]]);
}

/** 같은 점·한 줄 위의 가운데 점을 뺀다. */
function tidy(points: [number, number][]): [number, number][] {
  const out: [number, number][] = [];
  for (const p of points) {
    const last = out.at(-1);
    if (last && last[0] === p[0] && last[1] === p[1]) continue;
    const prev = out.at(-2);
    if (prev && last && ((prev[0] === last[0] && last[0] === p[0]) || (prev[1] === last[1] && last[1] === p[1]))) out.pop();
    out.push(p);
  }
  return out;
}

export function layoutNetwork(view: ScheduleView, opt: { mode: ViewMode; selected?: string | null; wbs?: string | null }): Network {
  const ids = visibleIds(view, opt);
  const acts = view.activities.filter((a) => ids.has(a.id));
  const byId = new Map(acts.map((a) => [a.id, a]));
  const rels = view.relations.filter((r) => byId.has(r.pred) && byId.has(r.succ));
  const col = columns(acts.map((a) => a.id), rels);
  const cols: Activity[][] = [];
  for (const a of acts) (cols[col.get(a.id)!] ??= []).push(a);
  const nodes: NetNode[] = [];
  let maxRow = -1;
  cols.forEach((list, c) =>
    [...list].sort(byEsWbsId).forEach((a, row) => {
      maxRow = Math.max(maxRow, row);
      nodes.push({ id: a.id, col: c, row, x: PAD + c * (CARD_W + GAP_X), y: PAD + row * (CARD_H + GAP_Y) });
    }),
  );
  const at = new Map(nodes.map((n) => [n.id, n]));
  const edges = rels.map((r) => ({
    from: r.pred, to: r.succ, type: r.type, lag: r.lag, label: relLabel(r.type, r.lag),
    critical: byId.get(r.pred)!.critical && byId.get(r.succ)!.critical,
    points: route(at.get(r.pred)!, at.get(r.succ)!, r.type),
  }));
  const span = (n: number, size: number, gap: number) => (n > 0 ? n * size + (n - 1) * gap : 0);
  return { nodes, edges, width: 2 * PAD + span(cols.length, CARD_W, GAP_X), height: 2 * PAD + span(maxRow + 1, CARD_H, GAP_Y) };
}
