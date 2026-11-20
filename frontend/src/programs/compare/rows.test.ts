import { expect, test } from 'vitest';
import { deltaText, visibleRows } from './rows';
import { C } from './testKit';

test.each([
  [-3, '−3일'],
  [2, '+2일'],
  [0, '0'],
  [null, '—'],
])('delta %s', (n, t) => expect(deltaText(n)).toBe(t));

test('changed-only keeps every row that is not the same, in server order', () => {
  expect(visibleRows(C.rows, true).map((r) => r.activity_id)).toEqual(['B', 'E', 'C', 'M']);
  expect(visibleRows(C.rows, false).map((r) => r.activity_id)).toEqual(['A', 'B', 'E', 'C', 'M']);
});

test('added, removed and duration-only rows count as changed', () => {
  const rows = [
    { ...C.rows[0], activity_id: 'X', change: 'added' as const },
    { ...C.rows[0], activity_id: 'Y', change: 'removed' as const },
    { ...C.rows[0], activity_id: 'Z', change: 'duration' as const },
    C.rows[0],
  ];
  expect(visibleRows(rows, true).map((r) => r.activity_id)).toEqual(['X', 'Y', 'Z']);
});
