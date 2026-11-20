// 표의 선행 칸 글("A2010, A1040 SS+15") ↔ 선행 목록.
import type { PredItem, RelType } from './scheduleApi';

export class ParseError extends Error {}

// ID [종류[±간격]] — 종류가 없으면 FS 0, 간격이 없으면 0. 종류는 소문자도 받는다.
// ID 는 서버에서 자유 글이다(소문자·하이픈·한글). 띄어쓰기·쉼표가 든 ID 는 이 칸이 아니라 관계 패널에서 고른다.
const PART = /^(\S+)(?:\s+(FS|SS|FF|SF)([+-]\d+)?)?$/i;
// 종류 없이 간격만 붙은 글(A1+3).
const LAG_ONLY = /^(\S+?)([+-]\d+)$/;

/** ids 를 주면 그 목록과 정확히(대소문자 구분) 맞춰 본다. 없는 ID 는 이름을 짚어 거절한다. */
function check(part: string, pred: string, ids: ReadonlySet<string> | undefined) {
  if (!ids || ids.has(pred)) return;
  const lag = LAG_ONLY.exec(part);
  if (lag) throw new ParseError(`관계 종류가 빠졌습니다: ${part} (예: ${lag[1]} SS${lag[2]})`);
  throw new ParseError(`없는 액티비티입니다: ${pred}`);
}

/**
 * 쉼표로 나눈 선행 목록. 빈 글은 선행 없음. 꼴이 틀리면 ParseError("선행 형식이 맞지 않습니다: …").
 * ids(지금 일정의 액티비티 ID)를 주면 없는 ID 도 ParseError("없는 액티비티입니다: …" 또는 "관계 종류가 빠졌습니다: …").
 */
export function parse(text: string, ids?: ReadonlySet<string>): PredItem[] {
  return text
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => {
      const m = PART.exec(part);
      if (!m) throw new ParseError(`선행 형식이 맞지 않습니다: ${part}`);
      check(part, m[1], ids);
      return { pred: m[1], type: (m[2]?.toUpperCase() ?? 'FS') as RelType, lag: m[3] ? Number(m[3]) : 0 };
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
