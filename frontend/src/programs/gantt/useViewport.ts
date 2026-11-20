// 간트 보기 창: 차트 본문(.gt-body)만 스크롤하고 날짜 머리·자원 줄(가로)·왼쪽 표(세로)가 따라온다.
// 보이는 줄(앞뒤 여유 포함)만 그린다. 눈금은 '맞춤'(창 폭에 맞춤, pxPerDay=null) 또는 확대·축소한 값.
import { useCallback, useLayoutEffect, useRef, useState, type RefObject } from 'react';
import { ROW_H } from '../../shared/gantt/Bars';
import { addDays, daysBetween, makeScale, width, x, type Scale } from '../../shared/gantt/scale';

const PAD = 7;
const OVERSCAN = 6;
/** 크기를 잴 수 없을 때(시험 환경) 쓰는 차트 창 크기. */
const FALLBACK = { w: 1000, h: 600 };
const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, n));

function useSize(bodyRef: RefObject<HTMLDivElement | null>) {
  const [size, setSize] = useState(FALLBACK);
  const [barH, setBarH] = useState(0);
  useLayoutEffect(() => {
    const el = bodyRef.current;
    if (!el) return;
    const measure = () => {
      setSize({ w: el.clientWidth || FALLBACK.w, h: el.clientHeight || FALLBACK.h });
      setBarH(el.offsetHeight && el.clientHeight ? el.offsetHeight - el.clientHeight : 0);
    };
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [bodyRef]);
  return { size, scrollbarH: barH };
}

interface NavCtx {
  body: RefObject<HTMLDivElement | null>;
  /** 다음 그림 뒤에 맞출 가로 스크롤 자리. */
  anchor: RefObject<number | null>;
  scale: Scale;
  total: number;
  size: { w: number; h: number };
  sync(): void;
  setZoomPx(px: number | null): void;
}

/** 확대·축소·맞춤·이동. 눈금을 바꾸는 것은 anchor 에 자리를 남기고 다시 그린 뒤 맞춘다. */
function makeNav({ body, anchor, scale, total, size, sync, setZoomPx }: NavCtx) {
  const scrollTo = (left: number) => {
    if (!body.current) return;
    body.current.scrollLeft = clamp(left, 0, Math.max(0, total - size.w));
    sync();
  };
  return {
    zoom(f: number) {
      const center = ((body.current?.scrollLeft ?? 0) + size.w / 2) / scale.pxPerDay;
      const px = clamp(scale.pxPerDay * f, 0.2, 80);
      anchor.current = center * px - size.w / 2;
      setZoomPx(px);
    },
    fit() {
      anchor.current = 0;
      setZoomPx(null);
    },
    /** start~end 가 창에 꽉 차게(앞뒤 2일 여유). */
    fitRange(start: string, end: string) {
      const px = clamp(size.w / (daysBetween(start, end) + 5), 0.2, 80);
      anchor.current = x({ ...scale, pxPerDay: px }, addDays(start, -2));
      setZoomPx(px);
    },
    /** 그 날이 창 왼쪽 1/3 쯤 오게. */
    toDate: (iso: string) => scrollTo(x(scale, iso) - size.w / 3),
    page: (dir: 1 | -1) => scrollTo((body.current?.scrollLeft ?? 0) + dir * size.w * 0.8),
    /** 그 줄이 창 가운데 오게(이미 보이면 그대로). */
    toRow(i: number) {
      const b = body.current;
      const y = i * ROW_H;
      if (!b || (y >= b.scrollTop && y + ROW_H <= b.scrollTop + size.h)) return;
      b.scrollTop = Math.max(0, y - size.h / 2 + ROW_H / 2);
      sync();
    },
    /** 맨 위 줄로(묶는 기준을 바꿨을 때). */
    top() {
      if (!body.current) return;
      body.current.scrollTop = 0;
      sync();
    },
    wheel(dy: number) {
      if (!body.current) return;
      body.current.scrollTop = Math.max(0, body.current.scrollTop + dy);
      sync();
    },
  };
}

export function useViewport(range: { start: string; end: string }, rowCount: number) {
  const bodyRef = useRef<HTMLDivElement>(null);
  const headRef = useRef<HTMLDivElement>(null);
  const leftRef = useRef<HTMLDivElement>(null);
  const resRef = useRef<HTMLDivElement>(null);
  const { size, scrollbarH } = useSize(bodyRef);
  const [top, setTop] = useState(0);
  const [zoomPx, setZoomPx] = useState<number | null>(null);
  const anchor = useRef<number | null>(null);

  const fit = makeScale(range.start, range.end, size.w, PAD);
  const scale: Scale = zoomPx === null ? fit : { ...fit, pxPerDay: zoomPx };
  const total = width(scale);

  const sync = useCallback(() => {
    const b = bodyRef.current;
    if (!b) return;
    if (headRef.current) headRef.current.scrollLeft = b.scrollLeft;
    if (resRef.current) resRef.current.scrollLeft = b.scrollLeft;
    if (leftRef.current) leftRef.current.scrollTop = b.scrollTop;
    setTop(b.scrollTop);
  }, []);
  // 눈금이 바뀐 뒤(다시 그린 뒤) 가로 자리를 맞춘다.
  useLayoutEffect(() => {
    if (anchor.current === null || !bodyRef.current) return;
    bodyRef.current.scrollLeft = Math.max(0, anchor.current);
    anchor.current = null;
    sync();
  });
  const nav = makeNav({ body: bodyRef, anchor, scale, total, size, sync, setZoomPx });

  const first = Math.max(0, Math.floor(top / ROW_H) - OVERSCAN);
  const last = Math.min(rowCount - 1, Math.ceil((top + size.h) / ROW_H) + OVERSCAN);
  return { bodyRef, headRef, leftRef, resRef, scale, total, size, scrollbarH, first, last, sync, nav };
}

export type Viewport = ReturnType<typeof useViewport>;
