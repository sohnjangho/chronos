// 승인 요약(summary_json)·차이(diff_json)를 화면 글로. 서버 자료라 칸이 빠져 있어도 던지지 않는다.
import { reasonLabel, type ApprovalDetail, type DiffSide, type Json, type Mode } from './apvApi';

export const asObj = (v: unknown): Json => (typeof v === 'object' && v !== null && !Array.isArray(v) ? (v as Json) : {});
export const asNum = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);
export const asList = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
export const asText = (v: unknown): string => (typeof v === 'string' ? v : v === null || v === undefined ? '' : String(v));

/** "2027-11-28" → "2027.11.28". 날짜가 아니면 받은 글 그대로. */
export const dot = (v: unknown) => asText(v).replace(/^(\d{4})-(\d{2})-(\d{2})$/, '$1.$2.$3');

/** 시작 ~ 종료(같은 날이면 하루만). */
export const range = (s: DiffSide | null) => (s === null ? '—' : s.start === s.finish ? dot(s.finish) : `${dot(s.start)} ~ ${dot(s.finish)}`);

/** -12 → "−12일", 3 → "+3일", 0 → "0일". */
export const signedDays = (n: number) => (n < 0 ? `−${-n}일` : n > 0 ? `+${n}일` : '0일');

function finishText(f: Json): string | null {
  if (f.after === undefined || f.after === null) return null;
  if (f.before === undefined || f.before === null) return `준공 ${dot(f.after)}`;
  const d = asNum(f.delta_days);
  const tail = d === null || d === 0 ? '' : ` (${Math.abs(d)}일 ${d < 0 ? '당겨짐' : '늦어짐'})`;
  return `${dot(f.before)} → ${dot(f.after)}${tail}`;
}

function criticalText(c: Json): string | null {
  const after = asNum(c.after_count);
  if (after === null) return null;
  const before = asNum(c.before_count);
  return `${before === null ? '' : `${before}개 → `}${after}개${c.path_changed === true ? ' · 경로 바뀜' : ''}`;
}

export function conditionLines(summary: Json): string[] {
  return asList(summary.conditions_changed)
    .map(asObj)
    .map((c) => `${asText(c.name) || asText(c.id)} ${asText(c.before) || '없음'} → ${asText(c.after) || '없음'}`);
}

const violationLines = (summary: Json) => asList(asObj(summary.check).violations).map((v) => asText(asObj(v).message)).filter(Boolean);

/** 사유 한 줄의 설명들(여러 줄일 수 있다). */
function reasonText(reason: string, s: Json): string[] {
  switch (reason) {
    case 'finish_changed':
      return [finishText(asObj(s.finish)) ?? '준공일이 바뀝니다.'];
    case 'critical_path_changed':
      return [criticalText(asObj(s.critical)) ?? '크리티컬 패스가 바뀝니다.'];
    case 'condition_changed': {
      const lines = conditionLines(s);
      return lines.length ? lines : ['조건이 바뀝니다.'];
    }
    case 'first_save': {
      const count = asNum(s.changed_count);
      const finish = dot(asObj(s.finish).after);
      return [[count === null ? '' : `액티비티 ${count}개`, finish && `준공 ${finish}`].filter(Boolean).join(' · ') || '새 일정을 처음 저장합니다.'];
    }
    case 'milestone_changed':
      return ['마일스톤 날짜가 바뀝니다. 아래 표에서 확인하세요.'];
    case 'structure_changed':
      return ['액티비티·선후 관계·WBS 가 없어지거나 옮겨집니다.'];
    case 'condition_violated': {
      const lines = violationLines(s);
      return lines.length ? lines : ['조건을 어깁니다.'];
    }
    case 'plan_reset':
      return ['Plan(기준 일정)을 다시 잡습니다.'];
    case 'rule_save':
      return ['내 규칙을 저장합니다.'];
    default:
      return [];
  }
}

export interface WhyLine {
  reason: string;
  label: string;
  lines: string[];
}

export function whyLines(item: Pick<ApprovalDetail, 'reasons' | 'summary'>): WhyLine[] {
  const s = asObj(item.summary);
  return item.reasons.map((r) => ({ reason: r, label: reasonLabel(r), lines: reasonText(r, s) }));
}

/** 사유가 없을 때의 한 줄(모두 승인 수준이거나 자동 적용). */
export function noReasonText(mode: Mode, auto: boolean): string {
  if (auto) return '승인이 필요한 변경이 없어 바로 반영했습니다.';
  return mode === 'all' ? '승인 수준이 「모두 승인」이라 모든 변경을 승인받습니다.' : '승인 사유가 적혀 있지 않습니다.';
}

export const reasonTone = (r: string) =>
  r === 'structure_changed' ? 'warning' : r === 'first_save' || r === 'rule_save' || r === 'plan_reset' ? 'info' : 'danger';

/**
 * 조건 점검. 점검하지 않은 조건은 통과에 넣지 않고 따로 센다. 색: 위반이 있으면 bad, 형식 틀림이 있으면 warn,
 * 점검 안 함이 있으면 neutral, 모두 점검해 통과했을 때만 ok.
 */
export function checkText(summary: Json): { text: string; tone: 'ok' | 'neutral' | 'warn' | 'bad' } | null {
  const c = asObj(summary.check);
  if (Object.keys(c).length === 0) return null;
  const violations = asList(c.violations).length;
  const invalid = asNum(c.invalid) ?? 0;
  const unchecked = asNum(c.uncheckable) ?? 0;
  const parts = [`통과 ${asNum(c.passed) ?? 0}`, `위반 ${violations}`, `점검 안 함 ${unchecked}`];
  if (invalid) parts.push(`형식 틀림 ${invalid}`);
  const tone = violations > 0 ? 'bad' : invalid > 0 ? 'warn' : unchecked > 0 ? 'neutral' : 'ok';
  return { text: parts.join(' · '), tone };
}

/** 기한 여유(근무일). 기한 조건이 없으면 null. */
export function floatText(summary: Json): string | null {
  const f = asObj(summary.finish_float);
  const after = asNum(f.after);
  if (after === null) return null;
  const before = asNum(f.before);
  return `${before === null ? '' : `${before}일 → `}${after}일`;
}

/** 시각 → "11.20 14:02"(지역 시각). */
export function stamp(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const two = (n: number) => String(n).padStart(2, '0');
  return `${two(d.getMonth() + 1)}.${two(d.getDate())} ${two(d.getHours())}:${two(d.getMinutes())}`;
}

/** 숫자 뒤 "로/으로": 끝자리가 0·3·6(영·삼·육, 십·백·천)이면 "으로". */
export const ro = (n: number) => `${n}${/[036]$/.test(String(n)) ? '으로' : '로'}`;
