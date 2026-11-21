// 자료함 미리 보기 폭 조절 훅(사용자별 localStorage 저장).
import { useEffect, useRef, useState } from 'react';

export const DEFAULT_DETAIL_WIDTH = 440;
export const MIN_DETAIL_WIDTH = 280;
export const MAX_DETAIL_WIDTH = 720;

const widthKey = (userId: number) => `chronos.library.detailWidth.${userId}`;
const clampWidth = (w: number) => Math.min(MAX_DETAIL_WIDTH, Math.max(MIN_DETAIL_WIDTH, w));

function loadDetailWidth(userId: number): number {
  try {
    const raw = Number(localStorage.getItem(widthKey(userId)));
    if (Number.isFinite(raw) && raw >= MIN_DETAIL_WIDTH && raw <= MAX_DETAIL_WIDTH) return raw;
  } catch {
    // ignore storage errors
  }
  return DEFAULT_DETAIL_WIDTH;
}

function saveDetailWidth(userId: number, w: number) {
  try {
    localStorage.setItem(widthKey(userId), String(w));
  } catch {
    // ignore storage errors
  }
}

export function useDetailWidth(userId: number) {
  const [width, setWidth] = useState(() => loadDetailWidth(userId));
  const dragRef = useRef<{ startX: number; startW: number } | null>(null);

  useEffect(() => {
    setWidth(loadDetailWidth(userId));
  }, [userId]);

  const startResize = (e: React.PointerEvent) => {
    e.preventDefault();
    dragRef.current = { startX: e.clientX, startW: width };
    const onMove = (ev: PointerEvent) => {
      if (!dragRef.current) return;
      setWidth(clampWidth(dragRef.current.startW + (dragRef.current.startX - ev.clientX)));
    };
    const onUp = (ev: PointerEvent) => {
      if (dragRef.current) {
        const finalW = clampWidth(dragRef.current.startW + (dragRef.current.startX - ev.clientX));
        setWidth(finalW);
        saveDetailWidth(userId, finalW);
      }
      dragRef.current = null;
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
    };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
  };

  const stepResize = (delta: number) => {
    const next = clampWidth(width + delta);
    setWidth(next);
    saveDetailWidth(userId, next);
  };

  return { width, startResize, stepResize };
}
