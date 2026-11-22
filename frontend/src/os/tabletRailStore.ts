// 태블릿 전용 왼쪽 아이콘 레일 구성(추가·제거·순서 변경). 사용자별로 localStorage 에 기억한다.
import { create } from 'zustand';
import { loadPref, savePref } from './prefs';
import type { ProgramManifest } from './registry';
import type { Role } from './session';

export interface TabletRailEntry {
  id: string;
  label: string;
  fullName: string;
  programId: string;
  iconId?: 'field';
}

export const DEFAULT_TABLET_RAIL: readonly string[] = [
  'chat',
  'schedule-table',
  'gantt',
  'progress',
  'field',
  'cpm',
  'delays',
  'workflow',
  'approvals',
  'reports',
  'library',
];

export const FIELD_TABLET_RAIL: readonly string[] = ['field', 'schedule-table', 'gantt', 'chat'];

const SHORT_LABELS: Record<string, string> = {
  chat: '대화',
  'schedule-table': '스케줄',
  gantt: '간트',
  progress: '공정률',
  field: '현장 점검',
  cpm: 'CPM',
  delays: '지연',
  workflow: '워크플로우',
  approvals: '승인함',
  reports: '보고서',
  library: '자료함',
  compare: '비교판',
  conditions: '조건·규칙',
  explorer: '탐색기',
  questionnaire: '질문지',
  devconsole: '개발 콘솔',
};

export function defaultTabletRailIds(role: Role): string[] {
  return role === 'field' ? [...FIELD_TABLET_RAIL] : [...DEFAULT_TABLET_RAIL];
}

export function tabletCatalog(role: Role, allowedPrograms: ProgramManifest[]): TabletRailEntry[] {
  const byProgramId = new Map(allowedPrograms.map((p) => [p.id, p]));
  if (role === 'field') {
    const out: TabletRailEntry[] = [];
    if (byProgramId.has('progress')) {
      out.push({ id: 'field', label: '현장 점검', fullName: '현장 모바일 점검', programId: 'progress', iconId: 'field' });
    }
    if (byProgramId.has('schedule-table')) {
      out.push({ id: 'schedule-table', label: '스케줄', fullName: byProgramId.get('schedule-table')!.name, programId: 'schedule-table' });
    }
    if (byProgramId.has('gantt')) {
      out.push({ id: 'gantt', label: '간트', fullName: byProgramId.get('gantt')!.name, programId: 'gantt' });
    }
    if (byProgramId.has('chat')) {
      out.push({ id: 'chat', label: '현장 AI', fullName: byProgramId.get('chat')!.name, programId: 'chat' });
    }
    return out;
  }

  const out: TabletRailEntry[] = [];
  for (const p of allowedPrograms) {
    if (p.id === 'settings') continue;
    out.push({
      id: p.id,
      label: SHORT_LABELS[p.id] ?? p.name,
      fullName: p.name,
      programId: p.id,
    });
    if (p.id === 'progress') {
      out.push({
        id: 'field',
        label: '현장 점검',
        fullName: '현장 모바일 점검',
        programId: 'progress',
        iconId: 'field',
      });
    }
  }
  return out;
}

export function resolveTabletRail(role: Role, allowedPrograms: ProgramManifest[], saved: string[] | null): TabletRailEntry[] {
  const byId = new Map(tabletCatalog(role, allowedPrograms).map((e) => [e.id, e]));
  const ids = saved ?? defaultTabletRailIds(role);
  const seen = new Set<string>();
  const out: TabletRailEntry[] = [];
  for (const id of ids) {
    if (seen.has(id)) continue;
    seen.add(id);
    const entry = byId.get(id);
    if (entry) out.push(entry);
  }
  return out;
}

interface TabletRailState {
  userId: number | null;
  items: string[] | null;
  load(userId: number | null): void;
  add(id: string, defaults: string[]): void;
  remove(id: string, defaults: string[]): void;
  move(id: string, to: number, defaults: string[]): void;
  moveBy(id: string, delta: -1 | 1, defaults: string[]): void;
  resetDefault(): void;
}

export const useTabletRail = create<TabletRailState>((set, get) => {
  const save = (items: string[]) => {
    savePref('tabletRail', get().userId, items);
    set({ items });
  };
  const current = (defaults: string[]) => get().items ?? defaults;
  return {
    userId: null,
    items: null,
    load(userId) {
      const saved = loadPref('tabletRail', userId);
      const items = Array.isArray(saved) ? saved.filter((x): x is string => typeof x === 'string') : null;
      set({ userId, items });
    },
    add(id, defaults) {
      save([...current(defaults).filter((x) => x !== id), id]);
    },
    remove(id, defaults) {
      save(current(defaults).filter((x) => x !== id));
    },
    move(id, to, defaults) {
      const rest = current(defaults).filter((x) => x !== id);
      rest.splice(Math.max(0, Math.min(to, rest.length)), 0, id);
      save(rest);
    },
    moveBy(id, delta, defaults) {
      const cur = current(defaults);
      const idx = cur.indexOf(id);
      const next = idx + delta;
      if (idx < 0 || next < 0 || next >= cur.length) return;
      const rest = cur.filter((x) => x !== id);
      rest.splice(next, 0, id);
      save(rest);
    },
    resetDefault() {
      savePref('tabletRail', get().userId, null);
      set({ items: null });
    },
  };
});
