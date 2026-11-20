// 지연 기록 화면 글: 금액·일수·날짜·책임·상태. 계산하지 않고 서버 값을 글로 바꾸기만 한다(날짜는 글자 자르기뿐).
import type { Tone } from '../../shared/ui/Badge';
import type { DelayEvent, Responsibility } from './delaysApi';

const commas = (n: number) => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ',');

/** 원 → 글. null 은 「—」, 1만 원 아래는 원 그대로(9,000원), 그 밖은 만 원 단위 반올림(1,240만 원). */
export function won(v: number | null): string {
  if (v === null) return '—';
  if (v < 10_000) return `${commas(v)}원`;
  return `${commas(Math.round(v / 10_000))}만 원`;
}

/** 준공을 민 근무일: 늦어지면 +. */
export const impactDays = (n: number) => (n > 0 ? `+${n}일` : `${n}일`);

/** 표의 몫(단위는 칸 머리에): +2 · 0. */
export const signed = (n: number) => (n > 0 ? `+${n}` : String(n));

/** 2027-06-02 → 2027.06.02. */
export const dot = (iso: string) => iso.replaceAll('-', '.');

/** 두 날짜: 같은 해면 MM.DD 둘, 다르면 YYYY.MM.DD 둘. */
export function shortPair(a: string, b: string): [string, string] {
  if (a.slice(0, 4) !== b.slice(0, 4)) return [dot(a), dot(b)];
  return [dot(a.slice(5)), dot(b.slice(5))];
}

/** 책임: 차례는 KPI·거르기·양식이 같이 쓴다. */
export const RESPONSIBILITIES: { key: Responsibility; label: string; tone: Tone }[] = [
  { key: 'owner', label: '발주처', tone: 'info' },
  { key: 'force', label: '불가항력', tone: 'warning' },
  { key: 'ours', label: '우리', tone: 'danger' },
  { key: 'undecided', label: '미정', tone: 'neutral' },
];
export const respOf = (key: string) => RESPONSIBILITIES.find((r) => r.key === key) ?? { key, label: key, tone: 'neutral' as Tone };

/** 상태 배지: 열림 / 반영됨 v n. */
export const statusLabel = (e: DelayEvent) => (e.status === 'open' ? '열림' : `반영됨 v${e.reflected_version ?? ''}`);

export const SOURCE_LABEL: Record<string, string> = { chat: '대화에서', actual: '실적 입력에서' };
