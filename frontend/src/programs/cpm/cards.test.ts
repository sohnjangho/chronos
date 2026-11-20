import { expect, test } from 'vitest';
import { cardRows, planChip, statusLabel } from './cards';
import { a } from './testKit';

test.each([['late +4', '+4일'], ['early -1', '−1일'], ['on_plan', '계획 내'], ['new', '새 액티비티'], ['done', '완료']])('plan chip %s', (s, t) =>
  expect(planChip(s).text).toBe(t),
);

test('plan chip tones: late is danger, early and on plan are success, the rest neutral', () => {
  expect(['late +4', 'early -1', 'on_plan', 'new', 'done', 'odd'].map((s) => planChip(s).tone)).toEqual(['danger', 'success', 'success', 'neutral', 'neutral', 'neutral']);
  expect(planChip('odd').text).toBe('odd');
});

test('status comes from the actual dates', () => {
  expect(statusLabel(a('A', { actual_start: '2027-03-02', actual_finish: '2027-03-05' }))).toBe('완료');
  expect(statusLabel(a('A', { actual_start: '2027-03-02' }))).toBe('진행 중');
  expect(statusLabel(a('A'))).toBe('미착수');
});

const x = a('A2020', {
  es: '2027-05-11', ef: '2027-07-18', ls: '2027-05-11', lf: '2027-07-18', od: 50, rd: 32, tf: 0, progress: 0.36,
  plan_start: '2027-05-06', plan_finish: '2027-07-14',
});
const all = { plan: true, actual: true, cpm: true };

test('card rows with every layer on', () =>
  expect(cardRows(x, all)).toEqual([
    { label: 'ES/EF', value: '05.11 ~ 07.18' },
    { label: 'LS/LF', value: '05.11 ~ 07.18' },
    { label: 'OD/RD', value: '50일 / 32일' },
    { label: 'TF/진도', value: '0일 / 36%' },
    { label: 'Plan', value: '05.06 ~ 07.14' },
  ]));

test('turning layers off drops their rows', () => {
  expect(cardRows(x, { ...all, cpm: false }).map((row) => row.label)).toEqual(['OD/RD', '진도', 'Plan']);
  expect(cardRows(x, { ...all, actual: false }).find((row) => row.label === 'TF')).toEqual({ label: 'TF', value: '0일' });
  expect(cardRows(x, { ...all, plan: false }).map((row) => row.label)).toEqual(['ES/EF', 'LS/LF', 'OD/RD', 'TF/진도']);
  expect(cardRows(x, { plan: false, actual: false, cpm: false }).map((row) => row.label)).toEqual(['OD/RD']);
});

test('missing values say so instead of guessing', () => {
  const bare = a('N', { rd: null, ls: undefined, lf: undefined, plan_start: null, plan_finish: null });
  const rows = Object.fromEntries(cardRows(bare, all).map((row) => [row.label, row.value]));
  expect(rows['OD/RD']).toBe('3일 / —');
  expect(rows['LS/LF']).toBe('—');
  expect(rows.Plan).toBe('Plan 없음');
});
