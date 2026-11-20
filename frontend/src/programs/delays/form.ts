// 지연 사건 양식의 값·검사·보낼 본문. 칸 값은 모두 글(입력 칸 그대로)이고, 보낼 때 숫자로 바꾼다.
import type { DelayBody, DelayEvent, DelayPatch, Responsibility } from './delaysApi';

export interface FormValues {
  activity_id: string;
  start_date: string;
  days: string;
  cause: string;
  responsibility: Responsibility;
  daily_cost: string;
  evidence: string;
}

export type FormErrors = Partial<Record<keyof FormValues, string>>;

export const emptyValues = (over: Partial<FormValues> = {}): FormValues => ({
  activity_id: '', start_date: '', days: '', cause: '', responsibility: 'undecided', daily_cost: '', evidence: '', ...over,
});

export const valuesOf = (e: DelayEvent): FormValues => ({
  activity_id: e.activity_id, start_date: e.start_date, days: String(e.days), cause: e.cause,
  responsibility: e.responsibility, daily_cost: e.daily_cost === null ? '' : String(e.daily_cost), evidence: e.evidence,
});

const INT = /^\d+$/;
const DATE = /^\d{4}-\d{2}-\d{2}$/;

/** 검사: 대상·시작일·일수 1~365·원인 필수·하루 금액 0 이상 정수(비워도 됨). */
export function validate(v: FormValues): FormErrors {
  const errors: FormErrors = {};
  if (!v.activity_id) errors.activity_id = '대상 액티비티를 고르세요.';
  if (!DATE.test(v.start_date.trim())) errors.start_date = '날짜는 2027-06-01 처럼 적어 주세요.';
  const days = v.days.trim();
  if (!INT.test(days) || Number(days) < 1 || Number(days) > 365) errors.days = '일수는 1~365 사이 정수로 적어 주세요.';
  if (!v.cause.trim()) errors.cause = '원인을 적어 주세요.';
  if (v.daily_cost.trim() && !INT.test(v.daily_cost.trim())) errors.daily_cost = '하루 금액은 0 이상 정수(원)로 적어 주세요.';
  return errors;
}

const cost = (s: string) => (s.trim() ? Number(s.trim()) : null);

/** 새 사건 본문. before(실적 입력 전 버전)가 있으면 source 'actual' 로 — 이미 일정에 들어간 늦음이라 두 번 세지 않게. */
export function toBody(v: FormValues, before: number | null): DelayBody {
  const body: DelayBody = {
    activity_id: v.activity_id, start_date: v.start_date.trim(), days: Number(v.days.trim()), cause: v.cause.trim(),
    responsibility: v.responsibility, daily_cost: cost(v.daily_cost), evidence: v.evidence.trim(),
  };
  return before === null ? body : { ...body, source: 'actual', before_version: before };
}

/** 고치기 본문: 사건과 달라진 칸만(같은 값을 보내면 잠긴 칸 변경으로 본다). 하루 금액을 비우면 null. */
export function toPatch(v: FormValues, e: DelayEvent): DelayPatch {
  const next = toBody(v, null);
  const patch: DelayPatch = {};
  if (next.activity_id !== e.activity_id) patch.activity_id = next.activity_id;
  if (next.start_date !== e.start_date) patch.start_date = next.start_date;
  if (next.days !== e.days) patch.days = next.days;
  if (next.cause !== e.cause) patch.cause = next.cause;
  if (next.responsibility !== e.responsibility) patch.responsibility = next.responsibility;
  if (next.daily_cost !== e.daily_cost) patch.daily_cost = next.daily_cost;
  if (next.evidence !== e.evidence) patch.evidence = next.evidence;
  return patch;
}
