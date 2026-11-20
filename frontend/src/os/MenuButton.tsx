import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';

interface MenuButtonProps {
  label: ReactNode;
  ariaLabel?: string;
  className?: string;
  /** 펼칠 때 부른다(목록 새로 읽기 등). */
  onOpen?: () => void;
  /** 펼친 메뉴 내용. close 를 불러 닫는다. */
  children: (close: () => void) => ReactNode;
}

/** 메뉴바의 펼침 메뉴. 바깥을 누르거나 Escape 면 닫힌다. */
export default function MenuButton({ label, ariaLabel, className, onOpen, children }: MenuButtonProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);

  useEffect(() => {
    if (!open) return;
    const onPointer = (e: PointerEvent) => {
      if (!ref.current?.contains(e.target as Node)) close();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close();
    };
    document.addEventListener('pointerdown', onPointer);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', onPointer);
      document.removeEventListener('keydown', onKey);
    };
  }, [open, close]);

  function toggle() {
    if (!open) onOpen?.();
    setOpen(!open);
  }

  return (
    <div ref={ref} className="os-mb-menu">
      <button
        type="button"
        className={['os-mb-btn', className].filter(Boolean).join(' ')}
        aria-label={ariaLabel}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={toggle}
      >
        {label}
      </button>
      {open && (
        <div role="menu" className="os-menu">
          {children(close)}
        </div>
      )}
    </div>
  );
}
