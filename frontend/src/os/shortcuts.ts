import { useEffect } from 'react';
import { arrangeWindows, closeAllWindows, minimizeAllWindows, zoomActive } from './commands';
import { useContextPanel } from './contextStore';
import { useSession } from './session';
import { useShell } from './shell';
import { useWindows } from './windowStore';

const isEditable = (t: EventTarget | null) =>
  t instanceof HTMLElement && (t.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName));

/** Ctrl+Alt 조합(브라우저 예약키를 피함). e.code 로 본다(맥 Option 은 e.key 를 바꾼다). */
const CTRL_ALT: Record<string, () => void> = {
  KeyS: () => arrangeWindows('split'),
  KeyG: () => arrangeWindows('grid'),
  KeyC: () => arrangeWindows('cascade'),
  KeyM: minimizeAllWindows,
  KeyQ: closeAllWindows,
  KeyW: () => useWindows.getState().closeActive(),
  Equal: () => zoomActive('in'),
  Minus: () => zoomActive('out'),
  Digit0: () => zoomActive('reset'),
  KeyD: () => useShell.getState().setDockRevealed(useShell.getState().dockRevealed ? false : 'keyboard'),
  Period: () => useContextPanel.getState().toggle(),
};

/** 지금 처리할 셸 명령. 없으면 null(앱에 맡김). 잠금 중·입력칸 안에서는 넘긴다(Ctrl+K 는 입력칸에서도 연다). */
export function shortcutFor(e: KeyboardEvent, extra: Record<string, () => void> = {}): (() => void) | null {
  if (useSession.getState().locked) return null;
  if (e.ctrlKey && !e.altKey && e.code === 'KeyK') return () => useShell.getState().setPalette(true);
  if (isEditable(e.target)) return null;
  if (e.key === '/' && !e.ctrlKey && !e.altKey && !e.metaKey) return () => useShell.getState().setPalette(true);
  if (e.ctrlKey && !e.altKey && e.code === 'Backquote') return () => useWindows.getState().nextWindow();
  if (e.ctrlKey && e.altKey) return extra[e.code] ?? CTRL_ALT[e.code] ?? null;
  return null;
}

const NONE: Record<string, () => void> = {};

/** 문서 전체 단축키. extra 는 다른 셸 부품이 더하는 Ctrl+Alt 조합(예 Context 패널의 Period). 모듈 상수로 넘긴다. */
export function useShellShortcuts(extra: Record<string, () => void> = NONE) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const run = shortcutFor(e, extra);
      if (!run) return;
      e.preventDefault();
      run();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [extra]);
}
