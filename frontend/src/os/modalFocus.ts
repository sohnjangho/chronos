import { useEffect, useState, type KeyboardEvent, type RefObject } from 'react';

const FOCUSABLE = 'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * aria-modal 겹화면(앱 서랍·검색·정보 대화상자)의 포커스: 연 곳을 기억했다가 닫히면 돌려주고,
 * 열린 동안 Tab·Shift+Tab 이 안에서만 돈다. 돌려준 onKeyDown 을 겹화면 바깥 틀에 단다.
 */
export function useModalFocus(ref: RefObject<HTMLElement | null>) {
  // 처음 그릴 때(autoFocus 가 포커스를 옮기기 전) 연 곳을 잡는다.
  const [opener] = useState(() => document.activeElement as HTMLElement | null);
  useEffect(() => {
    const node = ref.current;
    return () => {
      // StrictMode(개발)의 가짜 언마운트에서는 겹화면이 그대로 붙어 있다 → 진짜로 닫힐 때만 돌려준다.
      if (node?.isConnected) return;
      if (opener && opener !== document.body && opener.isConnected) opener.focus();
    };
  }, [opener, ref]);
  return (e: KeyboardEvent) => {
    if (e.key !== 'Tab' || !ref.current) return;
    const items = [...ref.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    const at = document.activeElement;
    if (e.shiftKey && (at === first || !ref.current.contains(at))) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && at === last) {
      e.preventDefault();
      first.focus();
    }
  };
}
