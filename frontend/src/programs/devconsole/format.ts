// 숫자·시간을 짧은 화면 글로.

/** 340 → "0.34초", 12800 → "12.8초", 125000 → "2분 5초". */
export function seconds(ms: number): string {
  const s = ms / 1000;
  if (s < 1) return `${s.toFixed(2)}초`;
  if (s < 60) return `${s.toFixed(1)}초`;
  const m = Math.floor(s / 60);
  const rest = Math.round(s - m * 60);
  return rest ? `${m}분 ${rest}초` : `${m}분`;
}

/** 950 → "950", 21400 → "21.4K", 1250000 → "1.3M". */
export function tokens(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${Math.round(n / 100) / 10}K`;
  return `${Math.round(n / 100_000) / 10}M`;
}

export const count = (n: number) => n.toLocaleString('ko-KR');

/** 비용(Liner 가 보낸 값). 작은 값은 넷째 자리까지. */
export const cost = (c: number) => `$${c.toFixed(c < 0.01 ? 4 : 2)}`;

const two = (n: number) => String(n).padStart(2, '0');

/** 시:분:초.1 (예 "14:02:07.3"). */
export function clock(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return `${two(d.getHours())}:${two(d.getMinutes())}:${two(d.getSeconds())}.${Math.floor(d.getMilliseconds() / 100)}`;
}

export const hourMinute = (iso: string) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : `${two(d.getHours())}:${two(d.getMinutes())}`;
};

/** 고르기 목록의 날짜 묶음: "오늘" · "어제" · "11월 18일". */
export function dayGroup(iso: string, now = new Date()): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '날짜 모름';
  const day = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((day(now) - day(d)) / 86_400_000);
  if (diff === 0) return '오늘';
  if (diff === 1) return '어제';
  return `${d.getMonth() + 1}월 ${d.getDate()}일`;
}

export const STATUS: Record<string, { label: string; tone: 'info' | 'success' | 'danger' | 'neutral' }> = {
  running: { label: '실행 중', tone: 'info' },
  done: { label: '완료', tone: 'success' },
  failed: { label: '실패', tone: 'danger' },
  stopped: { label: '멈춤', tone: 'neutral' },
};
export const status = (s: string) => STATUS[s] ?? { label: s, tone: 'neutral' as const };
