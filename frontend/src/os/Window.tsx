import { Component, Suspense, useEffect, useRef, type PointerEvent as ReactPointerEvent, type ReactNode } from 'react';
import { getProgram } from './registry';
import { useWindows, workArea, type Win } from './windowStore';

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

/** 누른 곳에서 움직인 거리를 놓을 때까지 알린다. */
function startDrag(e: ReactPointerEvent, onDrag: (dx: number, dy: number) => void) {
  e.preventDefault();
  const x0 = e.clientX;
  const y0 = e.clientY;
  const move = (ev: PointerEvent) => onDrag(ev.clientX - x0, ev.clientY - y0);
  const up = () => {
    window.removeEventListener('pointermove', move);
    window.removeEventListener('pointerup', up);
  };
  window.addEventListener('pointermove', move);
  window.addEventListener('pointerup', up);
}

/** 오른쪽 가장자리 · 아래 가장자리 · 오른쪽 아래 모서리. ax, ay = 너비·높이에 곱할 값. */
const RESIZERS = [
  { edge: 'e', ax: 1, ay: 0 },
  { edge: 's', ax: 0, ay: 1 },
  { edge: 'se', ax: 1, ay: 1 },
];

const isButton = (e: { target: EventTarget }) => (e.target as Element).closest('button') !== null;

/** 신호등 버튼과 제목. 끌면 옮기고, 두 번 누르면 확대·복귀. */
function TitleBar({ win }: { win: Win }) {
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

export default function Window({ win, active }: { win: Win; active: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const { focus, resize } = useWindows.getState();
  const rect = win.maximized ? workArea() : win;

  useEffect(() => ref.current?.focus(), []);

  const raise = () => {
    if (!active) focus(win.id);
  };

  function onResizePointerDown(e: ReactPointerEvent, ax: number, ay: number) {
    const { w, h } = win;
    startDrag(e, (dx, dy) => resize(win.id, w + dx * ax, h + dy * ay));
  }

  return (
    <div
      ref={ref}
      role="dialog"
      aria-label={win.title}
      tabIndex={-1}
      hidden={win.minimized}
      className={`os-win${active ? ' is-active' : ''}`}
      style={{ left: rect.x, top: rect.y, width: rect.w, height: rect.h, zIndex: win.z }}
      onPointerDownCapture={raise}
      onFocus={raise}
    >
      <TitleBar win={win} />
      <div className="os-win-body">
        <ProgramView win={win} />
      </div>
      {!win.maximized &&
        RESIZERS.map((r) => (
          <div
            key={r.edge}
            className={`os-rs os-rs-${r.edge}`}
            data-resize={r.edge}
            aria-hidden="true"
            onPointerDown={(e) => onResizePointerDown(e, r.ax, r.ay)}
          />
        ))}
    </div>
  );
}
