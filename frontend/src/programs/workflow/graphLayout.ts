// 단계 그림 자리: 차례대로 가로 perRow(기본 4)칸씩 줄바꿈. 바로 이어진 단계의 parallel_group 이 같으면
// 한 칸에 세로로 쌓는다(한 답이 함께 부른 도구). 선은 칸에서 다음 칸으로(쌓인 칸은 모두에서·모두로).

export interface LayoutStep {
  id: string;
  parallel_group?: string | number | null;
}

export interface LayoutNode {
  id: string;
  x: number;
  y: number;
  /** 몇째 줄인가(0부터). 줄을 넘어가는 선을 그릴 때 쓴다. */
  row: number;
}

export interface LayoutEdge {
  from: string;
  to: string;
}

export interface Layout {
  nodes: LayoutNode[];
  edges: LayoutEdge[];
  width: number;
  height: number;
}

export const NODE_W = 160;
export const NODE_H = 76;
export const GAP_X = 24;
export const GAP_Y = 14;
export const ROW_GAP = 34;
export const PAD = 16;

/** 바로 이어진 같은 묶음끼리 한 칸. */
function slots(steps: LayoutStep[]): LayoutStep[][] {
  const out: LayoutStep[][] = [];
  for (const s of steps) {
    const last = out.at(-1);
    const g = s.parallel_group;
    if (last && g !== null && g !== undefined && last[0].parallel_group === g) last.push(s);
    else out.push([s]);
  }
  return out;
}

/** 이 폭에 들어가는 한 줄 칸 수(1~4). */
export function columnsFor(width: number): number {
  return Math.max(1, Math.min(4, Math.floor((width - 2 * PAD + GAP_X) / (NODE_W + GAP_X))));
}

export function layout(steps: LayoutStep[], perRow = 4): Layout {
  const groups = slots(steps);
  const nodes: LayoutNode[] = [];
  let top = PAD;
  let width = 0;
  for (let start = 0; start < groups.length; start += perRow) {
    const row = groups.slice(start, start + perRow);
    const r = start / perRow;
    row.forEach((g, col) => g.forEach((s, k) => nodes.push({ id: s.id, x: PAD + col * (NODE_W + GAP_X), y: top + k * (NODE_H + GAP_Y), row: r })));
    const tall = Math.max(...row.map((g) => g.length));
    width = Math.max(width, 2 * PAD + row.length * NODE_W + (row.length - 1) * GAP_X);
    top += tall * NODE_H + (tall - 1) * GAP_Y + ROW_GAP;
  }
  const edges = groups.flatMap((g, i) => (i + 1 < groups.length ? g.flatMap((a) => groups[i + 1].map((b) => ({ from: a.id, to: b.id }))) : []));
  return { nodes, edges, width, height: groups.length ? top - ROW_GAP + PAD : 0 };
}
