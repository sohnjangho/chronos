import { expect, test } from 'vitest';
import { linkPath } from './layout';

const A = { x: 0, w: 100, row: 0 };

test('FS goes from the end of the predecessor to the start of the successor', () => {
  expect(linkPath(A, { x: 150, w: 50, row: 2 }, 'FS', 30)).toBe('M 100 15 H 106 V 75 H 150');
});

test('FS to a successor that starts before the predecessor ends routes around between the rows', () => {
  expect(linkPath(A, { x: 50, w: 50, row: 1 }, 'FS', 30)).toBe('M 100 15 H 106 V 30 H 44 V 45 H 50');
});

test('FS upward routes along the bottom edge of the target row', () => {
  expect(linkPath({ x: 0, w: 100, row: 3 }, { x: 50, w: 50, row: 1 }, 'FS', 30)).toBe('M 100 105 H 106 V 60 H 44 V 45 H 50');
});

test('SS leaves and enters on the left of both starts', () => {
  expect(linkPath({ x: 20, w: 100, row: 0 }, { x: 50, w: 50, row: 1 }, 'SS', 30)).toBe('M 20 15 H 14 V 45 H 50');
});

test('FF leaves and enters on the right of both ends', () => {
  expect(linkPath(A, { x: 0, w: 120, row: 1 }, 'FF', 30)).toBe('M 100 15 H 126 V 45 H 120');
});

test('SF goes from the predecessor start to the successor end', () => {
  expect(linkPath({ x: 200, w: 50, row: 0 }, { x: 0, w: 100, row: 1 }, 'SF', 30)).toBe('M 200 15 H 194 V 45 H 100');
  expect(linkPath({ x: 50, w: 50, row: 0 }, { x: 0, w: 100, row: 1 }, 'SF', 30)).toBe('M 50 15 H 44 V 30 H 106 V 45 H 100');
});

test('coordinates are rounded to one decimal', () => {
  expect(linkPath({ x: 0, w: 10.123, row: 0 }, { x: 40.06, w: 5, row: 1 }, 'FS', 30)).toBe('M 10.1 15 H 16.1 V 45 H 40.1');
});

test('back-to-back FS links drop straight without protruding right', () => {
  expect(linkPath(A, { x: 100, w: 50, row: 2 }, 'FS', 30)).toBe('M 100 15 V 75 H 100');
  expect(linkPath(A, { x: 106, w: 50, row: 2 }, 'FS', 30)).toBe('M 100 15 H 103 V 75 H 106');
});
