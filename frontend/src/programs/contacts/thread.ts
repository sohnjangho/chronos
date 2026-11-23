// 대화 줄을 그리기 전의 셈: 날짜 줄 묶기(KST) · 다시 읽은 쪽과 앞서 읽은 쪽 합치기 · 「…에 대한 답」 한 줄 · 작업 이름표.
import { kstDate, kstDay, kstTime } from '../../shared/outreach/labels';
import type { Message } from '../../shared/outreach/outreachApi';

export interface DayGroup {
  /** 2026년 11월 23일 월요일 */
  day: string;
  items: Message[];
}

/** 만든 날(KST)이 같은 줄끼리 차례대로 묶는다. 줄은 서버가 준 차례(오래된 것부터) 그대로. */
export function groupByDay(messages: Message[]): DayGroup[] {
  const groups: DayGroup[] = [];
  for (const m of messages) {
    const day = kstDay(m.created_at);
    const last = groups.at(-1);
    if (last && last.day === day) last.items.push(m);
    else groups.push({ day, items: [m] });
  }
  return groups;
}

/** 가장 새 쪽을 다시 읽었다: 그 쪽이 덮는 구간(첫 id 부터)은 통째로 바꾸고(지워진 초안이 사라지게), 그보다 앞의 줄은 둔다. */
export function mergeNewest(prev: Message[], fresh: Message[]): Message[] {
  if (fresh.length === 0) return [];
  return [...prev.filter((m) => m.id < fresh[0].id), ...fresh];
}

/** 「이전 대화 더 보기」로 읽은 쪽: 지금 보이는 첫 줄보다 앞의 것만 앞에 붙인다. */
export function prependOlder(shown: Message[], older: Message[]): Message[] {
  const first = shown[0]?.id ?? Infinity;
  return [...older.filter((m) => m.id < first), ...shown];
}

/** A1210 지상 골조 — 그 작업이 지금 일정에 없으면 id 만. */
export const activityLabel = (a: NonNullable<Message['activity']>) => (a.name ? `${a.id} ${a.name}` : a.id);

/** 초안 머리의 한 줄: 「아직 보내지 않음 · 대화 「주간 점검」에서」, 자동 답이면 「… · 들어온 문자에 대한 답 초안」. */
export function draftLine(m: Message, status: string): string {
  // 대화 제목은 그 대화를 만든 사람에게만 온다(다른 사람에게는 빈 글).
  const from = m.kind === 'auto_reply' ? '들어온 문자에 대한 답 초안' : m.chat ? (m.chat.title ? `대화 「${m.chat.title}」에서` : '다른 사람의 대화에서') : null;
  return from ? `${status} · ${from}` : status;
}

/** ↩ 11/24 A1210 지상 골조 요청에 대한 답. 답한 줄이 아니면 null, 그 줄을 아직 읽지 않았으면(더 앞쪽) 「앞선 글」. */
export function replyLine(m: Message, all: Message[]): string | null {
  if (m.reply_to_id === null) return null;
  const to = all.find((x) => x.id === m.reply_to_id);
  if (!to) return '↩ 앞선 글에 대한 답';
  const day = kstDate(to.created_at);
  if (to.direction === 'in') return `↩ ${day} ${kstTime(to.created_at)} 받은 글에 대한 답`;
  return to.activity ? `↩ ${day} ${activityLabel(to.activity)} 요청에 대한 답` : `↩ ${day} ${kstTime(to.created_at)} 보낸 글에 대한 답`;
}
