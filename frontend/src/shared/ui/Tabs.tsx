import { useRef, type KeyboardEvent, type ReactNode } from 'react';
import './ui.css';

export interface TabItem {
  id: string;
  /** 글이나 글 + 개수 배지 등. */
  label: ReactNode;
}

export interface TabsProps {
  items: TabItem[];
  value: string;
  onChange(id: string): void;
  /** tablist 의 이름(화면 읽기 프로그램용). */
  label?: string;
}

/** 탭 줄. 좌우 화살표로 옮겨 간다. 탭 내용은 부르는 쪽이 그린다. */
export default function Tabs({ items, value, onChange, label }: TabsProps) {
  const listRef = useRef<HTMLDivElement>(null);

  function onKeyDown(e: KeyboardEvent) {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
    e.preventDefault();
    const i = items.findIndex((t) => t.id === value);
    const next = (i + (e.key === 'ArrowRight' ? 1 : -1) + items.length) % items.length;
    onChange(items[next].id);
    listRef.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[next]?.focus();
  }

  return (
    <div ref={listRef} role="tablist" aria-label={label} className="ui-tabs" onKeyDown={onKeyDown}>
      {items.map((t) => (
        <button
          key={t.id}
          type="button"
          role="tab"
          className="ui-tab"
          aria-selected={t.id === value}
          tabIndex={t.id === value ? 0 : -1}
          onClick={() => onChange(t.id)}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
