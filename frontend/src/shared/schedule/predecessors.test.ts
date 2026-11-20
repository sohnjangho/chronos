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
  expect(parse('  A1 ss+3 ,B2,  ')).toEqual([
    { pred: 'A1', type: 'SS', lag: 3 },
    { pred: 'B2', type: 'FS', lag: 0 },
  ]);
});

// fix 2 N1: ID 는 자유 글(소문자·하이픈·한글도 된다). ID 목록을 주면 그 목록과 정확히(대소문자 구분) 맞춰 본다.
const IDS = new Set(['A1', 'A2010', 'a1040', 'B-12', '가설-01']);

test('lower-case, hyphenated and Korean ids are accepted when the activity exists', () => {
  expect(parse('a1040 ss+2, B-12, 가설-01 FF-1', IDS)).toEqual([
    { pred: 'a1040', type: 'SS', lag: 2 },
    { pred: 'B-12', type: 'FS', lag: 0 },
    { pred: '가설-01', type: 'FF', lag: -1 },
  ]);
});

test('without an id list the token is not checked against activities', () => {
  expect(parse('a1')).toEqual([{ pred: 'a1', type: 'FS', lag: 0 }]);
});

test.each([
  ['a1', '없는 액티비티입니다: a1'],
  ['A2010, a2010', '없는 액티비티입니다: a2010'],
  ['A1+3', '관계 종류가 빠졌습니다: A1+3 (예: A1 SS+3)'],
  ['A2010-2', '관계 종류가 빠졌습니다: A2010-2 (예: A2010 SS-2)'],
  ['A9 SS+1', '없는 액티비티입니다: A9'],
])('with an id list %s is rejected by name', (text, message) => {
  expect(() => parse(text, IDS)).toThrow(ParseError);
  expect(() => parse(text, IDS)).toThrow(message);
});

test('an id that really contains a sign and digits is still found', () => {
  expect(parse('B-12', IDS)).toEqual([{ pred: 'B-12', type: 'FS', lag: 0 }]);
});

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
