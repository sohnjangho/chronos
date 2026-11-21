import { create } from 'zustand';
import { loadPref, savePref } from './prefs';
import { SCHEDULE_TOOLS, type ProgramManifest } from './registry';

export type DockEntry =
  | { kind: 'apps' }
  | { kind: 'sep'; key: string }
  | { kind: 'program'; program: ProgramManifest; pinned: boolean };

interface DockState {
  userId: number | null;
  /** 사용자가 정한 Dock 프로그램 차례. null 이면 기본(등록 차례 전부). */
  pinned: string[] | null;
  load(userId: number | null): void;
  pin(id: string, allIds: string[]): void;
  unpin(id: string, allIds: string[]): void;
  /** id 를 차례 to 자리로 옮긴다. */
  move(id: string, to: number, allIds: string[]): void;
  resetDefault(): void;
}

/**
 * 저장된 차례의 옛 일정판(schedule) 자리에 나뉜 도구 프로그램 넷을 넣는다(이미 있는 것은 그 자리 그대로).
 * 일정판을 Dock 에 두었던 사람은 그 넷을 모두 Dock 에서 쓰던 셈이다.
 */
function migrated(ids: string[]): string[] {
  if (!ids.includes('schedule')) return ids;
  return ids.flatMap((id) => (id === 'schedule' ? SCHEDULE_TOOLS.filter((t) => !ids.includes(t)) : [id]));
}

/** Dock 에 둘 프로그램 차례와 바꾸기. 사용자별로 저장한다(실패해도 메모리에는 남는다). */
export const useDock = create<DockState>((set, get) => {
  const save = (pinned: string[]) => {
    savePref('dock', get().userId, pinned);
    set({ pinned });
  };
  const current = (allIds: string[]) => get().pinned ?? allIds;
  return {
    userId: null,
    pinned: null,
    load(userId) {
      const saved = loadPref('dock', userId);
      const ids = Array.isArray(saved) ? saved.filter((x): x is string => typeof x === 'string') : null;
      const pinned = ids && migrated(ids);
      if (pinned && pinned !== ids) savePref('dock', userId, pinned);
      set({ userId, pinned });
    },
    pin: (id, allIds) => save([...current(allIds).filter((x) => x !== id), id]),
    unpin: (id, allIds) => save(current(allIds).filter((x) => x !== id)),
    move(id, to, allIds) {
      const rest = current(allIds).filter((x) => x !== id);
      rest.splice(Math.max(0, Math.min(to, rest.length)), 0, id);
      save(rest);
    },
    resetDefault() {
      savePref('dock', get().userId, null);
      set({ pinned: null });
    },
  };
});

/**
 * Dock 에 그릴 차례: 「앱 목록」, 고정한 프로그램(볼 수 있는 것만), 그리고 고정하지 않았지만 실행 중인 프로그램.
 * 고정 차례가 [시스템…][업무…] 로 깔끔히 나뉘면 그 경계에 구분선, 실행 중 임시 항목 앞에도 구분선.
 */
export function dockEntries(allowed: ProgramManifest[], pinned: string[] | null, running: Set<string>): DockEntry[] {
  const byId = new Map(allowed.map((p) => [p.id, p]));
  const fixed = (pinned ?? allowed.map((p) => p.id)).flatMap((id) => byId.get(id) ?? []);
  const out: DockEntry[] = [{ kind: 'apps' }];
  const firstWork = fixed.findIndex((p) => p.kind === 'work');
  const clean = firstWork > 0 && fixed.slice(firstWork).every((p) => p.kind === 'work');
  fixed.forEach((program, i) => {
    if (clean && i === firstWork) out.push({ kind: 'sep', key: 'sep-kind' });
    out.push({ kind: 'program', program, pinned: true });
  });
  const extra = allowed.filter((p) => running.has(p.id) && !fixed.includes(p));
  if (extra.length) out.push({ kind: 'sep', key: 'sep-running' });
  for (const program of extra) out.push({ kind: 'program', program, pinned: false });
  return out;
}
