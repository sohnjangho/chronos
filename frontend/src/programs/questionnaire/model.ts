import type { QQuestion, QView } from './qApi';

/** 묶음 안 자리까지 붙인 질문(목차 차례 그대로 한 줄로). */
export interface Placed extends QQuestion {
  group: string;
  /** 묶음 안에서 몇 번째(1부터). */
  pos: number;
  /** 묶음의 질문 수. */
  size: number;
}

export function flatten(view: QView): Placed[] {
  return view.groups.flatMap((g) => g.questions.map((q, i) => ({ ...q, group: g.name, pos: i + 1, size: g.questions.length })));
}

/** 처음으로 답하지 않은 질문. 모두 답했으면 첫 질문. */
export function firstOpen<T extends QQuestion>(questions: T[]): T | undefined {
  return questions.find((q) => !q.answer) ?? questions[0];
}

/** params 의 id 글이 양의 정수면 그 수. */
export function positiveId(text: string | undefined): number | null {
  const n = Number(text);
  return Number.isInteger(n) && n > 0 ? n : null;
}
