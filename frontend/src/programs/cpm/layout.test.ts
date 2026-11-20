import { expect, test } from 'vitest';
import { CARD_H, CARD_W, layoutNetwork, route } from './layout';
import { a, r, small, view } from './testKit';

const v = small();
const mid = CARD_H / 2;

test('columns follow the longest predecessor chain', () => {
  const n = Object.fromEntries(layoutNetwork(v, { mode: 'all' }).nodes.map((x) => [x.id, [x.x, x.y]]));
  expect(n).toEqual({ A: [24, 24], B: [368, 24], D: [368, 224], C: [712, 24] });
});

test('the picture is as large as the columns and rows it uses', () => {
  const g = layoutNetwork(v, { mode: 'all' });
  expect([g.width, g.height]).toEqual([24 * 2 + 3 * CARD_W + 2 * 96, 24 * 2 + 2 * CARD_H + 32]);
});

test('critical mode drops non-critical nodes and their edges', () => {
  const g = layoutNetwork(v, { mode: 'critical' });
  expect(g.nodes.map((x) => x.id)).toEqual(['A', 'B', 'C']);
  expect(g.edges.every((e) => e.from !== 'D' && e.to !== 'D')).toBe(true);
});

test('selected mode keeps direct neighbours', () => expect(layoutNetwork(v, { mode: 'selected', selected: 'D' }).nodes.map((x) => x.id).sort()).toEqual(['A', 'C', 'D']));

test('selected mode without a selection shows everything', () => expect(layoutNetwork(v, { mode: 'selected', selected: null }).nodes).toHaveLength(4));

test('edge label shows type and lag', () => {
  const g = layoutNetwork(v, { mode: 'all' });
  expect(g.edges.find((e) => e.from === 'D')!.label).toBe('SS+15');
  expect(g.edges.find((e) => e.from === 'A' && e.to === 'B')!.label).toBe('FS');
});

test('an edge is critical only when both ends are critical', () => {
  const g = layoutNetwork(v, { mode: 'all' });
  expect(g.edges.filter((e) => e.critical).map((e) => `${e.from}>${e.to}`)).toEqual(['A>B', 'B>C']);
});

test('the WBS filter keeps activities under that top group', () => {
  const nested = view(
    [a('A', { wbs: '1' }), a('B', { wbs: '2.1' }), a('C', { wbs: '2' })],
    [r('A', 'B'), r('B', 'C')],
    { wbs: [{ code: '1', name: '기초', parent: null }, { code: '2', name: '골조', parent: null }, { code: '2.1', name: '지상', parent: '2' }] },
  );
  const g = layoutNetwork(nested, { mode: 'all', wbs: '2' });
  expect(g.nodes.map((x) => [x.id, x.col])).toEqual([['B', 0], ['C', 1]]);
  expect(g.edges.map((e) => `${e.from}>${e.to}`)).toEqual(['B>C']);
});

test('FS runs from the predecessor right middle to the successor left middle', () => {
  const p = layoutNetwork(v, { mode: 'all' }).edges.find((e) => e.from === 'A' && e.to === 'B')!.points;
  expect(p[0]).toEqual([24 + CARD_W, 24 + mid]);
  expect(p.at(-1)).toEqual([368, 24 + mid]);
});

test('SS runs left to left, FF right to right, SF left to right, all with square bends', () => {
  const from = { x: 24, y: 24 };
  const to = { x: 368, y: 224 };
  const ends = (t: 'SS' | 'FF' | 'SF') => {
    const p = route(from, to, t);
    return [p[0], p.at(-1)];
  };
  expect(ends('SS')).toEqual([[24, 24 + mid], [368, 224 + mid]]);
  expect(ends('FF')).toEqual([[24 + CARD_W, 24 + mid], [368 + CARD_W, 224 + mid]]);
  expect(ends('SF')).toEqual([[24, 24 + mid], [368 + CARD_W, 224 + mid]]);
  for (const t of ['FS', 'SS', 'FF', 'SF'] as const) {
    const p = route(from, to, t);
    p.slice(1).forEach(([x, y], i) => expect(x === p[i][0] || y === p[i][1]).toBe(true));
  }
});

test('a line to a far column runs in the gap above the successor, not through cards', () => {
  const p = route({ x: 24, y: 24 }, { x: 712, y: 24 }, 'FS');
  const ys = p.map(([, y]) => y);
  expect(Math.min(...ys)).toBe(24 - 16);
});
