// 「공정률」 대시보드 위젯 배치·너비·표시 상태(사용자별 localStorage 기억).
import { loadPref, savePref } from '../../os/prefs';
import { loadJson, saveJson } from '../../os/storage';

export type WidgetId = 'kpi' | 'scurve' | 'milestone' | 'wbs' | 'spi' | 'delay' | 'lookahead';
export type WidgetSpan = 3 | 4 | 6 | 8 | 12;

export interface WidgetItem {
  id: WidgetId;
  span: WidgetSpan;
  visible: boolean;
}

export const WIDGET_META: Record<WidgetId, { label: string; shortLabel: string }> = {
  kpi: { label: '공정률 요약 (KPI)', shortLabel: '요약 KPI' },
  scurve: { label: '공정률 S-커브', shortLabel: 'S-커브' },
  milestone: { label: '마일스톤 추적', shortLabel: '마일스톤' },
  wbs: { label: 'WBS 묶음별 공정률', shortLabel: 'WBS' },
  spi: { label: '일정 수행 지수(SPI) 추이', shortLabel: 'SPI 추이' },
  delay: { label: '지연 상위 액티비티', shortLabel: '지연 상위' },
  lookahead: { label: '앞으로 3주 작업', shortLabel: '앞으로 3주' },
};

export const SPAN_OPTIONS: readonly { span: WidgetSpan; label: string }[] = [
  { span: 3, label: '1/4' },
  { span: 4, label: '1/3' },
  { span: 6, label: '1/2' },
  { span: 8, label: '2/3' },
  { span: 12, label: '전체' },
];

export const DEFAULT_WIDGET_LAYOUT: readonly WidgetItem[] = [
  { id: 'kpi', span: 12, visible: true },
  { id: 'scurve', span: 8, visible: true },
  { id: 'milestone', span: 4, visible: true },
  { id: 'wbs', span: 3, visible: true },
  { id: 'spi', span: 3, visible: true },
  { id: 'delay', span: 3, visible: true },
  { id: 'lookahead', span: 3, visible: true },
];

const PREF_NAME = 'progress.widgets';
const FALLBACK_KEY = 'chronos.progress.widgets';
const VALID_SPANS = new Set<number>([3, 4, 6, 8, 12]);
const DEFAULT_BY_ID = new Map<WidgetId, WidgetItem>(DEFAULT_WIDGET_LAYOUT.map((item) => [item.id, item]));

function isWidgetId(v: unknown): v is WidgetId {
  return typeof v === 'string' && DEFAULT_BY_ID.has(v as WidgetId);
}

export function resetWidgetLayout(): WidgetItem[] {
  return DEFAULT_WIDGET_LAYOUT.map((item) => ({ ...item }));
}

export function loadWidgetLayout(userId: number | null): WidgetItem[] {
  const raw = userId !== null ? (loadPref(PREF_NAME, userId) ?? loadJson(FALLBACK_KEY)) : loadJson(FALLBACK_KEY);
  if (!Array.isArray(raw)) return resetWidgetLayout();

  const seen = new Set<WidgetId>();
  const out: WidgetItem[] = [];
  for (const entry of raw) {
    if (!entry || typeof entry !== 'object') continue;
    const obj = entry as Record<string, unknown>;
    if (!isWidgetId(obj.id) || seen.has(obj.id)) continue;
    seen.add(obj.id);
    const def = DEFAULT_BY_ID.get(obj.id)!;
    const span = typeof obj.span === 'number' && VALID_SPANS.has(obj.span) ? (obj.span as WidgetSpan) : def.span;
    const visible = typeof obj.visible === 'boolean' ? obj.visible : true;
    out.push({ id: obj.id, span, visible });
  }
  for (const def of DEFAULT_WIDGET_LAYOUT) {
    if (!seen.has(def.id)) out.push({ ...def });
  }
  return out;
}

export function saveWidgetLayout(userId: number | null, items: WidgetItem[]): void {
  savePref(PREF_NAME, userId, items);
  saveJson(FALLBACK_KEY, items);
}

export function moveWidget(items: WidgetItem[], id: WidgetId, delta: -1 | 1): WidgetItem[] {
  const visibleIndices = items.reduce<number[]>((acc, item, i) => {
    if (item.visible) acc.push(i);
    return acc;
  }, []);
  const srcIndex = items.findIndex((item) => item.id === id && item.visible);
  if (srcIndex === -1) return items;
  const vIdx = visibleIndices.indexOf(srcIndex);
  const targetVIdx = vIdx + delta;
  if (targetVIdx < 0 || targetVIdx >= visibleIndices.length) return items;

  const targetIndex = visibleIndices[targetVIdx];
  const next = items.map((item) => ({ ...item }));
  const tmp = next[srcIndex];
  next[srcIndex] = next[targetIndex];
  next[targetIndex] = tmp;
  return next;
}

export function reorderWidget(items: WidgetItem[], fromId: WidgetId, toId: WidgetId): WidgetItem[] {
  if (fromId === toId) return items;
  const fromIdx = items.findIndex((item) => item.id === fromId);
  const toIdx = items.findIndex((item) => item.id === toId);
  if (fromIdx === -1 || toIdx === -1) return items;

  const next = items.map((item) => ({ ...item }));
  const [moved] = next.splice(fromIdx, 1);
  next.splice(toIdx, 0, moved);
  return next;
}

export function setWidgetSpan(items: WidgetItem[], id: WidgetId, span: WidgetSpan): WidgetItem[] {
  let changed = false;
  const next = items.map((item) => {
    if (item.id !== id || item.span === span) return item;
    changed = true;
    return { ...item, span };
  });
  return changed ? next : items;
}

export function toggleWidgetVisible(items: WidgetItem[], id: WidgetId): WidgetItem[] {
  let changed = false;
  const next = items.map((item) => {
    if (item.id !== id) return item;
    changed = true;
    return { ...item, visible: !item.visible };
  });
  return changed ? next : items;
}
