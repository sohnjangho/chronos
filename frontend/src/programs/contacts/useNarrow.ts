// 연락처 창을 몇 칸으로 보일지(Task 105). 스마트폰 → 목록 → 대화 한 화면씩. 태블릿 → PC 와 같은 두 칸, 세로로 세우면
// 사람을 고른 뒤 주소록이 접힌다. PC 창 → 창 몸의 폭이 720 이하면 한 화면씩(재지 못했으면 — 시험 환경 — 두 칸).
// 태블릿 오른쪽 AI 패널이 열리면 몸이 720 보다 좁아지지만 태블릿은 폭이 아니라 기기로 정한다(두 칸이 되게).
import { useEffect, useState, type RefObject } from 'react';
import { useActiveDevice, type ResolvedDevice } from '../../os/useIsMobile';

export const NARROW_MAX = 720;

export type ContactsLayout = 'two' | 'folded' | 'single';

export function contactsLayout(device: ResolvedDevice, width: number | null, portrait: boolean): ContactsLayout {
  if (device === 'phone') return 'single';
  if (device === 'tablet') return portrait ? 'folded' : 'two';
  return width !== null && width <= NARROW_MAX ? 'single' : 'two';
}

/** 화면이 세로로 서 있나(높이 > 폭). 돌리면 다시. */
function usePortrait(): boolean {
  const read = () => window.innerHeight > window.innerWidth;
  const [portrait, setPortrait] = useState(read);
  useEffect(() => {
    const onResize = () => setPortrait(read());
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);
  return portrait;
}

/** 칸의 폭. ResizeObserver 가 없으면(시험 환경) null. */
function useWidth(ref: RefObject<HTMLElement | null>): number | null {
  const [width, setWidth] = useState<number | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const first = el.getBoundingClientRect().width;
    if (first > 0) setWidth(first);
    const ro = new ResizeObserver((entries) => {
      const w = entries[entries.length - 1]?.contentRect.width;
      if (w) setWidth(w);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return width;
}

export function useNarrow(ref: RefObject<HTMLElement | null>): ContactsLayout {
  const device = useActiveDevice();
  const width = useWidth(ref);
  const portrait = usePortrait();
  return contactsLayout(device, width, portrait);
}
