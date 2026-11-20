import { expect, test } from 'vitest';
import { addDays, barRect, dateAt, dayCount, makeScale, months, weekends, weeks, width, x, zoomed } from './scale';

test('one-day bar has one day width', () => {
  const s = makeScale('2027-03-01', '2027-03-31', 620, 0);
  expect(barRect(s, '2027-03-02', '2027-03-02').w).toBeCloseTo(s.pxPerDay);
});

test('bar x is monotonic and finish is inclusive', () => {
  const s = makeScale('2027-03-01', '2027-03-31', 620, 0);
  const r = barRect(s, '2027-03-01', '2027-03-03');
  expect(r.x).toBe(0);
  expect(r.w).toBeCloseTo(3 * s.pxPerDay);
  expect(x(s, '2027-03-10')).toBeGreaterThan(x(s, '2027-03-09'));
});

test('months label first with year', () => {
  expect(months(makeScale('2027-03-01', '2027-05-31', 900, 0)).map((m) => m.label)).toEqual(['2027년 3월', '4월', '5월']);
});

test('makeScale fits the inclusive range into the width and pads both sides', () => {
  const s = makeScale('2027-03-01', '2027-03-31', 620, 0);
  expect(s.pxPerDay).toBeCloseTo(20);
  expect(dayCount(s)).toBe(31);
  expect(width(s)).toBeCloseTo(620);
  const padded = makeScale('2027-03-08', '2027-03-14', 210, 7);
  expect(dayCount(padded)).toBe(21);
  expect(x(padded, '2027-03-08')).toBeCloseTo(7 * padded.pxPerDay);
});

test('months cover the whole width and January shows its year again', () => {
  const s = makeScale('2027-12-10', '2028-02-05', 570, 0);
  const ms = months(s);
  expect(ms.map((m) => m.label)).toEqual(['2027년 12월', '2028년 1월', '2월']);
  expect(ms[0].x).toBe(0);
  expect(ms.reduce((n, m) => n + m.w, 0)).toBeCloseTo(width(s));
});

test('weeks start on Mondays with M/D labels', () => {
  const s = makeScale('2027-03-03', '2027-03-20', 180, 0); // 3/3 수요일
  expect(weeks(s).map((w) => w.label)).toEqual(['3/8', '3/15']);
  expect(weeks(s)[0].x).toBeCloseTo(x(s, '2027-03-08'));
});

test('weekends lists Saturdays and Sundays inside the range', () => {
  const s = makeScale('2027-03-05', '2027-03-08', 40, 0); // 금~월
  expect(weekends(s).map((d) => d.date)).toEqual(['2027-03-06', '2027-03-07']);
});

test('dateAt is the day under a pixel and inverts x', () => {
  const s = makeScale('2027-03-01', '2027-03-31', 620, 0);
  expect(dateAt(s, 0)).toBe('2027-03-01');
  expect(dateAt(s, 19.9)).toBe('2027-03-01');
  expect(dateAt(s, 20)).toBe('2027-03-02');
  expect(dateAt(s, x(s, '2027-03-17'))).toBe('2027-03-17');
});

test('addDays crosses months and years', () => {
  expect(addDays('2027-02-27', 3)).toBe('2027-03-02');
  expect(addDays('2027-12-31', 1)).toBe('2028-01-01');
  expect(addDays('2027-03-02', -2)).toBe('2027-02-28');
});

test('zoomed keeps the range and multiplies pxPerDay', () => {
  const s = makeScale('2027-03-01', '2027-03-31', 620, 0);
  const z = zoomed(s, 1.25);
  expect(z.pxPerDay).toBeCloseTo(25);
  expect(z.start).toEqual(s.start);
  expect(z.end).toEqual(s.end);
});

test('weekends follow the working week: 6 days → only Sundays, 7 days → none', () => {
  const s = makeScale('2027-03-05', '2027-03-08', 40, 0); // 금~월
  expect(weekends(s, 6).map((d) => d.date)).toEqual(['2027-03-07']);
  expect(weekends(s, 7)).toEqual([]);
});
