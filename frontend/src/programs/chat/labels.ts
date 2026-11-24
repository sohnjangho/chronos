// 서버가 보내는 이름(도구·단계·사유·분야)을 화면 글로. 모르는 이름은 받은 그대로 보인다.

export { toolLabel } from '../../shared/toolLabels';

/** 생성 단계(Task 9 의 GenStage) 차례. */
export const STAGES: [string, string][] = [
  ['wbs', 'WBS 만들기'],
  ['schedule', '스케줄 만들기'],
  ['compute', '날짜 계산'],
  ['critical', '크리티컬 패스'],
  ['check', '조건 점검'],
];

const REASONS: Record<string, string> = {
  first_save: '첫 저장',
  finish_changed: '준공 변경',
  milestone_changed: '마일스톤 변경',
  critical_path_changed: '크리티컬 경로 변경',
  condition_violated: '조건 위반',
  condition_changed: '조건 변경',
  structure_changed: '구조 변경',
  plan_reset: 'Plan 다시 정함',
  rule_save: '규칙 저장',
  field_report: '현장 보고',
  human_read: '사람 판독',
};
export const reasonLabel = (reason: string) => REASONS[reason] ?? reason;

import { domainLabel } from '../../shared/domainLabels';

export { domainLabel };

export const STEP_STATUS: Record<string, string> = { running: '진행 중', waiting: '대기 중', done: '끝남', failed: '실패', stopped: '멈춤' };

/** "2027-11-24" → "2027.11.24". 날짜가 아니면 그대로. */
export const dotDate = (value: unknown) => (typeof value === 'string' ? value.replace(/^(\d{4})-(\d{2})-(\d{2})$/, '$1.$2.$3') : '');

/** 200ms → "0.2초", 41000ms → "41초". */
export function seconds(ms: number): string {
  const s = ms / 1000;
  return `${s < 10 ? Math.round(s * 10) / 10 : Math.round(s)}초`;
}

/** 48200 → "48K", 950 → "950". */
export function tokens(n: number): string {
  if (n < 1000) return String(n);
  const k = n / 1000;
  return `${k < 10 ? Math.round(k * 10) / 10 : Math.round(k)}K`;
}

const CIRCLED = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳';
export const circled = (n: number) => (n >= 1 && n <= CIRCLED.length ? CIRCLED[n - 1] : `${n}.`);
