// 표의 선행 칸 글("A2010, A1040 SS+15") ↔ 선행 목록.
import type { PredItem, RelType } from '../scheduleApi';

export class ParseError extends Error {}

// ID [종류[±간격]] — 종류가 없으면 FS 0, 간격이 없으면 0. ID 는 대문자·숫자·_·. 만(A1+3 처럼 종류 없는 간격,
// 소문자 ID 는 틀린 글로 본다). 종류는 소문자도 받는다.
const PART = /^([A-Z0-9][A-Z0-9_.]*)(?:\s+(FS|SS|FF|SF)([+-]\d+)?)?$/;
const TYPE = /^(\S+\s+)(fs|ss|ff|sf)/i;

/** 쉼표로 나눈 선행 목록. 빈 글은 선행 없음. 틀리면 ParseError("선행 형식이 맞지 않습니다: …"). */
export function parse(text: string): PredItem[] {
  return text
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => {
      const m = PART.exec(part.replace(TYPE, (_, id: string, type: string) => id + type.toUpperCase()));
      if (!m) throw new ParseError(`선행 형식이 맞지 않습니다: ${part}`);
      return { pred: m[1], type: (m[2] ?? 'FS') as RelType, lag: m[3] ? Number(m[3]) : 0 };
    });
}

/** FS 0 은 ID 만, 간격 0 은 종류까지, 나머지는 "A1 SS+15". */
export function format(items: PredItem[]): string {
  return items
    .map(({ pred, type, lag }) => {
      if (type === 'FS' && lag === 0) return pred;
      if (lag === 0) return `${pred} ${type}`;
      return `${pred} ${type}${lag > 0 ? '+' : ''}${lag}`;
    })
    .join(', ');
}
