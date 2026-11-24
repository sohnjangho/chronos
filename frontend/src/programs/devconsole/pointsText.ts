// 관리 포인트 단계(계획 5 Task 7)의 짧은 글 — 고르기 목록과 단계 칸이 함께 쓴다.
import type { PointsStage } from './devApi';

/** 1,000회당 값 → 「$2/1K」. 기상청(null)은 「비용 없음」. */
export const per1k = (v: number | null) => (v === null ? '비용 없음' : `$${Number.isInteger(v) ? v : v.toFixed(1)}/1K`);

/** 어림 비용(호출 수 × 단가) — 1달러 밑은 넷째 자리까지(「$0.0460」). */
export const estimate = (usd: number) => `$${usd.toFixed(usd < 1 ? 4 : 2)}`;

/** 「5층 사무동 · 버전 2 → 3」 · 「… · 가정 · 버전 3 · 지연 기록」. */
export function stageTitle(s: PointsStage): string {
  const t = s.trigger;
  const what = s.what_if
    ? `가정 · 버전 ${s.version}${t.kind === 'delay' ? ' · 지연 기록' : ''}`
    : t.kind === 'version' && t.from !== undefined
      ? `버전 ${t.from} → ${t.to ?? s.version}`
      : `버전 ${s.version}`;
  return `${s.schedule_name || `일정 ${s.schedule_id}`} · ${what}`;
}
