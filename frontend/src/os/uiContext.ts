// 화면 맥락: 창이 "지금 무엇을 보여 주는지"(프로그램·일정·고른 액티비티)를 알리는 OS 저장소.
// 에이전트 대화가 질문과 함께 보낸다(Task 10 의 ui). 프로그램끼리는 import 하지 않으므로 여기(os)에 둔다.
import { create } from 'zustand';
import { useWindows, type Win } from './windowStore';

/** 한 창이 알리는 맥락. schedule_id 가 없으면 받는 쪽이 OS 의 지금 일정을 쓴다. */
export interface UiContext {
  program: string;
  schedule_id?: number | null;
  selected_activity?: string | null;
}

interface UiContextState {
  /** 창 id → 그 창이 알린 맥락. */
  byWindow: Record<string, UiContext>;
  /** 창이 자기 맥락을 알린다(바뀔 때마다 다시 부른다). */
  publish(windowId: string, ctx: UiContext): void;
  /** 알린 맥락을 지운다. 창이 닫히면 저절로 지워진다. */
  clear(windowId: string): void;
  reset(): void;
}

export const useUiContext = create<UiContextState>((set) => ({
  byWindow: {},
  publish: (windowId, ctx) => set((s) => ({ byWindow: { ...s.byWindow, [windowId]: ctx } })),
  clear: (windowId) =>
    set((s) => (windowId in s.byWindow ? { byWindow: Object.fromEntries(Object.entries(s.byWindow).filter(([id]) => id !== windowId)) } : {})),
  reset: () => set({ byWindow: {} }),
}));

/**
 * 사용자에게 보이는 창 가운데 맨 앞(최소화한 창과 except 프로그램의 창은 건너뛴다).
 * except 프로그램의 창이 확대돼 있으면 그 뒤 창은 가려져 있으므로 없다.
 */
export function frontVisibleWindow(wins: Win[], except: string): Win | null {
  const shown = wins.filter((w) => !w.minimized).sort((a, b) => b.z - a.z);
  for (const w of shown) {
    if (w.programId !== except) return w;
    if (w.maximized) return null;
  }
  return null;
}

// 창이 닫히면(닫기·모두 닫기·초기화) 그 창이 알린 맥락도 지운다.
useWindows.subscribe((s) => {
  const { byWindow } = useUiContext.getState();
  const ids = Object.keys(byWindow);
  if (ids.length === 0) return;
  const open = new Set(s.wins.map((w) => w.id));
  if (ids.every((id) => open.has(id))) return;
  useUiContext.setState({ byWindow: Object.fromEntries(Object.entries(byWindow).filter(([id]) => open.has(id))) });
});
