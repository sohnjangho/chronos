import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import './overlays.css';

export interface PickItem {
  key: string;
  label: string;
  detail?: string;
  icon?: ReactNode;
  /** 지금 고른 것(선택 바탕). */
  selected?: boolean;
  run(): void;
}

export interface PickGroup {
  title?: string;
  items: PickItem[];
}

interface PickListProps {
  /** 찾기 칸 이름. */
  label: string;
  placeholder?: string;
  query: string;
  onQuery(q: string): void;
  groups: PickGroup[];
  onClose(): void;
  empty?: ReactNode;
  className?: string;
}

/**
 * 찾기 칸 + 묶음 목록. 글자를 치면 부르는 쪽이 거른다. ↑↓ 로 고르고 Enter 로 실행, Esc 로 닫는다.
 * 묶음 제목에는 개수가 붙는다. 현장 선택과 전역 검색이 함께 쓴다.
 */
export default function PickList({ label, placeholder, query, onQuery, groups, onClose, empty, className }: PickListProps) {
  const id = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const flat = groups.flatMap((g) => g.items);
  const [active, setActive] = useState(0);
  const at = Math.min(active, Math.max(0, flat.length - 1));

  useEffect(() => inputRef.current?.focus(), []);
  useEffect(() => setActive(0), [query]);
  useEffect(() => {
    document.getElementById(`${id}-${at}`)?.scrollIntoView?.({ block: 'nearest' });
  }, [id, at]);

  function onKeyDown(e: KeyboardEvent) {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      if (flat.length) setActive((at + (e.key === 'ArrowDown' ? 1 : flat.length - 1)) % flat.length);
    } else if (e.key === 'Enter') flat[at]?.run();
    else if (e.key === 'Escape') onClose();
    else return;
    e.preventDefault();
    e.stopPropagation();
  }

  return (
    <div className={['os-pick', className].filter(Boolean).join(' ')}>
      <input
        ref={inputRef}
        className="os-pick-input"
        role="combobox"
        aria-label={label}
        aria-expanded="true"
        aria-controls={`${id}-list`}
        aria-activedescendant={flat.length ? `${id}-${at}` : undefined}
        placeholder={placeholder}
        value={query}
        onChange={(e) => onQuery(e.target.value)}
        onKeyDown={onKeyDown}
      />
      <div id={`${id}-list`} role="listbox" aria-label={label} className="os-pick-list">
        {flat.length === 0 && <div className="os-pick-empty">{empty ?? '찾은 것이 없습니다.'}</div>}
        <PickOptions id={id} groups={groups} at={at} onHover={(i) => i !== at && setActive(i)} />
      </div>
    </div>
  );
}

/** 묶음 제목(개수)과 선택지. 선택지 id 는 `${id}-${차례}` (aria-activedescendant 용). */
function PickOptions({ id, groups, at, onHover }: { id: string; groups: PickGroup[]; at: number; onHover(i: number): void }) {
  let index = -1;
  return groups
    .filter((g) => g.items.length)
    .map((g, gi) => (
      <div key={g.title ?? gi} role="group" aria-label={g.title} className="os-pick-group">
        {g.title && (
          <div className="os-pick-title" aria-hidden="true">
            {g.title} <span className="os-pick-count">{g.items.length}</span>
          </div>
        )}
        {g.items.map((item) => {
          index += 1;
          const i = index;
          return (
            <div
              key={item.key}
              id={`${id}-${i}`}
              role="option"
              aria-selected={i === at}
              className={`os-pick-option${item.selected ? ' is-selected' : ''}`}
              onPointerMove={() => onHover(i)}
              // 누르는 순간 찾기 칸이 포커스를 잃지 않게(현장 선택은 blur 로 닫혀 click 이 오기 전에 목록이 사라진다).
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => item.run()}
            >
              {item.icon}
              <span className="os-pick-label">{item.label}</span>
              {item.detail && <span className="os-pick-detail">{item.detail}</span>}
            </div>
          );
        })}
      </div>
    ));
}
