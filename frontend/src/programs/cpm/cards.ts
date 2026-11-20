// CPM 카드 글: 상태·Plan 대비 칩·줄(ES/EF · LS/LF · OD/RD · TF/진도 · Plan). 서버 값을 글로 바꾸기만 한다(날짜 계산 없음).
import { percent } from '../../shared/schedule/format';
import type { Activity } from '../../shared/schedule/scheduleApi';

export interface Layers {
  plan: boolean;
  actual: boolean;
  cpm: boolean;
}

/** 2027-05-06 → 05.06. 없으면 빈 글. */
export const md = (iso: string | null | undefined) => (iso ? iso.slice(5).replace('-', '.') : '');

const DASH = '—';
const range = (start: string | null | undefined, finish: string | null | undefined, none = DASH) =>
  start && finish ? `${md(start)} ~ ${md(finish)}` : none;

export function statusLabel(a: Activity): '완료' | '진행 중' | '미착수' {
  if (a.actual_finish) return '완료';
  return a.actual_start ? '진행 중' : '미착수';
}

export type ChipTone = 'danger' | 'success' | 'neutral';

/** 서버 status → Plan 대비 칩. 지연·선행 일수는 서버가 센 근무일. 모르는 값은 그대로. */
export function planChip(status: string): { text: string; tone: ChipTone } {
  const late = /^late \+(\d+)$/.exec(status);
  if (late) return { text: `+${late[1]}일`, tone: 'danger' };
  const early = /^early -(\d+)$/.exec(status);
  if (early) return { text: `−${early[1]}일`, tone: 'success' };
  if (status === 'on_plan') return { text: '계획 내', tone: 'success' };
  if (status === 'new') return { text: '새 액티비티', tone: 'neutral' };
  if (status === 'done') return { text: '완료', tone: 'neutral' };
  return { text: status, tone: 'neutral' };
}

/** 카드 줄. CPM 층은 ES/EF·LS/LF·TF, Actual 층은 진도, Plan 층은 Plan 줄. */
export function cardRows(a: Activity, layers: Layers): { label: string; value: string }[] {
  const rows: { label: string; value: string }[] = [];
  if (layers.cpm) {
    rows.push({ label: 'ES/EF', value: range(a.es, a.ef) }, { label: 'LS/LF', value: range(a.ls, a.lf) });
  }
  rows.push({ label: 'OD/RD', value: `${a.od}일 / ${a.rd === null ? DASH : `${a.rd}일`}` });
  const tf = `${a.tf}일`;
  const progress = `${percent(a.progress)}%`;
  if (layers.cpm && layers.actual) rows.push({ label: 'TF/진도', value: `${tf} / ${progress}` });
  else if (layers.cpm) rows.push({ label: 'TF', value: tf });
  else if (layers.actual) rows.push({ label: '진도', value: progress });
  if (layers.plan) rows.push({ label: 'Plan', value: range(a.plan_start, a.plan_finish, 'Plan 없음') });
  return rows;
}
