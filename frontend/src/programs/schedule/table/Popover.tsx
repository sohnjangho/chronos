import { useEffect, useRef, useState, type ReactNode } from 'react';
import Button from '../../../shared/ui/Button';

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

/** 단추 + 펼침 판. 바깥을 누르거나 Esc 면 닫힌다(Esc 는 단추로 초점을 돌린다). */
export default function Popover({ button, label, up, align = 'left', role = 'dialog', children }: PopoverProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onPointer = (e: PointerEvent) => !rootRef.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener('pointerdown', onPointer);
    return () => document.removeEventListener('pointerdown', onPointer);
  }, [open]);
  const close = () => {
    setOpen(false);
    rootRef.current?.querySelector('button')?.focus();
  };
  return (
    <div className="sch-pop-root" ref={rootRef}>
      <Button aria-expanded={open} aria-haspopup="dialog" onClick={() => setOpen((o) => !o)}>
        {button}
      </Button>
      {open && (
        <div
          role={role === 'dialog' ? 'dialog' : undefined}
          aria-label={role === 'dialog' ? label : undefined}
          className={`sch-pop${up ? ' is-up' : ''}${align === 'right' ? ' is-right' : ''}`}
          onKeyDown={(e) => {
            if (e.key !== 'Escape') return;
            e.stopPropagation();
            close();
          }}
        >
          {children(close)}
        </div>
      )}
    </div>
  );
}
