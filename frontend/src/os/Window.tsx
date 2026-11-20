import {
  Component,
  Suspense,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  type PointerEvent as ReactPointerEvent,
  type CSSProperties,
  type ReactNode,
  type RefObject,
} from 'react';
import { getProgram } from './registry';
import { playMotion } from './windowMotion';
import { resizeRect, useWindows, workArea, type Edge, type Rect, type Win } from './windowStore';
import { useZoom, zoomOf } from './zoom';

const CANNOT_OPEN = '이 프로그램을 열 수 없습니다';

/** 프로그램 화면이 불러오기·그리기에 실패해도 이 창 안에서만 멈춘다. */
class ProgramBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    return this.state.failed ? <p className="os-win-note">{CANNOT_OPEN}</p> : this.props.children;
  }
}

function ProgramView({ win }: { win: Win }) {
  const program = getProgram(win.programId);
  if (!program) return <p className="os-win-note">{CANNOT_OPEN}</p>;
  const Screen = program.component;
  return (
    <ProgramBoundary>
      <Suspense fallback={<p className="os-win-note">불러오는 중…</p>}>
        <Screen windowId={win.id} params={win.params} />
      </Suspense>
    </ProgramBoundary>
  );
}

type StartDrag = (e: ReactPointerEvent, onDrag: (dx: number, dy: number) => void) => void;

/**
 * 누른 곳에서 움직인 거리를 알린다. 놓기·취소(pointercancel)·창 밖으로 포커스가 나감(blur)·
 * 단추를 뗀 채 움직임(buttons 0)이면 끝난다. 창이 닫히면(언마운트) 듣기를 그만둔다.
 */
function useDrag(): StartDrag {
  const stopRef = useRef<(() => void) | null>(null);
  useEffect(() => () => stopRef.current?.(), []);
  return useCallback((e, onDrag) => {
    e.preventDefault();
    stopRef.current?.();
    // 브라우저에는 늘 있다. jsdom 에는 없다.
    e.currentTarget.setPointerCapture?.(e.pointerId);
    const x0 = e.clientX;
    const y0 = e.clientY;
    const move = (ev: PointerEvent) => (ev.buttons === 0 ? stop() : onDrag(ev.clientX - x0, ev.clientY - y0));
    const stop = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', stop);
      window.removeEventListener('pointercancel', stop);
      window.removeEventListener('blur', stop);
      stopRef.current = null;
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', stop);
    window.addEventListener('pointercancel', stop);
    window.addEventListener('blur', stop);
    stopRef.current = stop;
  }, []);
}

const EDGES: Edge[] = ['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw'];

const isButton = (e: { target: EventTarget }) => (e.target as Element).closest('button') !== null;

/** 신호등 단추와 제목. 끌면 옮기고, 두 번 누르면 확대·복귀. */
function TitleBar({ win, startDrag }: { win: Win; startDrag: StartDrag }) {
  const { close, minimize, toggleMaximize, move } = useWindows.getState();

  function onPointerDown(e: ReactPointerEvent) {
    if (win.maximized || isButton(e)) return;
    const { x, y } = win;
    startDrag(e, (dx, dy) => move(win.id, x + dx, y + dy));
  }

  return (
    <div className="os-win-bar" onPointerDown={onPointerDown} onDoubleClick={(e) => isButton(e) || toggleMaximize(win.id)}>
      <button type="button" className="os-lt os-lt-close" aria-label="닫기" onClick={() => close(win.id)} />
      <button type="button" className="os-lt os-lt-min" aria-label="최소화" onClick={() => minimize(win.id)} />
      <button type="button" className="os-lt os-lt-max" aria-label="확대" onClick={() => toggleMaximize(win.id)} />
      <div className="os-win-title">{win.title}</div>
    </div>
  );
}

/**
 * store 가 붙인 움직임(win.motion)을 그린다. 그리기 전에 걸어서 첫 화면부터 움직임의 시작 모양이다.
 * 확대·복귀는 바로 앞에 그린 자리(last)에서 지금 자리로 간다. 끌기·크기 조절은 움직임이 없다.
 */
function useMotion(ref: RefObject<HTMLDivElement | null>, win: Win, rect: Rect) {
  const last = useRef(rect);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || !win.motion || typeof el.animate !== 'function') return;
    const anim = playMotion(el, { kind: win.motion, rect, from: last.current, programId: win.programId, fromDock: win.fromDock === true });
    return () => anim.cancel();
  }, [win.motion, win.maximized]); // 움직임이 바뀔 때만 다시 건다
  useLayoutEffect(() => {
    last.current = rect;
  });
}

export default function Window({ win, active }: { win: Win; active: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const startDrag = useDrag();
  const zoom = useZoom((s) => zoomOf(s.levels, win.programId));
  const { focus, setBounds } = useWindows.getState();
  const rect = win.maximized ? workArea() : win;
  // 닫히는·최소화되는 동안에는 누를 수 없다(inert). 최소화는 Dock 으로 줄어든 뒤에 숨긴다.
  const leaving = win.motion === 'close' || win.motion === 'minimize';
  useMotion(ref, win, rect);

  // 앞으로 올 때마다(열기·Dock·복귀) 창 안으로 포커스. 이미 창 안에 포커스가 있으면 두기.
  useEffect(() => {
    const el = ref.current;
    if (active && el && !el.contains(document.activeElement)) el.focus();
  }, [active, win.z]);

  const raise = () => {
    if (!active && !leaving) focus(win.id);
  };

  function onResizePointerDown(e: ReactPointerEvent, edge: Edge) {
    const start = { x: win.x, y: win.y, w: win.w, h: win.h };
    startDrag(e, (dx, dy) => setBounds(win.id, resizeRect(start, edge, dx, dy)));
  }

  return (
    <div
      ref={ref}
      role="dialog"
      aria-label={win.title}
      tabIndex={-1}
      hidden={win.minimized && win.motion !== 'minimize'}
      inert={leaving}
      data-motion={win.motion}
      className={`os-win${active ? ' is-active' : ''}`}
      style={{ left: rect.x, top: rect.y, width: rect.w, height: rect.h, zIndex: win.z }}
      onPointerDownCapture={raise}
      onFocus={raise}
    >
      <TitleBar win={win} startDrag={startDrag} />
      <div className="os-win-body">
        <div className="os-win-zoom" data-zoom={zoom} style={{ '--zoom': zoom / 100 } as CSSProperties}>
          <ProgramView win={win} />
        </div>
      </div>
      {!win.maximized &&
        EDGES.map((edge) => (
          <div
            key={edge}
            className={`os-rs os-rs-${edge}`}
            data-resize={edge}
            aria-hidden="true"
            onPointerDown={(e) => onResizePointerDown(e, edge)}
          />
        ))}
    </div>
  );
}
