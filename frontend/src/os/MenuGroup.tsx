import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode, type RefObject } from 'react';

/** 누를 수 있는 메뉴 항목. checked 를 주면 체크 항목(✓)이 된다. detail 은 둘째 줄 보조 글. */
export interface MenuAction {
  type?: 'item';
  label: string;
  run: () => void;
  /** 보이는 단축키(예 "Ctrl+Alt+S"). 처리는 따로 한다. */
  shortcut?: string;
  disabled?: boolean;
  checked?: boolean;
  /** 지금 고른 것(굵게). */
  current?: boolean;
  detail?: string;
}

export type MenuEntry = MenuAction | { type: 'separator' } | { type: 'title'; label: string };

export const SEPARATOR: MenuEntry = { type: 'separator' };

export interface MenuSpec {
  key: string;
  label: ReactNode;
  ariaLabel?: string;
  className?: string;
  items: MenuEntry[];
  /** 항목 위에 보이는 안내. */
  note?: string;
  /** 펼칠 때 부른다(목록 새로 읽기 등). */
  onOpen?: () => void;
  /** 펼침을 단추 오른쪽 끝에 맞춘다(사용자 메뉴). */
  alignRight?: boolean;
}

interface OpenState {
  index: number;
  focusFirst: boolean;
}

const ITEM_SELECTOR = '[role="menuitem"]:not(:disabled), [role="menuitemcheckbox"]:not(:disabled)';

/** 펼친 메뉴의 켜진 항목 가운데 지금 것에서 d 만큼(끝에서 돌아감). 묶음 제목·구분선·꺼진 항목은 건너뛴다. */
export function stepFocus(menu: HTMLElement | null, d: 1 | -1) {
  const list = menu ? [...menu.querySelectorAll<HTMLButtonElement>(ITEM_SELECTOR)] : [];
  if (list.length === 0) return;
  const at = list.indexOf(document.activeElement as HTMLButtonElement);
  const next = at < 0 ? (d > 0 ? 0 : list.length - 1) : (at + d + list.length) % list.length;
  list[next].focus();
}

/** 어느 메뉴가 열렸는지. 키보드로 열면 첫 항목에 포커스, 바깥을 누르면 닫힌다. */
function useOpenMenu(rootRef: RefObject<HTMLDivElement | null>, menuRef: RefObject<HTMLDivElement | null>) {
  const [open, setOpen] = useState<OpenState | null>(null);
  useEffect(() => {
    if (!open) return;
    if (open.focusFirst) stepFocus(menuRef.current, 1);
    const onPointer = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(null);
    };
    document.addEventListener('pointerdown', onPointer);
    return () => document.removeEventListener('pointerdown', onPointer);
  }, [open, rootRef, menuRef]);
  return [open, setOpen] as const;
}

interface KeyContext {
  count: number;
  open: OpenState | null;
  setOpen(o: OpenState | null): void;
  show(index: number, focusFirst: boolean): void;
  closeToButton(): void;
  menuRef: RefObject<HTMLDivElement | null>;
}

/** 메뉴 단추와 펼친 메뉴의 키보드 처리. */
function keyHandlers({ count, open, setOpen, show, closeToButton, menuRef }: KeyContext) {
  function onButtonKeyDown(e: KeyboardEvent, index: number) {
    if (e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowDown') show(index, true);
    else if (e.key === 'Escape' && open) setOpen(null);
    else return;
    e.preventDefault();
  }

  function onMenuKeyDown(e: KeyboardEvent) {
    if (!open) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') stepFocus(menuRef.current, e.key === 'ArrowDown' ? 1 : -1);
    else if (e.key === 'ArrowRight' || e.key === 'ArrowLeft')
      show((open.index + (e.key === 'ArrowRight' ? 1 : count - 1)) % count, true);
    else if (e.key === 'Escape') closeToButton();
    else {
      if (e.key === 'Tab') setOpen(null);
      return;
    }
    e.preventDefault();
    e.stopPropagation();
  }

  return { onButtonKeyDown, onMenuKeyDown };
}

/**
 * 메뉴바의 펼침 메뉴 묶음(macOS 메뉴바 방식). Enter·Space·↓ 로 열면 첫 항목에 포커스, ↑↓ 로 항목,
 * ←→ 로 옆 메뉴, Escape 는 닫고 메뉴 단추로 돌아간다. 하나가 열린 동안 다른 메뉴 이름을 가리키면
 * 그 메뉴로 바뀐다. 바깥을 누르면 닫힌다. 꺼진 항목은 누를 수 없다.
 */
export default function MenuGroup({ menus, className }: { menus: MenuSpec[]; className?: string }) {
  const rootRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const [open, setOpen] = useOpenMenu(rootRef, menuRef);

  const show = (index: number, focusFirst: boolean) => {
    menus[index].onOpen?.();
    setOpen({ index, focusFirst });
  };
  const closeToButton = () => {
    if (open) buttons.current[open.index]?.focus();
    setOpen(null);
  };
  const { onButtonKeyDown, onMenuKeyDown } = keyHandlers({ count: menus.length, open, setOpen, show, closeToButton, menuRef });

  return (
    <div
      ref={rootRef}
      className={['os-mb-group', className].filter(Boolean).join(' ')}
      onBlur={(e) => open && !rootRef.current?.contains(e.relatedTarget as Node) && setOpen(null)}
    >
      {menus.map((m, index) => (
        <div key={m.key} className="os-mb-menu">
          <button
            ref={(el) => {
              buttons.current[index] = el;
            }}
            type="button"
            className={['os-mb-btn', m.className].filter(Boolean).join(' ')}
            aria-label={m.ariaLabel}
            aria-haspopup="menu"
            aria-expanded={open?.index === index}
            onClick={() => (open?.index === index ? setOpen(null) : show(index, false))}
            onPointerEnter={() => open && open.index !== index && show(index, false)}
            onKeyDown={(e) => onButtonKeyDown(e, index)}
          >
            {m.label}
          </button>
          {open?.index === index && <MenuList menu={m} menuRef={menuRef} onKeyDown={onMenuKeyDown} onPick={closeToButton} />}
        </div>
      ))}
    </div>
  );
}

interface MenuListProps {
  menu: Pick<MenuSpec, 'label' | 'ariaLabel' | 'items' | 'note' | 'alignRight'>;
  menuRef: RefObject<HTMLDivElement | null>;
  onKeyDown(e: KeyboardEvent): void;
  onPick(): void;
  className?: string;
}

/** 펼친 메뉴 내용. Dock 항목 메뉴도 이것을 쓴다. */
export function MenuList({ menu, menuRef, onKeyDown, onPick, className }: MenuListProps) {
  const name = menu.ariaLabel ?? (typeof menu.label === 'string' ? menu.label : undefined);
  const classes = ['os-menu', menu.alignRight && 'is-right', className].filter(Boolean).join(' ');
  return (
    <div ref={menuRef} role="menu" aria-label={name} className={classes} onKeyDown={onKeyDown}>
      {menu.note && <div className="os-menu-note">{menu.note}</div>}
      {menu.items.map((entry, i) => (
        <MenuRow key={entry.type === 'separator' ? `sep-${i}` : `${entry.label}-${i}`} entry={entry} onPick={onPick} />
      ))}
    </div>
  );
}

function MenuRow({ entry, onPick }: { entry: MenuEntry; onPick(): void }) {
  if (entry.type === 'separator') return <div role="separator" className="os-menu-sep" />;
  if (entry.type === 'title') return <div className="os-menu-title">{entry.label}</div>;
  const check = entry.checked !== undefined;
  return (
    <button
      type="button"
      role={check ? 'menuitemcheckbox' : 'menuitem'}
      aria-checked={check ? entry.checked : undefined}
      tabIndex={-1}
      disabled={entry.disabled}
      aria-keyshortcuts={entry.shortcut?.replace(/Ctrl/g, 'Control')}
      className={`os-menu-item${entry.current ? ' is-current' : ''}`}
      onClick={() => {
        onPick();
        entry.run();
      }}
    >
      {check && (
        <span className="os-menu-check" aria-hidden="true">
          {entry.checked ? '✓' : ''}
        </span>
      )}
      <span className="os-menu-label">
        {entry.label}
        {entry.detail && <span className="os-menu-detail">{entry.detail}</span>}
      </span>
      {entry.shortcut && (
        <span className="os-menu-shortcut" aria-hidden="true">
          {entry.shortcut}
        </span>
      )}
    </button>
  );
}
