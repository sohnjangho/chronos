import { expect, test } from 'vitest';
import { scaleCurve, weekLabel } from './scurve';
import { P } from './testKit';

const box = { w: 800, h: 300, pad: 20 };

test('actual path stops at the data date and forecast starts there', () => {
  const s = scaleCurve(P.curve, box, '2027-03-03');
  expect(s.actual.split(/[ML]/).filter(Boolean)).toHaveLength(2);
  expect(s.forecast.startsWith(`M${s.dataDateX}`)).toBe(true);
  expect(s.yOf(100)).toBe(20);
});

test('the plan path has every point, x follows the dates and y the percent', () => {
  const s = scaleCurve(P.curve, box, '2027-03-03');
  expect(s.plan.split(/[ML]/).filter(Boolean)).toHaveLength(5);
  expect(s.plan.startsWith(`M20 ${s.yOf(0)}`)).toBe(true); // 첫 점 = 왼쪽 끝, 0%
  expect(s.plan.endsWith(`L780 ${s.yOf(100)}`)).toBe(true); // 끝 점 = 오른쪽 끝, 100%
  expect(s.yOf(0)).toBe(280);
  expect(s.dataDateX).toBe(Math.round((20 + (2 / 15) * 760) * 100) / 100); // 3/1 ~ 3/16 가운데 2일
  expect(s.forecast.split(/[ML]/).filter(Boolean)).toHaveLength(4);
});

test('bars span each period with its plan and actual share', () => {
  const s = scaleCurve(P.curve, box, '2027-03-03');
  expect(s.bars).toHaveLength(4); // 첫 점(0 에서의 차) 다음부터 기간마다 하나
  expect(s.bars.map((b) => [b.plan, b.actual])).toEqual([[20, 10], [30, null], [50, null], [0, null]]);
  expect(s.bars[0].x).toBe(20);
  expect(s.bars[0].x + s.bars[0].w).toBeCloseTo(s.dataDateX, 1);
});

test('a data date outside the curve is pinned to the edge', () => {
  expect(scaleCurve(P.curve, box, '2027-02-01').dataDateX).toBe(20);
  expect(scaleCurve(P.curve, box, '2027-05-01').dataDateX).toBe(780);
});

test('an empty curve gives empty paths', () => {
  const s = scaleCurve([], box, '2027-03-03');
  expect([s.plan, s.actual, s.forecast, s.bars]).toEqual(['', '', '', []]);
});

test('week label', () => expect(weekLabel('2027-06-01', '2027-03-01', '2027-11-24')).toBe('14주차 / 39주'));
