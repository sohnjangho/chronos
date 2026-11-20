import { create } from 'zustand';

export type ShellDialog = { kind: 'about' } | { kind: 'program'; programId: string } | { kind: 'shortcuts' } | null;
export type DrawerMode = 'closed' | 'open' | 'edit';

interface ShellState {
  dialog: ShellDialog;
  drawer: DrawerMode;
  palette: boolean;
  /** 확대한 창 때문에 숨은 Dock 을 잠시 드러냄. keyboard(Ctrl+Alt+D)면 Dock 항목에 포커스를 준다. */
  dockRevealed: false | 'pointer' | 'keyboard';
  /** 화면 낭독기에 한 번 알릴 글(role=status). */
  announcement: string;
  setDialog(d: ShellDialog): void;
  setDrawer(m: DrawerMode): void;
  setPalette(open: boolean): void;
  setDockRevealed(shown: false | 'pointer' | 'keyboard'): void;
  announce(text: string): void;
}

/** 셸 겹화면 상태: 대화상자·앱 서랍·검색·Dock 드러냄·알림 글. */
export const useShell = create<ShellState>((set) => ({
  dialog: null,
  drawer: 'closed',
  palette: false,
  dockRevealed: false,
  announcement: '',
  setDialog: (dialog) => set({ dialog }),
  setDrawer: (drawer) => set({ drawer }),
  setPalette: (palette) => set({ palette }),
  setDockRevealed: (dockRevealed) => set({ dockRevealed }),
  announce: (announcement) => set({ announcement }),
}));
