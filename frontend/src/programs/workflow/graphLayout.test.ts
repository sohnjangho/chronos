import { expect, test } from 'vitest';
import { layout, type LayoutStep } from './graphLayout';

/** n개 단계. parallel 에 적은 자리(0부터)는 같은 parallel_group 이다. */
function steps(n: number, { parallel = [] as number[] } = {}): LayoutStep[] {
  return Array.from({ length: n }, (_, i) => ({ id: String(i + 1), parallel_group: parallel.includes(i) ? 'g1' : null }));
}

test('graph layout wraps at four and stacks parallel steps', () => {
  const g = layout(steps(6, { parallel: [2, 3] }));
  expect(g.nodes[2].x).toBe(g.nodes[3].x);
  expect(g.nodes[2].y).not.toBe(g.nodes[3].y);
  expect(g.nodes[5].y).toBeGreaterThan(g.nodes[0].y);
});

test('steps go left to right in order, four to a row', () => {
  const g = layout(steps(5));
  const xs = g.nodes.map((n) => n.x);
  expect(xs[0]).toBeLessThan(xs[1]);
  expect(xs[1]).toBeLessThan(xs[2]);
  expect(xs[2]).toBeLessThan(xs[3]);
  expect(g.nodes[4]).toMatchObject({ x: xs[0] });
  expect(g.nodes.slice(0, 4).every((n) => n.y === g.nodes[0].y)).toBe(true);
  expect(g.nodes.map((n) => n.id)).toEqual(['1', '2', '3', '4', '5']);
});

test('edges join each slot to the next, fanning out to and in from parallel steps', () => {
  const g = layout(steps(4, { parallel: [1, 2] }));
  expect(g.edges).toEqual([
    { from: '1', to: '2' },
    { from: '1', to: '3' },
    { from: '2', to: '4' },
    { from: '3', to: '4' },
  ]);
});

test('a stacked slot pushes the next row down', () => {
  const flat = layout(steps(5));
  const tall = layout(steps(6, { parallel: [1, 2] }));
  expect(tall.nodes[5].y).toBeGreaterThan(flat.nodes[4].y);
  expect(tall.height).toBeGreaterThan(flat.height);
});

test('fewer columns per row when the pane is narrow', () => {
  const g = layout(steps(3), 1);
  expect(new Set(g.nodes.map((n) => n.x)).size).toBe(1);
  expect(g.nodes[2].y).toBeGreaterThan(g.nodes[1].y);
});

test('non-adjacent steps with the same group are not stacked together', () => {
  const g = layout([{ id: '1', parallel_group: 'a' }, { id: '2', parallel_group: null }, { id: '3', parallel_group: 'a' }]);
  expect(new Set(g.nodes.map((n) => n.x)).size).toBe(3);
});
