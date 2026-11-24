// 관리 포인트 창의 글·모양 도우미. 날짜는 서버가 준 ISO 글을 자르고 견주기만 한다(계산하지 않는다).
import type { Diff, Point, Risk } from './pointsApi';

/** 「2027-06-01」 → 「06.01」. */
export const md = (iso: string | null | undefined) => (iso ? iso.slice(5, 10).replace('-', '.') : '');
export const span = (es: string, ef: string) => (es === ef ? md(es) : `${md(es)} ~ ${md(ef)}`);

/** 저장 시각(UTC ISO) → 「11-24 17:05」(보는 사람의 시간대). */
export function stamp(at: string | null): string {
  if (!at) return '';
  const d = new Date(at);
  if (Number.isNaN(d.getTime())) return '';
  const p = (n: number) => String(n).padStart(2, '0');
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

const WEEK_NAMES = ['이번 주', '다음 주', '그다음 주'];
export const weekName = (i: number) => WEEK_NAMES[i] ?? `${i + 1}주째`;

/** 포인트가 들어갈 주 칸: 시작일이 그 칸 끝보다 늦지 않은 첫 칸(진행 중 — Data Date 앞 시작 — 은 첫 칸). 없으면 마지막 칸. */
export function weekIndex(es: string, weeks: { start: string; end: string }[]): number {
  const i = weeks.findIndex((w) => es <= w.end);
  return i === -1 ? weeks.length - 1 : i;
}

/** 이번 버전에 바뀐 포인트의 표시(바뀜 배지). 여유가 준 것은 「바뀜 a → b」, 새로 들어온 것은 앞 여유를 알면 같은 꼴. */
export function changeOf(diff: Diff | null, p: Point): string | null {
  if (!diff) return null;
  const t = diff.tightened.find(([id]) => id === p.activity_id);
  if (t) return `바뀜 ${t[1]} → ${t[2]}`;
  const before = diff.before_tf[p.activity_id];
  if (diff.added.some((a) => a.activity_id === p.activity_id)) return before !== undefined ? `바뀜 ${before} → ${p.tf}` : '새로 들어옴';
  if (diff.became_critical.includes(p.activity_id)) return '크리티컬이 됨';
  return null;
}

export function changedCount(diff: Diff | null): number {
  if (!diff) return 0;
  return new Set([...diff.added.map((a) => a.activity_id), ...diff.became_critical, ...diff.tightened.map(([id]) => id)]).size;
}

export const KINDS: Record<string, string> = { weather: '날씨', materials: '자재', fx: '환율', business: '업체' };
const ICONS: Record<string, string[]> = {
  weather: ['M7 15a4 4 0 0 1-.6-7.95A5.5 5.5 0 0 1 17 7.5a3.75 3.75 0 0 1 .5 7.5z', 'M8 18.5l-1 2M12 18.5l-1 2M16 18.5l-1 2'],
  materials: ['M12 3l8 4.5v9L12 21l-8-4.5v-9z', 'M4 7.5l8 4.5 8-4.5M12 12v9'],
  fx: ['M4 8h14l-3.5-3.5', 'M20 16H6l3.5 3.5'],
  business: ['M4 21V6l8-3v18', 'M12 9l8 2v10', 'M3 21h18M7.5 9h1M7.5 13h1M7.5 17h1M15.5 14h1M15.5 18h1'],
};

export function KindIcon({ kind, label = false }: { kind: string; label?: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"
      role={label ? 'img' : undefined} aria-label={label ? KINDS[kind] ?? kind : undefined} aria-hidden={label ? undefined : true}>
      {(ICONS[kind] ?? ICONS.business).map((d) => (
        <path key={d} d={d} />
      ))}
    </svg>
  );
}

/** 포인트 카드에 보일 바깥 위험 갈래(자료가 있는 줄만, 한 번씩). */
export const riskKinds = (risks: Risk[], aid: string) => [...new Set(risks.filter((r) => r.activity_id === aid && r.status === 'ok').map((r) => r.kind))];

export const matches = (p: Point, query: string) => {
  const q = query.trim().toLowerCase();
  return !q || p.name.toLowerCase().includes(q) || p.activity_id.toLowerCase().includes(q);
};
