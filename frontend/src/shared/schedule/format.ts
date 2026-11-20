// 일정 도구 화면 글: 날짜·유형·상태. 스케줄·간트차트 등이 함께 쓴다(계산은 하지 않고 서버 값을 글로 바꾸기만 한다).
import type { Tone } from '../ui/Badge';
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

const KNOWN = /^(on_plan|done|new|late \+\d+|early -\d+)$/;

/** 서버 status("late +4" 등) → 거르기 열쇠. 모르는 값이면 null(상태로 거를 때는 빠진다). */
export function statusKey(status: string): StatusKey | null {
  return KNOWN.test(status) ? (status.split(' ')[0] as StatusKey) : null;
}

const TONE: Record<StatusKey, Tone> = { on_plan: 'success', late: 'danger', early: 'info', done: 'neutral', new: 'neutral' };

/** 서버 status → 배지 글과 색. 지연·선행은 Plan 종료와 지금 종료의 근무일 차이(서버 계산). */
export function statusBadge(status: string): { label: string; tone: Tone } {
  const key = statusKey(status);
  if (key === null) return { label: status, tone: 'neutral' }; // 모르는 상태는 꾸미지 않고 그대로
  const days = status.split(' ')[1];
  if (key === 'late') return { label: `지연 ${days}일`, tone: TONE.late };
  if (key === 'early') return { label: `선행 ${days}일`, tone: TONE.early };
  return { label: STATUS_KEYS.find((s) => s.key === key)!.label, tone: TONE[key] };
}
