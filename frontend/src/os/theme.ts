import { create } from 'zustand';
import { loadPref, savePref } from './prefs';

export type Theme = 'light' | 'dark';

interface ThemeState {
  userId: number | null;
  theme: Theme;
  load(userId: number | null): void;
  setTheme(theme: Theme): void;
  toggle(): void;
}

function apply(theme: Theme) {
  document.documentElement.dataset.theme = theme;
}

/** 밝은·어두운 테마. <html data-theme> 로 tokens.css 의 어두운 값이 켜진다. 사용자별로 기억한다. */
export const useTheme = create<ThemeState>((set, get) => ({
  userId: null,
  theme: 'light',
  load(userId) {
    const theme: Theme = loadPref('theme', userId) === 'dark' ? 'dark' : 'light';
    apply(theme);
    set({ userId, theme });
  },
  setTheme(theme) {
    savePref('theme', get().userId, theme);
    apply(theme);
    set({ theme });
  },
  toggle() {
    const theme: Theme = get().theme === 'dark' ? 'light' : 'dark';
    savePref('theme', get().userId, theme);
    apply(theme);
    set({ theme });
  },
}));
