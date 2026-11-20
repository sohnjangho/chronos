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
/** 틈(줄 사이)을 지나는 선의 줄: 그 틈의 n 줄 가운데 i 번째. 틈을 지나지 않으면 {i: 0, n: 1}. */
export interface Lane {
  i: number;
  n: number;
}
export interface NetEdge {
  from: string;
  to: string;
  type: RelType;
  lag: number;
  critical: boolean;
  label: string;
  lane: Lane;
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

interface Ends {
  ox: number;
  oy: number;
  ix: number;
  iy: number;
  outRight: boolean;
  inRight: boolean;
}

function ends(from: Pos, to: Pos, type: RelType): Ends {
  const outRight = type === 'FS' || type === 'FF';
  const inRight = type === 'FF' || type === 'SF';
  return { ox: from.x + (outRight ? CARD_W : 0), oy: from.y + CARD_H / 2, ix: to.x + (inRight ? CARD_W : 0), iy: to.y + CARD_H / 2, outRight, inRight };
}

/** 이웃 열의 오른→왼(FS)이면 틈을 돌지 않고 열 사이에서 한 번 꺾는다. */
const isDirect = ({ ox, ix, outRight, inRight }: Ends) => outRight && !inRight && ix - ox >= 2 * STUB && ix - ox <= GAP_X + 2 * STUB;

/** 후행 카드 위 틈(맨 윗줄이면 PAD) 안에서 lane 번째 줄의 y. 틈 위아래 3px 은 비운다. */
function laneY(toY: number, { i, n }: Lane): number {
  const top = Math.max(0, toY - GAP_Y) + 3;
  const bottom = toY - 3;
  return Math.round((top + ((i + 1) * (bottom - top)) / (n + 1)) * 10) / 10;
}

/** 카드 자리(왼쪽 위)에서 관계 type 의 꺾은선. FS 오른→왼, SS 왼→왼, FF 오른→오른, SF 왼→오른(모두 세로 가운데). */
export function route(from: Pos, to: Pos, type: RelType, lane: Lane = { i: 0, n: 1 }): [number, number][] {
  const e = ends(from, to, type);
  const { ox, oy, ix, iy } = e;
  if (isDirect(e)) {
    const mx = ox + (ix - ox) / 2;
    return tidy([[ox, oy], [mx, oy], [mx, iy], [ix, iy]]);
  }
  // 멀리 있거나 같은 쪽으로 들어가면 후행 카드 위 틈(줄 사이)으로 돈다 — 가운데 카드를 지나지 않게. 같은 틈의 선은 줄을 나눈다.
  const ex = ox + (e.outRight ? STUB : -STUB);
  const nx = ix + (e.inRight ? STUB : -STUB);
  const cy = laneY(to.y, lane);
  return tidy([[ox, oy], [ex, oy], [ex, cy], [nx, cy], [nx, iy], [ix, iy]]);
}

/** 배치 자리에서 틈을 도는 선마다 그 틈(후행 줄) 안의 줄. 차례는 (후행 열, 선행 열, 열쇠) — 늘 같다. */
function lanes(rels: Relation[], at: Map<string, NetNode>): Map<string, Lane> {
  const byGap = new Map<number, Relation[]>();
  for (const r of rels) {
    if (isDirect(ends(at.get(r.pred)!, at.get(r.succ)!, r.type))) continue;
    const row = at.get(r.succ)!.row;
    byGap.set(row, [...(byGap.get(row) ?? []), r]);
  }
  const out = new Map<string, Lane>();
  for (const list of byGap.values()) {
    const key = (r: Relation) => [at.get(r.succ)!.col, at.get(r.pred)!.col, edgeKey(r)] as const;
    list.sort((p, q) => {
      const [a, b] = [key(p), key(q)];
      return a[0] - b[0] || a[1] - b[1] || (a[2] < b[2] ? -1 : a[2] > b[2] ? 1 : 0);
    });
    list.forEach((r, i) => out.set(edgeKey(r), { i, n: list.length }));
  }
  return out;
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
  const laneOf = lanes(rels, at);
  const edges = rels.map((r) => {
    const lane = laneOf.get(edgeKey(r)) ?? { i: 0, n: 1 };
    return {
      from: r.pred, to: r.succ, type: r.type, lag: r.lag, label: relLabel(r.type, r.lag), lane,
      critical: byId.get(r.pred)!.critical && byId.get(r.succ)!.critical,
      points: route(at.get(r.pred)!, at.get(r.succ)!, r.type, lane),
    };
  });
  const span = (n: number, size: number, gap: number) => (n > 0 ? n * size + (n - 1) * gap : 0);
  return { nodes, edges, width: 2 * PAD + span(cols.length, CARD_W, GAP_X), height: 2 * PAD + span(maxRow + 1, CARD_H, GAP_Y) };
}
