// 그림 칸의 폭을 잰다(창 크기를 바꾸면 다시). ResizeObserver 가 없으면(시험 환경) 처음 값을 쓴다.
import { useEffect, useRef, useState } from 'react';

export function useWidth<T extends HTMLElement>(fallback: number) {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const measure = () => setWidth(Math.max(Math.floor(el.clientWidth), 200));
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return { ref, width };
}
