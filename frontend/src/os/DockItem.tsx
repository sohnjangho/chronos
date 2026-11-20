import { useRef, useState, type PointerEvent as ReactPointerEvent, type Ref } from 'react';
import type { DockEntry } from './dockStore';
import { AppsIcon } from './icons';
import ProgramIcon from './ProgramIcon';

export interface DockItemProps {
  entry: Exclude<DockEntry, { kind: 'sep' }>;
  index: number;
  name: string;
  /** 화면 낭독기용 상태(「, 실행 중」 등). */
  state: string;
  badge: number;
  running: boolean;
  launching: boolean;
  /** 확대 배율. null 이면 확대하지 않음(동작 줄이기). */
  scale: number | null;
  tabStop: boolean;
  menuOpen: boolean;
  buttonRef: Ref<HTMLButtonElement>;
  tileRef: Ref<HTMLSpanElement>;
  onLaunch(): void;
  onMenu(): void;
  onFocusItem(): void;
}

const LONG_PRESS_MS = 500;
const LONG_PRESS_SLOP = 8;

/** 터치·펜 길게 누르기(0.5초)로 메뉴. 8px 넘게 움직이면 취소. 메뉴가 열린 누름은 실행하지 않는다. */
function useLongPress(onMenu: () => void) {
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const start = useRef({ x: 0, y: 0 });
  const fired = useRef(false);
  const cancel = () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
  };
  return {
    onPointerDown(e: ReactPointerEvent) {
      if (e.pointerType === 'mouse') return;
      start.current = { x: e.clientX, y: e.clientY };
      fired.current = false;
      cancel();
      timer.current = setTimeout(() => {
        fired.current = true;
        onMenu();
      }, LONG_PRESS_MS);
    },
    onPointerMove(e: ReactPointerEvent) {
      if (timer.current && Math.hypot(e.clientX - start.current.x, e.clientY - start.current.y) > LONG_PRESS_SLOP) cancel();
    },
    onPointerUp: cancel,
    /** 길게 눌러 메뉴를 연 누름이면 true(그 click 은 버린다). */
    consumeFired() {
      const was = fired.current;
      fired.current = false;
      return was;
    },
  };
}

/** Dock 항목: 48px 타일(+ 배지), 4px 실행 점 자리, 가리킴·포커스 때 위쪽 이름 말풍선. */
export default function DockItem(p: DockItemProps) {
  const [hover, setHover] = useState(false);
  const [focused, setFocused] = useState(false);
  const press = useLongPress(p.onMenu);
  const classes = ['os-dock-item', p.launching && 'is-launching'].filter(Boolean).join(' ');
  return (
    <div className={classes}>
      {(hover || focused) && !p.menuOpen && (
        <span role="tooltip" className="os-dock-tip">
          {p.name}
        </span>
      )}
      <button
        ref={p.buttonRef}
        type="button"
        className="os-dock-btn"
        aria-label={`${p.name}${p.state}`}
        tabIndex={p.tabStop ? 0 : -1}
        onClick={() => !press.consumeFired() && p.onLaunch()}
        onContextMenu={(e) => {
          e.preventDefault();
          p.onMenu();
        }}
        onPointerEnter={() => setHover(true)}
        onPointerLeave={() => setHover(false)}
        onPointerDown={press.onPointerDown}
        onPointerMove={press.onPointerMove}
        onPointerUp={press.onPointerUp}
        onFocus={() => {
          setFocused(true);
          p.onFocusItem();
        }}
        onBlur={() => setFocused(false)}
      >
        <DockTile {...p} />
      </button>
      <span className={`os-dock-dot${p.running ? ' is-on' : ''}`} aria-hidden="true" />
    </div>
  );
}

/** 48px 타일(확대 배율 적용, 아래 가운데 축) + 오른쪽 위 배지. 앱 목록은 격자 아이콘. */
function DockTile({ entry, index, scale, badge, tileRef }: DockItemProps) {
  return (
    <span ref={tileRef} className="os-dock-tile" data-dock-index={index} style={scale === null ? undefined : { transform: `scale(${scale})` }}>
      {entry.kind === 'apps' ? (
        <span className="os-icon os-tone-slate os-icon-apps" aria-hidden="true">
          <AppsIcon />
        </span>
      ) : (
        <ProgramIcon program={entry.program} size={48} />
      )}
      {badge > 0 && <span className="os-dock-badge">{badge}</span>}
    </span>
  );
}
