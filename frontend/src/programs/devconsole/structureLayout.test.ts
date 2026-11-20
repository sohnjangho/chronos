import { describe, expect, test } from 'vitest';
import type { NodeKey, NodeState } from './devApi';
import { edgesFor, nodeBoxes, type Box } from './structureLayout';

const overlap = (a: Box, b: Box) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
const MAIN: NodeKey[] = ['request', 'context', 'skill', 'plan', 'judge', 'check', 'approval', 'respond'];

describe.each([1160, 900, 560, 420, 330])('nodeBoxes(%i)', (width) => {
  const boxes = nodeBoxes(width);
  const all = Object.entries(boxes);

  test('has the nine nodes, five context sources and the two side boxes', () => {
    expect(Object.keys(boxes).sort()).toEqual(
      ['approval', 'check', 'context', 'inbox', 'judge', 'plan', 'request', 'respond', 'skill', 'skillrun', 'src0', 'src1', 'src2', 'src3', 'src4', 'tool'].sort(),
    );
  });

  test('every box fits the width and no two boxes overlap', () => {
    for (const [k, b] of all) {
      expect(b.x, k).toBeGreaterThanOrEqual(0);
      expect(b.x + b.w, k).toBeLessThanOrEqual(width);
    }
    for (const [i, [ka, a]] of all.entries()) for (const [kb, b] of all.slice(i + 1)) expect(overlap(a, b), `${ka}·${kb}`).toBe(false);
  });

  test('the main flow runs top to bottom in one column with the side boxes beside it', () => {
    const ys = MAIN.map((k) => boxes[k].y);
    expect(ys).toEqual([...ys].sort((a, b) => a - b));
    expect(new Set(MAIN.map((k) => boxes[k].x)).size).toBe(1);
    expect(boxes.tool.y).toBe(boxes.judge.y);
    expect(boxes.tool.x).toBeGreaterThan(boxes.judge.x + boxes.judge.w);
    expect(boxes.skillrun.y).toBe(boxes.skill.y);
    expect(boxes.inbox.y).toBe(boxes.approval.y);
  });
});

test('wide layout puts the context sources left of the flow, narrow layout beside it on the right', () => {
  expect(nodeBoxes(1160).src0.x + nodeBoxes(1160).src0.w).toBeLessThan(nodeBoxes(1160).context.x);
  expect(nodeBoxes(420).src0.x).toBeGreaterThan(nodeBoxes(420).context.x + nodeBoxes(420).context.w);
});

describe('edgesFor', () => {
  const states = (s: Partial<Record<NodeKey, NodeState>>) =>
    (['request', 'context', 'skill', 'plan', 'judge', 'tool', 'check', 'approval', 'respond'] as NodeKey[]).map((key) => ({
      key,
      state: key === 'skill' ? ('skipped' as const) : (s[key] ?? 'todo'),
    }));
  const running = states({ request: 'past', context: 'past', plan: 'past', judge: 'past', tool: 'now' });
  const find = (edges: ReturnType<typeof edgesFor>, from: string, to: string) => edges.find((e) => e.from === from && e.to === to);

  test('the drawn path follows the visited nodes and the edge into the now node is lit as now', () => {
    const edges = edgesFor(running);
    expect(find(edges, 'request', 'context')?.state).toBe('past');
    expect(find(edges, 'context', 'skill')?.state).toBe('past');
    expect(find(edges, 'skill', 'plan')).toMatchObject({ state: 'past', label: '없음' });
    expect(find(edges, 'judge', 'tool')).toMatchObject({ state: 'now', label: '호출' });
    expect(find(edges, 'judge', 'check')?.state).toBe('todo');
    expect(find(edges, 'src0', 'context')?.state).toBe('past');
  });

  test('paths that are never recorded stay unlit', () => {
    const all = edgesFor(states({ request: 'past', context: 'past', plan: 'past', judge: 'past', tool: 'past', check: 'past', approval: 'past', respond: 'past' }));
    expect(find(all, 'skill', 'skillrun')).toMatchObject({ state: 'todo', label: '맞는 스킬 있음' });
    expect(find(all, 'check', 'judge')).toMatchObject({ state: 'todo', label: '위반 → 고쳐서 다시', unknown: true });
    expect(find(all, 'approval', 'inbox')).toMatchObject({ state: 'todo', unknown: true });
    expect(find(all, 'tool', 'judge')).toMatchObject({ state: 'past', label: '결과 관찰' });
    expect(all.filter((e) => e.unknown).map((e) => `${e.from}-${e.to}`)).toEqual(['check-judge', 'approval-inbox']);
  });
});
