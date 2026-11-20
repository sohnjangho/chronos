import { expect, test } from 'vitest';
import { format, parse, ParseError } from './predecessors';

// 지시서 시험
test.each([
  ['A1', [{ pred: 'A1', type: 'FS', lag: 0 }]],
  ['A1 SS+15', [{ pred: 'A1', type: 'SS', lag: 15 }]],
  ['A1 FF-2, B2', [{ pred: 'A1', type: 'FF', lag: -2 }, { pred: 'B2', type: 'FS', lag: 0 }]],
  ['', []],
])('parse %s', (s, out) => expect(parse(s)).toEqual(out));
test('parse rejects garbage', () => expect(() => parse('A1 XX+1')).toThrow('선행 형식이 맞지 않습니다'));
test('format is the inverse of parse', () => expect(format(parse('A1 SS+15, B2'))).toBe('A1 SS+15, B2'));

// 더 본 것
test('the brief example parses into two items', () => {
  expect(parse('A2010, A1040 SS+15')).toEqual([
    { pred: 'A2010', type: 'FS', lag: 0 },
    { pred: 'A1040', type: 'SS', lag: 15 },
  ]);
});

test('lower-case types, spaces and a trailing comma are accepted', () => {
  expect(parse('  a1 ss+3 ,B2,  ')).toEqual([
    { pred: 'a1', type: 'SS', lag: 3 },
    { pred: 'B2', type: 'FS', lag: 0 },
  ]);
});

test('a type without a lag means lag 0', () => expect(parse('A1 SF')).toEqual([{ pred: 'A1', type: 'SF', lag: 0 }]));

test('the error names the part that is wrong and is a ParseError', () => {
  expect(() => parse('A1, B2 SS 15')).toThrow(ParseError);
  expect(() => parse('A1, B2 SS 15')).toThrow('선행 형식이 맞지 않습니다: B2 SS 15');
});

test('format writes FS 0 as the id only and keeps other types and lags', () => {
  expect(
    format([
      { pred: 'A1', type: 'FS', lag: 0 },
      { pred: 'A2', type: 'FS', lag: 3 },
      { pred: 'A3', type: 'SS', lag: 0 },
      { pred: 'A4', type: 'FF', lag: -2 },
    ]),
  ).toBe('A1, A2 FS+3, A3 SS, A4 FF-2');
});
