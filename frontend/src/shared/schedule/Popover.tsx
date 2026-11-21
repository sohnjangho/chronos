import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import Button from '../ui/Button';

interface PopoverProps {
  /** 단추 글(필터 2 처럼 바뀔 수 있다). */
  button: string;
  /** 펼친 판의 이름. */
  label: string;
  /** 판을 위로 펼친다(창 아래쪽 단추). */
  up?: boolean;
  align?: 'left' | 'right';
  role?: 'dialog' | 'none';
  children: (close: () => void) => ReactNode;
}

/** 단추 + 펼침 판(portal + fixed 배치로 스크롤·리본 컨테이너에 잘리지 않는다). */
export default function Popover({ button, label, up, align = 'left', role = 'dialog', children }: PopoverProps) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<CSSProperties | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const popRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    if (!open || !rootRef.current) return;
    const place = () => {
      const r = rootRef.current?.getBoundingClientRect();
      if (!r) return;
      const vw = window.innerWidth || 1440;
      const vh = window.innerHeight || 900;
      const popW = popRef.current?.offsetWidth || 260;
      const popH = popRef.current?.offsetHeight || 220;
      const rawLeft = align === 'right' ? r.right - popW : r.left;
      const left = Math.max(8, Math.min(rawLeft, vw - popW - 8));
      const preferUp = up || (r.bottom + 4 + popH > vh - 8 && r.top - 4 - popH > 8);
      const top = preferUp ? Math.max(8, r.top - 4 - popH) : Math.min(vh - popH - 8, r.bottom + 4);
      setPos({ position: 'fixed', top, left, right: 'auto', bottom: 'auto' });
    };
    place();
    window.addEventListener('resize', place);
    window.addEventListener('scroll', place, true);
    return () => {
      window.removeEventListener('resize', place);
      window.removeEventListener('scroll', place, true);
    };
  }, [open, up, align]);

  useEffect(() => {
    if (!open) return;
    const onPointer = (e: PointerEvent) => {
      const t = e.target as Node;
      if (!rootRef.current?.contains(t) && !popRef.current?.contains(t)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      e.stopPropagation();
      setOpen(false);
      rootRef.current?.querySelector('button')?.focus();
    };
    document.addEventListener('pointerdown', onPointer);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', onPointer);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const close = () => {
    setOpen(false);
    rootRef.current?.querySelector('button')?.focus();
  };

  const panel = open && (
    <div
      ref={popRef}
      role={role === 'dialog' ? 'dialog' : undefined}
      aria-label={role === 'dialog' ? label : undefined}
      className={`sch-pop${up ? ' is-up' : ''}${align === 'right' ? ' is-right' : ''}`}
      style={pos ?? { position: 'fixed', top: -9999, left: -9999 }}
      onKeyDown={(e) => {
        if (e.key !== 'Escape') return;
        e.stopPropagation();
        close();
      }}
    >
      {children(close)}
    </div>
  );

  return (
    <div className="sch-pop-root" ref={rootRef}>
      <Button aria-expanded={open} aria-haspopup="dialog" onClick={() => setOpen((o) => !o)}>
        {button}
      </Button>
      {panel && createPortal(panel, document.body)}
    </div>
  );
}
