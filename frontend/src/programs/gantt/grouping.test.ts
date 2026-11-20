import { expect, test } from 'vitest';
import { makeView } from './testKit';
import { groupKeys, rowsFor } from './grouping';

const view = makeView();
const viewTwoResources = makeView({
  activities: makeView().activities.map((a) =>
    a.id === 'A2020' ? { ...a, resources: ['crane', 'rebar'] } : a.id === 'A1040' ? { ...a, resources: ['crane'] } : a,
  ),
  resources: [
    { id: 'crane', name: '타워크레인', unit: '대', capacity: 1 },
    { id: 'rebar', name: '철근공', unit: '명', capacity: 10 },
  ],
});

test('group by resource puts shared activity under each resource', () => {
  const rows = rowsFor(viewTwoResources, 'resource', new Set());
  expect(rows.filter((r) => r.activity?.id === 'A2020')).toHaveLength(2);
});

test('collapsed group hides children but keeps summary span', () => {
  const rows = rowsFor(view, 'wbs', new Set(['2']));
  expect(rows.find((r) => r.key === '2')!.spanFinish).toBe('2027-07-14');
  expect(rows.some((r) => r.activity?.id === 'A2020')).toBe(false);
});

test('wbs rows are the tree in order with milestones marked and the activity count', () => {
  const rows = rowsFor(view, 'wbs', new Set());
  expect(rows.slice(0, 3).map((r) => [r.key, r.kind, r.depth])).toEqual([
    ['1', 'group', 0],
    ['A1010', 'milestone', 1],
    ['A1020', 'activity', 1],
  ]);
  const g = rows[0];
  expect([g.label, g.count, g.open, g.spanStart, g.spanFinish]).toEqual(['1 기초', 4, true, '2027-03-02', '2027-04-09']);
  expect(rows.find((r) => r.key === 'A4030')!.kind).toBe('milestone');
  expect(rows).toHaveLength(15);
});

test('nested wbs groups sit under their parent and the parent span covers them', () => {
  const v = makeView({
    wbs: [
      { code: '1', name: '기초', parent: null },
      { code: '2', name: '골조', parent: null },
      { code: '2.1', name: '지하', parent: '2' },
      { code: '3', name: '외장·설비', parent: null },
      { code: '4', name: '마감', parent: null },
    ],
    activities: makeView().activities.map((a) => (a.id === 'A2010' ? { ...a, wbs: '2.1' } : a)),
  });
  const rows = rowsFor(v, 'wbs', new Set());
  const i = rows.findIndex((r) => r.key === '2');
  expect(rows.slice(i, i + 4).map((r) => [r.key, r.depth])).toEqual([
    ['2', 0],
    ['A2020', 1],
    ['2.1', 1],
    ['A2010', 2],
  ]);
  expect(rows[i].spanStart).toBe('2027-04-12');
  expect(rows.filter((r) => r.key !== '2' && r.kind === 'group' && r.depth === 0)).toHaveLength(3);
  expect(rowsFor(v, 'wbs', new Set(['2'])).some((r) => r.key === '2.1')).toBe(false);
});

test('resource groups: one lane per key resource with its activities, then 자원 없음', () => {
  const rows = rowsFor(viewTwoResources, 'resource', new Set());
  const groups = rows.filter((r) => r.kind === 'group');
  expect(groups.map((g) => [g.key, g.label, g.count])).toEqual([
    ['res:crane', '타워크레인 (1대)', 2],
    ['res:rebar', '철근공 (10명)', 1],
    ['res:', '자원 없음', 9],
  ]);
  expect(groups[0].lane!.map((a) => a.id)).toEqual(['A1040', 'A2020']);
  expect([groups[0].spanStart, groups[0].spanFinish]).toEqual(['2027-04-05', '2027-07-14']);
  const keys = rows.map((r) => r.key);
  expect(new Set(keys).size).toBe(keys.length);
  expect(rows[1]).toMatchObject({ key: 'res:crane/A1040', depth: 1, kind: 'activity' });
});

test('collapsing a resource lane keeps the lane bars on the group row', () => {
  const rows = rowsFor(viewTwoResources, 'resource', new Set(['res:crane']));
  expect(rows[0]).toMatchObject({ key: 'res:crane', open: false });
  expect(rows[0].lane!.map((a) => a.id)).toEqual(['A1040', 'A2020']);
  expect(rows[1].key).toBe('res:rebar');
});

test('an unknown resource id gets its own lane named by the id', () => {
  const v = makeView({ activities: makeView().activities.map((a) => (a.id === 'A3010' ? { ...a, resources: ['lift'] } : a)) });
  const groups = rowsFor(v, 'resource', new Set()).filter((r) => r.kind === 'group');
  expect(groups.map((g) => g.label)).toEqual(['타워크레인 (1대)', 'lift', '자원 없음']);
});

test('groupKeys lists every group key for 모두 접기', () => {
  expect(groupKeys(view, 'wbs')).toEqual(['1', '2', '3', '4']);
  expect(groupKeys(viewTwoResources, 'resource')).toEqual(['res:crane', 'res:rebar', 'res:']);
});
