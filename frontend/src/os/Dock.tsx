import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type RefObject,
} from 'react';
import { useApprovals } from './approvals';
import DockItem, { type DockItemProps } from './DockItem';
import DockMenu from './DockMenu';
import { dockEntries, useDock, type DockEntry } from './dockStore';
import { programs } from './registry';
import { useSession } from './session';
import { useShell } from './shell';
import { prefersReducedMotion, setDockAnchor } from './windowMotion';
import { activeWindow, useWindows } from './windowStore';
import './dock.css';

const MAG_MAX = 1.4;
const MAG_RANGE = 120;

/** 포인터와 타일 가운데의 가로 거리 d(px)에 따른 확대 배율: 0 이면 1.4, 120 이상이면 1, 그 사이는 코사인. */
export function magnification(d: number): number {
  if (d >= MAG_RANGE) return 1;
  return 1 + ((MAG_MAX - 1) * (1 + Math.cos((Math.PI * d) / MAG_RANGE))) / 2;
}

type Item = Exclude<DockEntry, { kind: 'sep' }>;

/** 새로 실행된 프로그램 또는 새 승인 건 도착 시 짧은 튀어 오름. 동작 줄이기면 없다. */
function useLaunching(running: Set<string>, approvals: number): string[] {
  const prev = useRef(running);
  const prevApprovals = useRef(approvals);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const [launching, setLaunching] = useState<string[]>([]);
  const key = [...running].sort().join(',');
  useEffect(() => {
    const added = [...running].filter((id) => !prev.current.has(id));
    prev.current = running;
    if (!added.length || prefersReducedMotion()) return;
    setLaunching((l) => [...l, ...added]);
    timers.current.push(setTimeout(() => setLaunching((l) => l.filter((id) => !added.includes(id))), 700));
  }, [key]); // running 은 key(정렬한 id 글)로 본다
  useEffect(() => {
    const grew = approvals > prevApprovals.current;
    prevApprovals.current = approvals;
    if (!grew || prefersReducedMotion()) return;
    setLaunching((l) => [...l, 'approvals']);
    timers.current.push(setTimeout(() => setLaunching((l) => l.filter((id) => id !== 'approvals')), 700));
  }, [approvals]);
  useEffect(() => () => timers.current.forEach(clearTimeout), []);
  return launching;
}

/** 확대한 창이 있으면 숨는다. 아래 끝 띠에 0.2초, Ctrl+Alt+D 로 드러나고, 위로 벗어남 0.8초·바깥 누름·Esc 로 다시 숨는다. */
function useAutoHide(maximized: boolean, menuOpen: boolean, wrapRef: RefObject<HTMLDivElement | null>) {
  const revealed = useShell((s) => s.dockRevealed);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hide = useCallback(() => useShell.getState().setDockRevealed(false), []);
  const later = (ms: number, fn: () => void) => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(fn, ms);
  };
  useEffect(() => {
    if (!revealed) return;
    const onPointer = (e: PointerEvent) => !wrapRef.current?.contains(e.target as Node) && hide();
    document.addEventListener('pointerdown', onPointer);
    return () => document.removeEventListener('pointerdown', onPointer);
  }, [revealed, hide, wrapRef]);
  useEffect(() => () => void (timer.current && clearTimeout(timer.current)), []);
  return {
    hidden: maximized && !revealed && !menuOpen,
    revealed,
    stripEnter: () => later(200, () => useShell.getState().setDockRevealed('pointer')),
    // 띠에서 벗어나면: 아직 안 드러났으면 취소, 드러났으면 Dock 에 들어오지 않는 한 0.8초 뒤 숨김.
    stripLeave: () => (useShell.getState().dockRevealed ? later(800, hide) : timer.current && clearTimeout(timer.current)),
    /** Dock 틀에 달 손: 들어오면 숨김 예약 취소, 위로 벗어나면 0.8초 뒤 숨김. */
    wrapHandlers: {
      onPointerEnter: () => timer.current && clearTimeout(timer.current),
      onPointerLeave: (e: ReactPointerEvent) => {
        const top = wrapRef.current?.getBoundingClientRect().top ?? 0;
        if (revealed && e.clientY < top) later(800, hide);
      },
    },
    hide,
  };
}

/** 포인터 가까운 타일을 키운다. 터치·메뉴 열림이면 멈추고, 동작 줄이기면 끈다. */
function useMagnify(count: number, tiles: RefObject<(HTMLSpanElement | null)[]>, frozen: boolean) {
  const [mag, setMag] = useState<{ scales: number[] | null; reduced: boolean }>(() => ({ scales: null, reduced: prefersReducedMotion() }));
  function onPointerMove(e: ReactPointerEvent) {
    if (e.pointerType === 'touch' || frozen) return;
    const reduced = prefersReducedMotion();
    const scales = tiles.current.slice(0, count).map((t) => {
      const r = t?.getBoundingClientRect();
      return r ? magnification(Math.abs(e.clientX - (r.left + r.width / 2))) : 1;
    });
    setMag({ scales: reduced ? null : scales, reduced });
  }
  return {
    scaleAt: (i: number) => (mag.reduced ? null : (mag.scales?.[i] ?? 1)),
    onPointerMove,
    onPointerLeave: () => setMag((m) => ({ ...m, scales: null })),
  };
}

interface RovingArgs {
  count: number;
  tabStop: number;
  current: number | null;
  setCurrent(i: number): void;
  buttons: RefObject<(HTMLButtonElement | null)[]>;
  openMenu(i: number): void;
  hide(): void;
}

/** 도구 막대 하나: ←→ 로 돌고 Home·End, Shift+F10·메뉴 키로 항목 메뉴, Esc 로 숨김. */
function rovingKeys({ count, tabStop, current, setCurrent, buttons, openMenu, hide }: RovingArgs) {
  const focusAt = (i: number) => {
    const at = ((i % count) + count) % count;
    setCurrent(at);
    buttons.current[at]?.focus();
  };
  return (e: KeyboardEvent) => {
    const at = current ?? tabStop;
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') focusAt(at + (e.key === 'ArrowRight' ? 1 : -1));
    else if (e.key === 'Home') focusAt(0);
    else if (e.key === 'End') focusAt(count - 1);
    else if ((e.key === 'F10' && e.shiftKey) || e.key === 'ContextMenu') openMenu(at);
    else if (e.key === 'Escape') hide();
    else return;
    e.preventDefault();
  };
}

const nameOf = (e: Item) => (e.kind === 'apps' ? '앱 목록' : e.program.name);

/** 항목 메뉴를 그 타일 위 가운데에 둔다(Dock 틀 기준 px). */
function menuLeft(tile: HTMLElement | null | undefined, wrap: HTMLElement | null) {
  const b = tile?.getBoundingClientRect();
  const w = wrap?.getBoundingClientRect();
  return b && w ? b.left - w.left + b.width / 2 : 0;
}

/** Dock 에 그릴 것: 항목 차례, 실행 중·활성, 승인 수, 롤링 정차 자리. */
function useDockModel(current: number | null) {
  const role = useSession((s) => s.session?.user.role ?? 'user');
  const wins = useWindows((s) => s.wins);
  const deactivated = useWindows((s) => s.deactivated);
  const pinned = useDock((s) => s.pinned);
  const pending = useApprovals((s) => s.pending);
  const running = new Set(wins.map((w) => w.programId));
  const active = activeWindow({ wins, deactivated });
  const entries = dockEntries(programs(role), pinned, running);
  const items = entries.filter((e): e is Item => e.kind !== 'sep');
  const activeIndex = items.findIndex((e) => e.kind === 'program' && e.program.id === active?.programId);
  const tabStop = current ?? (activeIndex >= 0 ? activeIndex : 0);
  const maximized = wins.some((w) => w.maximized && !w.minimized);
  return { running, active, entries, items, tabStop, maximized, pending };
}

type Model = ReturnType<typeof useDockModel>;

/** 항목 하나의 상태(이름 뒤 「, 활성 창」·「, 실행 중」·「, 승인 N」)와 배지. */
function itemState(entry: Item, model: Model) {
  const program = entry.kind === 'program' ? entry.program : null;
  const running = program !== null && model.running.has(program.id);
  const badge = program?.badge === 'approvals' ? model.pending : 0;
  const where = program && model.active?.programId === program.id ? ', 활성 창' : running ? ', 실행 중' : '';
  return { program, running, badge, state: `${where}${badge ? `, 승인 ${badge}` : ''}` };
}

interface ItemContext {
  model: Model;
  launching: string[];
  scaleAt(i: number): number | null;
  menuOpen: boolean;
  buttons: RefObject<(HTMLButtonElement | null)[]>;
  tiles: RefObject<(HTMLSpanElement | null)[]>;
  setMenu(i: number): void;
  setCurrent(i: number): void;
}

/** Dock 항목 하나의 속성. 누르면 프로그램을 열거나(앞으로·최소화 풀기) 앱 서랍을 연다. */
function dockItemProps(entry: Item, i: number, c: ItemContext): DockItemProps {
  const { program, running, badge, state } = itemState(entry, c.model);
  return {
    entry,
    index: i,
    name: nameOf(entry),
    state,
    badge,
    running,
    launching: program !== null && c.launching.includes(program.id),
    scale: c.scaleAt(i),
    tabStop: i === c.model.tabStop,
    menuOpen: c.menuOpen,
    buttonRef: (el) => void (c.buttons.current[i] = el),
    tileRef: (el) => {
      c.tiles.current[i] = el;
      if (program && el) setDockAnchor(program.id, el); // 창이 열리고·최소화될 때 이 아이콘 쪽으로 움직인다
    },
    onLaunch: () => (program ? useWindows.getState().open(program.id, undefined, 'dock') : useShell.getState().setDrawer('open')),
    onMenu: () => c.setMenu(i),
    onFocusItem: () => c.setCurrent(i),
  };
}

/**
 * 열린 항목 메뉴(항목 차례). 닫을 때 refocus 면 다시 그린 뒤 같은 자리 항목으로 포커스를 돌린다.
 * 「Dock에서 제거」 뒤에는 그 자리에 온 이웃 항목(끝이었으면 앞 항목)이다.
 */
function useItemMenu(buttons: RefObject<(HTMLButtonElement | null)[]>, count: number) {
  const [menu, setMenu] = useState<number | null>(null);
  const [refocus, setRefocus] = useState<number | null>(null);
  useEffect(() => {
    if (refocus === null) return;
    buttons.current[Math.min(refocus, count - 1)]?.focus();
    setRefocus(null);
  }, [refocus, count, buttons]);
  const closeMenu = useCallback(
    (again: boolean) => {
      if (again && menu !== null) setRefocus(menu);
      setMenu(null);
    },
    [menu],
  );
  return [menu, setMenu, closeMenu] as const;
}

export default function Dock() {
  const wrapRef = useRef<HTMLDivElement>(null);
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const tiles = useRef<(HTMLSpanElement | null)[]>([]);
  const [current, setCurrent] = useState<number | null>(null);
  const model = useDockModel(current);
  const [menu, setMenu, closeMenu] = useItemMenu(buttons, model.items.length);
  const { entries, items, tabStop } = model;
  const launching = useLaunching(model.running, model.pending);
  const auto = useAutoHide(model.maximized, menu !== null, wrapRef);
  const mag = useMagnify(items.length, tiles, menu !== null);
  const onKeyDown = rovingKeys({ count: items.length, tabStop, current, setCurrent, buttons, openMenu: setMenu, hide: auto.hide });

  useEffect(() => {
    if (auto.revealed === 'keyboard') buttons.current[tabStop]?.focus();
  }, [auto.revealed]); // 드러날 때 한 번만

  const ctx: ItemContext = { model, launching, scaleAt: mag.scaleAt, menuOpen: menu !== null, buttons, tiles, setMenu, setCurrent };
  let index = -1;
  const renderEntry = (entry: DockEntry) => {
    if (entry.kind === 'sep') return <div key={entry.key} role="separator" aria-orientation="vertical" className="os-dock-sep" />;
    index += 1;
    return <DockItem key={entry.kind === 'apps' ? 'apps' : entry.program.id} {...dockItemProps(entry, index, ctx)} />;
  };

  return (
    <>
      {model.maximized && <div className="os-dock-reveal" data-testid="dock-reveal" onPointerEnter={auto.stripEnter} onPointerLeave={auto.stripLeave} />}
      <div ref={wrapRef} className="os-dock-wrap" data-hidden={auto.hidden} inert={auto.hidden} {...auto.wrapHandlers}>
        <div
          role="toolbar"
          aria-label="프로그램 막대"
          className="os-dock"
          onKeyDown={onKeyDown}
          onPointerMove={mag.onPointerMove}
          onPointerLeave={mag.onPointerLeave}
          onBlur={(e) => {
            if (!e.currentTarget.contains(e.relatedTarget as Node)) setCurrent(null);
            if (auto.revealed && !wrapRef.current?.contains(e.relatedTarget as Node)) auto.hide();
          }}
        >
          {entries.map(renderEntry)}
        </div>
        {menu !== null && items[menu] && (
          <DockMenu entry={items[menu]} name={nameOf(items[menu])} left={menuLeft(tiles.current[menu], wrapRef.current)} onClose={closeMenu} />
        )}
      </div>
    </>
  );
}
