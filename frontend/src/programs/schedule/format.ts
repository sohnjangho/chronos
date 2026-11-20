// 일정판 화면 글: 날짜·유형·상태. 탭들이 함께 쓴다(계산은 하지 않고 서버 값을 글로 바꾸기만 한다).
import type { Tone } from '../../shared/ui/Badge';
import type { Kind } from './scheduleApi';

/** 2027-05-06 → 2027.05.06. 없으면 빈 글. */
export const dot = (iso: string | null | undefined) => (iso ? iso.replaceAll('-', '.') : '');

export const KIND_LABEL: Record<Kind, string> = { task: '작업', start_ms: '시작 마일스톤', finish_ms: '종료 마일스톤' };

/** 0~1 → 퍼센트 글(소수 한 자리까지, 끝의 .0 은 뺀다). */
export const percent = (ratio: number) => String(Math.round(ratio * 1000) / 10);

export type StatusKey = 'on_plan' | 'late' | 'early' | 'done' | 'new';

export const STATUS_KEYS: { key: StatusKey; label: string }[] = [
  { key: 'on_plan', label: '계획 내' },
  { key: 'late', label: '지연' },
  { key: 'early', label: '선행' },
  { key: 'done', label: '완료' },
  { key: 'new', label: 'Plan 없음' },
];

/** 서버 status("late +4" 등) → 거르기 열쇠. */
export function statusKey(status: string): StatusKey {
  const head = status.split(' ')[0];
  return (['late', 'early', 'done', 'new'] as const).find((k) => k === head) ?? 'on_plan';
}

const TONE: Record<StatusKey, Tone> = { on_plan: 'success', late: 'danger', early: 'info', done: 'neutral', new: 'neutral' };

/** 서버 status → 배지 글과 색. 지연·선행은 Plan 종료와 지금 종료의 근무일 차이(서버 계산). */
export function statusBadge(status: string): { label: string; tone: Tone } {
  const key = statusKey(status);
  const days = status.split(' ')[1];
  if (key === 'late') return { label: `지연 ${days}일`, tone: TONE.late };
  if (key === 'early') return { label: `선행 ${days}일`, tone: TONE.early };
  return { label: STATUS_KEYS.find((s) => s.key === key)!.label, tone: TONE[key] };
}
