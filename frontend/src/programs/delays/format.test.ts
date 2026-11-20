import { expect, test } from 'vitest';
import { impactDays, shortPair, won } from './format';

test.each([
  [6_200_000, '620만 원'],
  [12_400_000, '1,240만 원'],
  [null, '—'],
  [9_000, '9,000원'],
  [0, '0원'],
  [15_000, '2만 원'],
])('won %s', (v, t) => expect(won(v)).toBe(t));

test('impact days carry a plus only when the finish moved later', () => {
  expect(impactDays(2)).toBe('+2일');
  expect(impactDays(0)).toBe('0일');
  expect(impactDays(-1)).toBe('-1일');
});

test('date pairs drop the year only when both are in the same year', () => {
  expect(shortPair('2027-11-24', '2027-11-28')).toEqual(['11.24', '11.28']);
  expect(shortPair('2027-12-30', '2028-01-04')).toEqual(['2027.12.30', '2028.01.04']);
});
