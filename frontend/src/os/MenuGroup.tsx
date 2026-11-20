import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode, type RefObject } from 'react';

export interface MenuEntry {
  label: string;
  run: () => void;
  shortcut?: string;
  disabled?: boolean;
  /** 지금 고른 것(굵게). */
  current?: boolean;
}

export interface MenuSpec {
  key: string;
  label: ReactNode;
  ariaLabel?: string;
  className?: string;
  items: MenuEntry[];
  /** 항목 위에 보이는 안내(예 "일정 없음"). */
  note?: string;
  /** 펼칠 때 부른다(목록 새로 읽기 등). */
  onOpen?: () => void;
  /** 이 메뉴 단추 바로 뒤에 놓을 것(예 맨 앞 프로그램 이름). */
  after?: ReactNode;
}

interface OpenState {
  index: number;
  focusFirst: boolean;
}

/** 펼친 메뉴의 켜진 항목 가운데 지금 것에서 d 만큼(끝에서 돌아감). 포커스가 항목 밖이면 처음·끝. */
function stepFocus(menu: HTMLElement | null, d: 1 | -1) {
  const list = menu ? [...menu.querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not(:disabled)')] : [];
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
 * 메뉴바의 펼침 메뉴 묶음. Enter·Space·↓ 로 열면 첫 항목에 포커스, ↑↓ 로 항목, ←→ 로 옆 메뉴,
 * Escape 는 닫고 메뉴 단추로 돌아간다. 바깥을 누르면 닫힌다. 꺼진 항목은 누를 수 없다.
 */
export default function MenuGroup({ menus }: { menus: MenuSpec[] }) {
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
    <div ref={rootRef} className="os-mb-group">
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
            onKeyDown={(e) => onButtonKeyDown(e, index)}
          >
            {m.label}
          </button>
          {m.after}
          {open?.index === index && <MenuList menu={m} menuRef={menuRef} onKeyDown={onMenuKeyDown} onPick={closeToButton} />}
        </div>
      ))}
    </div>
  );
}

interface MenuListProps {
  menu: MenuSpec;
  menuRef: RefObject<HTMLDivElement | null>;
  onKeyDown(e: KeyboardEvent): void;
  onPick(): void;
}

function MenuList({ menu, menuRef, onKeyDown, onPick }: MenuListProps) {
  const name = menu.ariaLabel ?? (typeof menu.label === 'string' ? menu.label : undefined);
  return (
    <div ref={menuRef} role="menu" aria-label={name} className="os-menu" onKeyDown={onKeyDown}>
      {menu.note && <div className="os-menu-note">{menu.note}</div>}
      {menu.items.map((item) => (
        <button
          key={item.label}
          type="button"
          role="menuitem"
          tabIndex={-1}
          disabled={item.disabled}
          aria-keyshortcuts={item.shortcut}
          className={`os-menu-item${item.current ? ' is-current' : ''}`}
          onClick={() => {
            onPick();
            item.run();
          }}
        >
          <span>{item.label}</span>
          {item.shortcut && (
            <span className="os-menu-shortcut" aria-hidden="true">
              {item.shortcut}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}
