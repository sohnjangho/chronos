// 에이전트 구조 그림의 칸 자리와 선(시안 DevConsoleA A안). 폭에 맞춰 자리를 다시 잡는다:
// 넓으면 [컨텍스트 재료 | 흐름 | 곁 칸] 세 줄, 좁으면 재료를 곁 칸 줄 위쪽(요청 받기·컨텍스트 조립 옆)으로 옮겨 두 줄.
// 흐름은 위에서 아래로 한 줄: 요청 받기 → 컨텍스트 조립 → 스킬 찾기 → 워크플로우 짜기 → 판단 → 조건 점검 → 승인 판단 → 응답·기록.
import type { NodeKey, NodeState } from './devApi';

export interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

export type SideKey = 'skillrun' | 'inbox';
export type SourceKey = 'src0' | 'src1' | 'src2' | 'src3' | 'src4';
export type BoxKey = NodeKey | SideKey | SourceKey;

/** 컨텍스트 재료 다섯 칸 — 서버의 재료 일곱(trace.CONTEXT_PARTS)을 묶은 것. */
export const SOURCES: { key: SourceKey; label: string; parts: string[] }[] = [
  { key: 'src0', label: '지시문·정밀도', parts: ['지시문', '정밀도'] },
  { key: 'src1', label: '분야 지식', parts: ['분야 지식'] },
  { key: 'src2', label: '상황·파일·날짜', parts: ['지금 상황', '붙인 파일', '날짜 도우미'] },
  { key: 'src3', label: '대화 기록', parts: ['대화'] },
  { key: 'src4', label: '도구 목록', parts: ['도구 목록'] },
];

const FLOW: NodeKey[] = ['request', 'context', 'skill', 'plan', 'judge', 'check', 'approval', 'respond'];
const NODE_H = 50;
const TOP = 16;
const STEP = 80;
/** 판단 ⇄ 도구 줄과 되돌아감 글이 들어갈 자리. */
const extra = (row: number) => (row >= 4 ? 10 : 0) + (row >= 5 ? 30 : 0);
const rowY = (row: number) => TOP + row * STEP + extra(row);
const SRC_W = 150;
const MAIN_W = 190;
const SIDE_W = 170;
export const WIDE_MIN = 32 + SRC_W + 50 + MAIN_W + 100 + SIDE_W;

function columns(width: number) {
  if (width >= WIDE_MIN) {
    const spare = width - WIDE_MIN;
    const gapL = 50 + Math.min(spare * 0.3, 70);
    const gapR = 100 + Math.min(spare * 0.3, 60);
    const left = Math.max(16, (width - (SRC_W + gapL + MAIN_W + gapR + SIDE_W)) / 2);
    return { wide: true, src: left, main: left + SRC_W + gapL, mainW: MAIN_W, side: left + SRC_W + gapL + MAIN_W + gapR, sideW: SIDE_W };
  }
  const pad = 8;
  const gap = Math.min(Math.max((width - 2 * pad) * 0.2, 60), 110);
  const col = Math.floor((width - 2 * pad - gap) / 2);
  const mainW = Math.min(col, MAIN_W);
  const sideW = Math.min(col, SIDE_W);
  const left = Math.max(pad, (width - (mainW + gap + sideW)) / 2);
  return { wide: false, src: left + mainW + gap, main: left, mainW, side: left + mainW + gap, sideW };
}

function sourceBoxes(c: ReturnType<typeof columns>): Record<SourceKey, Box> {
  const h = c.wide ? 24 : 22;
  const top = c.wide ? rowY(1) + NODE_H / 2 - (5 * h + 4 * 8) / 2 : rowY(0);
  const space = c.wide ? 8 : (rowY(1) + NODE_H - rowY(0) - 5 * h) / 4;
  const w = c.wide ? SRC_W : c.sideW;
  return Object.fromEntries(SOURCES.map((s, i) => [s.key, { x: c.src, y: top + i * (h + space), w, h }])) as Record<SourceKey, Box>;
}

/** 폭 width 의 그림에서 칸마다 자리. 모든 칸은 [0, width] 안에 있고 겹치지 않는다. */
export function nodeBoxes(width: number): Record<BoxKey, Box> {
  const c = columns(width);
  const main = (row: number): Box => ({ x: c.main, y: rowY(row), w: c.mainW, h: NODE_H });
  const side = (row: number): Box => ({ x: c.side, y: rowY(row), w: c.sideW, h: NODE_H });
  const flow = Object.fromEntries(FLOW.map((k, i) => [k, main(i)])) as Record<Exclude<NodeKey, 'tool'>, Box>;
  return { ...flow, tool: side(4), skillrun: side(2), inbox: side(6), ...sourceBoxes(c) };
}

export interface Edge {
  from: BoxKey;
  to: BoxKey;
  label?: string;
  /** past = 지나간 길, now = 지금 칸으로 들어가는 길, todo = 아직(또는 기록으로 알 수 없는 길). */
  state: 'past' | 'now' | 'todo';
  /** 추적에 남지 않는 길(늘 todo, 점선). */
  unknown?: true;
}

const EDGES: { from: BoxKey; to: BoxKey; label?: string; unknown?: true }[] = [
  ...SOURCES.map((s) => ({ from: s.key, to: 'context' as const })),
  { from: 'request', to: 'context' },
  { from: 'context', to: 'skill' },
  { from: 'skill', to: 'plan', label: '없음' },
  { from: 'skill', to: 'skillrun', label: '맞는 스킬 있음' },
  { from: 'plan', to: 'judge' },
  { from: 'judge', to: 'tool', label: '호출' },
  { from: 'tool', to: 'judge', label: '결과 관찰' },
  { from: 'judge', to: 'check' },
  // 위반으로 되돌아갔는지, 승인함으로 갔는지는 추적에 남지 않는다 — 늘 불을 켜지 않는다.
  { from: 'check', to: 'judge', label: '위반 → 고쳐서 다시', unknown: true },
  { from: 'check', to: 'approval' },
  { from: 'approval', to: 'inbox', label: '중요한 변경', unknown: true },
  { from: 'approval', to: 'respond' },
];

/** 그릴 선과 그 상태. 들른 칸끼리의 선과 실제 실행된 분기(edgesLit)에 불을 켠다. */
export function edgesFor(nodes: { key: NodeKey; state: NodeState }[], edgesLit: string[] = []): Edge[] {
  const state = new Map<string, NodeState>(nodes.map((n) => [n.key, n.state]));
  const litFlags = new Set(edgesLit);
  const sourceState = state.get('context');
  const of = (k: BoxKey) => (k.startsWith('src') ? sourceState : state.get(k));
  const visited = (s: NodeState | undefined) => s === 'past' || s === 'now';
  const skillPassed = visited(state.get('plan'));
  const passed = (k: BoxKey) => (k === 'skill' ? skillPassed : visited(of(k)));
  return EDGES.map(({ from, to, label, unknown }) => {
    const flagLit =
      (from === 'skill' && to === 'skillrun' && litFlags.has('skill_matched')) ||
      (from === 'check' && to === 'judge' && litFlags.has('check_repair')) ||
      (from === 'approval' && to === 'inbox' && litFlags.has('approval_inbox'));
    const lit = flagLit || (!unknown && passed(from) && passed(to));
    const s: Edge['state'] = !lit ? 'todo' : of(to) === 'now' ? 'now' : 'past';
    const isUnknown = unknown && !flagLit;
    return { from, to, ...(label && { label }), state: s, ...(isUnknown && { unknown: true as const }) };
  });
}

export interface EdgeShape {
  d: string;
  lx: number;
  ly: number;
  anchor: 'start' | 'middle';
}

const right = (b: Box) => b.x + b.w;
const cy = (b: Box) => b.y + b.h / 2;
const cx = (b: Box) => b.x + b.w / 2;

/** 선의 경로와 글 자리. 재료 → 컨텍스트는 버스 하나로 모인다. 판단 ⇄ 도구는 위·아래 두 줄. */
export function edgeShape(e: Pick<Edge, 'from' | 'to'>, boxes: Record<BoxKey, Box>): EdgeShape {
  const a = boxes[e.from];
  const b = boxes[e.to];
  if (e.from.startsWith('src')) {
    const leftOf = right(a) < b.x;
    const bus = leftOf ? (right(a) + b.x) / 2 : (right(b) + a.x) / 2;
    const d = leftOf ? `M${right(a)},${cy(a)} H${bus} V${cy(b)} H${b.x}` : `M${a.x},${cy(a)} H${bus} V${cy(b)} H${right(b)}`;
    return { d, lx: 0, ly: 0, anchor: 'start' };
  }
  if (e.from === 'tool') return { d: `M${a.x},${cy(a) + 8} H${right(b)}`, lx: (a.x + right(b)) / 2, ly: cy(a) + 22, anchor: 'middle' };
  if (e.to === 'tool') return { d: `M${right(a)},${cy(a) - 8} H${b.x}`, lx: (right(a) + b.x) / 2, ly: cy(a) - 14, anchor: 'middle' };
  if (b.x > right(a)) return { d: `M${right(a)},${cy(a)} H${b.x}`, lx: (right(a) + b.x) / 2, ly: cy(a) - 6, anchor: 'middle' };
  if (b.y < a.y) {
    const x = a.x + a.w * 0.8;
    return { d: `M${x},${a.y} V${b.y + b.h}`, lx: x + 6, ly: (a.y + b.y + b.h) / 2 + 4, anchor: 'start' };
  }
  return { d: `M${cx(a)},${a.y + a.h} V${b.y}`, lx: cx(a) + 6, ly: (a.y + a.h + b.y) / 2 + 4, anchor: 'start' };
}
