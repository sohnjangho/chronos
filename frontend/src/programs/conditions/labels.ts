// 조건 화면의 글·분류·값 읽기. 날짜 계산은 하지 않는다(서버가 계산한 날짜를 보이기만 한다).
import type { BadgeProps } from '../../shared/ui/Badge';
import type { Cond, CondView, Layer, State } from './condApi';

export const STATE_LABEL: Record<State, string> = {
  passed: '통과',
  violated: '위반',
  uncheckable: '자동 점검 안 됨',
  off: '꺼짐',
};

export const STATE_TONE: Record<State, NonNullable<BadgeProps['tone']>> = {
  passed: 'success',
  violated: 'danger',
  uncheckable: 'neutral',
  off: 'neutral',
};

export const LAYERS: { layer: Layer; title: string; lock?: string; note: string }[] = [
  { layer: 'base', title: '① 기본 규칙', lock: '못 바꿈', note: '모든 일정에 항상 적용' },
  { layer: 'domain', title: '② 분야 규칙', lock: '관리자만 수정', note: '분야 묶음에 들어 있음 · 이 일정에서 켜고 끄기' },
  { layer: 'mine', title: '③ 내 규칙', note: '에이전트가 제안 → 확인 뒤 저장 · 이 화면에서는 읽기만' },
  { layer: 'input', title: '④ 입력 조건', note: '대화와 질문지에서 뽑음 · 이 일정에만 적용' },
];

/** 조건 종류의 묶음(많은 조건을 훑어보게). 차례대로 보인다. */
export const GROUPS: { label: string; kinds: string[] }[] = [
  { label: '자원', kinds: ['resource_cap'] },
  { label: '날짜', kinds: ['finish_by', 'start_after', 'milestone_by'] },
  { label: '달력·금지 기간', kinds: ['calendar', 'blocked_period'] },
  { label: '간격·기간', kinds: ['min_gap', 'max_duration', 'duration_per_unit'] },
  { label: '말로 된 조건', kinds: ['text_only'] },
];
const OTHER = '그 밖';

export function groupOf(kind: string): string {
  return GROUPS.find((g) => g.kinds.includes(kind))?.label ?? OTHER;
}

/** 한 칸의 조건을 묶음 차례로 나눈다(빈 묶음은 뺀다). */
export function grouped(items: Cond[]): { label: string; items: Cond[] }[] {
  const order = [...GROUPS.map((g) => g.label), OTHER];
  return order.map((label) => ({ label, items: items.filter((c) => groupOf(c.kind) === label) })).filter((g) => g.items.length);
}

type Resources = CondView['resources'];

const resourceOf = (c: Cond, resources: Resources) => resources.find((r) => r.id === c.params.resource_id);

/** 조건의 이름: 자원 조건은 자원 이름, 그 밖은 조건 글(없으면 id). */
export function condLabel(c: Cond, resources: Resources): string {
  if (c.kind === 'resource_cap') return resourceOf(c, resources)?.name ?? String(c.params.resource_id ?? c.id);
  return c.text || c.id;
}

export function unitOf(c: Cond, resources: Resources): string {
  if (c.kind === 'resource_cap') return resourceOf(c, resources)?.unit ?? '';
  return c.kind === 'min_gap' || c.kind === 'max_duration' ? '일' : '';
}

/** 바꿀 수 있는 값의 칸 이름(없으면 null). 날짜는 'date', 수는 'capacity'·'days', 근무 요일은 'days_per_week'. */
export function paramKey(kind: string): string | null {
  if (kind === 'resource_cap') return 'capacity';
  if (kind === 'finish_by' || kind === 'start_after' || kind === 'milestone_by') return 'date';
  if (kind === 'min_gap' || kind === 'max_duration') return 'days';
  return kind === 'calendar' ? 'days_per_week' : null;
}

/** 값 칸의 접근 이름(예 「타워크레인 수량」·「준공 기한 날짜」). */
export function fieldLabel(c: Cond, label: string): string {
  if (c.kind === 'resource_cap') return `${label} 수량`;
  if (c.kind === 'finish_by') return '준공 기한 날짜';
  if (c.kind === 'start_after') return '시작 가능일 날짜';
  if (c.kind === 'milestone_by') return `${String(c.params.activity_id ?? '')} 기한 날짜`;
  if (c.kind === 'calendar') return '근무 요일';
  return `${label} 일수`;
}

/** 값 하나를 짧게(바꾼 값 「1대 → 2대」 줄). */
export function valueText(key: string, value: unknown, unit: string): string {
  if (key === 'days_per_week') return `주 ${String(value)}일`;
  return key === 'date' ? String(value) : `${String(value)}${unit}`;
}

/** 입력 글 → 값. 틀리면 null. 수는 0 이상 정수(4자리까지), 날짜는 있는 날 YYYY-MM-DD. */
export function parseValue(key: string, raw: string): number | string | null {
  const text = raw.trim();
  if (key === 'date') {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) return null;
    const d = new Date(`${text}T00:00:00Z`);
    return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === text ? text : null;
  }
  return /^\d{1,4}$/.test(text) ? Number(text) : null;
}

/** 'YYYY-MM-DD' → 'MM.DD'. 비교하는 날짜와 해가 다르면 'YYYY.MM.DD'. */
export function shortDate(iso: string, other?: string): string {
  const [y, mo, d] = iso.split('-');
  return other && other.slice(0, 4) !== y ? `${y}.${mo}.${d}` : `${mo}.${d}`;
}

export function allConds(view: CondView): Cond[] {
  return LAYERS.flatMap((l) => view.layers[l.layer]);
}

export type StateFilter = 'all' | State;

export function matches(c: Cond, label: string, query: string, state: StateFilter): boolean {
  if (state !== 'all' && c.state !== state) return false;
  const q = query.trim().toLowerCase();
  return !q || [label, c.text, c.source, c.id].some((s) => s.toLowerCase().includes(q));
}
