// CPM 그림 판의 상태: 끌어 옮긴 카드 자리(이 창 메모리), 확대·축소·맞춤, 카드를 판 가운데로.
// 그림은 판(.cpm-canvas) 안에서만 스크롤한다. 끌기는 창 전체 포인터를 듣고, 거의 움직이지 않았으면 누르기(고르기)로 본다.
import {
  useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState,
  type Dispatch, type KeyboardEvent, type PointerEvent, type RefObject, type SetStateAction,
} from 'react';
import { CARD_H, CARD_W, PAD, type Network, type Pos } from './layout';

export const ZOOM_STEP = 1.25;
const ZOOM_MIN = 0.1;
const ZOOM_MAX = 2.5;
/** 이만큼(px) 움직이기 전에는 끌기가 아니라 누르기. */
const TAP = 4;
/** 판 크기를 잴 수 없을 때(시험 환경) 맞춤에 쓰는 크기. */
const FALLBACK = { w: 1000, h: 600 };
const clamp = (z: number, lo = ZOOM_MIN, hi = ZOOM_MAX) => Math.min(hi, Math.max(lo, z));

function useLatest<T>(value: T) {
  const ref = useRef(value);
  useLayoutEffect(() => {
    ref.current = value;
  });
  return ref;
}

/** 확대 배율과 그 뒤 스크롤 자리(바뀐 배율로 다시 그린 뒤 맞춘다). */
function useZoom(canvas: RefObject<HTMLDivElement | null>) {
  const [zoom, setZoom] = useState(1);
  const now = useLatest(zoom);
  const after = useRef<((z: number, el: HTMLDivElement) => void) | null>(null);
  useLayoutEffect(() => {
    const el = canvas.current;
    const fn = after.current;
    after.current = null;
    if (el && fn) fn(zoom, el);
  }, [canvas, zoom]);
  /** 판 가운데를 그대로 두고 배율을 바꾼다. */
  const zoomBy = useCallback(
    (f: number) => {
      const el = canvas.current;
      const z0 = now.current;
      if (el) {
        const cx = (el.scrollLeft + el.clientWidth / 2) / z0;
        const cy = (el.scrollTop + el.clientHeight / 2) / z0;
        after.current = (z, box) => {
          box.scrollLeft = cx * z - box.clientWidth / 2;
          box.scrollTop = cy * z - box.clientHeight / 2;
        };
      }
      setZoom(clamp(z0 * f));
    },
    [canvas, now],
  );
  const zoomTo = useCallback((z: number, then: (z: number, el: HTMLDivElement) => void) => {
    after.current = then;
    setZoom(z);
  }, []);
  return { zoom, zoomBy, zoomTo };
}

export function useNetwork(graph: Network, onTap: (id: string) => void) {
  const canvasRef = useRef<HTMLDivElement>(null);
  const [moved, setMoved] = useState<Record<string, Pos>>({});
  const { zoom, zoomBy, zoomTo } = useZoom(canvasRef);
  const pos = useMemo(() => new Map(graph.nodes.map((n) => [n.id, moved[n.id] ?? { x: n.x, y: n.y }])), [graph, moved]);
  const size = useMemo(() => {
    let w = graph.width;
    let h = graph.height;
    for (const p of pos.values()) {
      w = Math.max(w, p.x + CARD_W + PAD);
      h = Math.max(h, p.y + CARD_H + PAD);
    }
    return { w, h };
  }, [graph, pos]);
  const latest = useLatest({ graph, pos, zoom, onTap, size });

  const center = useCallback((id: string) => {
    const el = canvasRef.current;
    const p = latest.current.pos.get(id);
    if (!el || !p) return;
    const z = latest.current.zoom;
    el.scrollLeft = (p.x + CARD_W / 2) * z - el.clientWidth / 2;
    el.scrollTop = (p.y + CARD_H / 2) * z - el.clientHeight / 2;
  }, [latest]);

  // 다음 그림 뒤에 가운데로(보기를 바꾼 뒤에야 그 카드 자리가 생길 때가 있다).
  const [pending, setPending] = useState<{ id: string } | null>(null);
  useLayoutEffect(() => {
    if (!pending) return;
    if (pos.has(pending.id)) center(pending.id);
    setPending(null);
  }, [pending, pos, center]);
  const centerSoon = useCallback((id: string) => setPending({ id }), []);

  const fit = useCallback(() => {
    const el = canvasRef.current;
    const { w, h } = latest.current.size;
    const bw = el?.clientWidth || FALLBACK.w;
    const bh = el?.clientHeight || FALLBACK.h;
    zoomTo(clamp(Math.min((bw - 16) / w, (bh - 16) / h), ZOOM_MIN, 1), (_z, box) => {
      box.scrollLeft = 0;
      box.scrollTop = 0;
    });
  }, [latest, zoomTo]);

  const drag = useCardDrag(latest, setMoved);
  const [active, setActive] = useState<string | null>(null);
  /** Enter·Space 는 고르기, 화살표는 옆 열·위아래 줄의 카드로 초점을 옮긴다. */
  const onKey = useCallback((id: string, e: KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      latest.current.onTap(id);
      return;
    }
    const to = neighbour(latest.current.graph, id, e.key);
    if (to === undefined) return;
    e.preventDefault();
    [...(canvasRef.current?.querySelectorAll<SVGGElement>('[data-node]') ?? [])].find((g) => g.getAttribute('data-node') === to)?.focus();
  }, [latest]);
  const autoLayout = useCallback(() => setMoved({}), []);
  return { canvasRef, pos, size, zoom, zoomBy, fit, center, centerSoon, autoLayout, onDown: drag, onKey, active, setActive };
}

const STEP: Record<string, [number, number]> = { ArrowRight: [1, 0], ArrowLeft: [-1, 0], ArrowDown: [0, 1], ArrowUp: [0, -1] };

/** 화살표 key 로 갈 카드: 옆 열은 같은 줄(없으면 그 열의 마지막 줄), 위아래는 같은 열. 화살표가 아니면 undefined, 갈 곳이 없으면 그 카드. */
function neighbour(graph: Network, id: string, key: string): string | undefined {
  const step = STEP[key];
  const here = graph.nodes.find((n) => n.id === id);
  if (!step || !here) return undefined;
  const col = graph.nodes.filter((n) => n.col === here.col + step[0]);
  if (col.length === 0) return id;
  const row = step[0] ? Math.min(here.row, Math.max(...col.map((n) => n.row))) : here.row + step[1];
  return col.find((n) => n.row === row)?.id ?? id;
}

export type Net = ReturnType<typeof useNetwork>;

type Latest = RefObject<{ graph: Network; pos: ReadonlyMap<string, Pos>; zoom: number; onTap: (id: string) => void }>;

/** 카드 끌기: 자리만 바꾼다(서버에 보내지 않음). Esc·포인터 취소면 제자리로. 거의 안 움직였으면 누르기. */
function useCardDrag(latest: Latest, setMoved: Dispatch<SetStateAction<Record<string, Pos>>>) {
  const stop = useRef<(() => void) | null>(null);
  useEffect(() => () => stop.current?.(), []);
  return useCallback(
    (id: string, e: PointerEvent) => {
      if (e.button !== 0) return;
      stop.current?.();
      const start = latest.current.pos.get(id);
      if (!start) return;
      const z = latest.current.zoom;
      const [x0, y0] = [e.clientX, e.clientY];
      let dragging = false;
      const place = (p: Pos) => setMoved((m) => ({ ...m, [id]: p }));
      const move = (ev: globalThis.PointerEvent) => {
        if (!dragging && Math.hypot(ev.clientX - x0, ev.clientY - y0) < TAP) return;
        dragging = true;
        place({ x: Math.max(0, Math.round(start.x + (ev.clientX - x0) / z)), y: Math.max(0, Math.round(start.y + (ev.clientY - y0) / z)) });
      };
      const end = () => {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', up);
        window.removeEventListener('pointercancel', cancel);
        window.removeEventListener('keydown', esc);
        stop.current = null;
      };
      const up = () => {
        end();
        if (!dragging) latest.current.onTap(id);
      };
      const cancel = () => {
        end();
        if (dragging) place(start);
      };
      const esc = (ev: globalThis.KeyboardEvent) => ev.key === 'Escape' && cancel();
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up);
      window.addEventListener('pointercancel', cancel);
      window.addEventListener('keydown', esc);
      stop.current = end;
    },
    [latest, setMoved],
  );
}
