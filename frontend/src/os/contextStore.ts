import { create } from 'zustand';
import { useWindows } from './windowStore';

export const PANEL_WIDTH = 420;
export const PANEL_MIN = 320;
export const PANEL_MAX = 720;
/** 이 폭 이하 화면에서는 패널이 창 위를 서랍처럼 덮는다(창 영역을 줄이지 않음). */
const OVERLAY_BELOW = 1024;

export type ContextTab = 'ai' | 'evidence' | 'activity';

/** 패널을 부른 창(마지막으로 열거나 앞으로 가져온 창). 창이 닫혀도 이름은 남는다. */
export interface ContextSource {
  id: string;
  programId: string;
  title: string;
  params?: Record<string, string>;
}

interface ContextPanelState {
  open: boolean;
  width: number;
  tab: ContextTab;
  source: ContextSource | null;
  toggle(): void;
  close(): void;
  setWidth(px: number): void;
  setTab(tab: ContextTab): void;
  setSource(source: ContextSource | null): void;
  reset(): void;
}

const applyInset = (open: boolean, width: number) =>
  useWindows.getState().setInsetRight(open && window.innerWidth > OVERLAY_BELOW ? width : 0);

/** Context 패널(오른쪽 420px, 왼쪽 가장자리로 폭 조절). 열면 창 영역이 그만큼 좁아진다. */
export const useContextPanel = create<ContextPanelState>((set, get) => ({
  open: false,
  width: PANEL_WIDTH,
  tab: 'ai',
  source: null,
  toggle() {
    if (get().open) return get().close();
    set({ open: true });
    applyInset(true, get().width);
  },
  close() {
    set({ open: false });
    applyInset(false, 0);
    const src = get().source;
    if (src && useWindows.getState().wins.some((w) => w.id === src.id)) useWindows.getState().focus(src.id);
  },
  setWidth(px) {
    const width = Math.round(Math.max(PANEL_MIN, Math.min(PANEL_MAX, px)));
    set({ width });
    applyInset(get().open, width);
  },
  setTab: (tab) => set({ tab }),
  setSource: (source) => set({ source }),
  reset() {
    set({ open: false, width: PANEL_WIDTH, tab: 'ai', source: null });
    applyInset(false, 0);
  },
}));
