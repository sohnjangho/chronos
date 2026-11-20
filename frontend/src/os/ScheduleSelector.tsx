import { useCallback, useEffect, useRef, useState, type RefObject } from 'react';
import { api } from '../shared/api';
import { useCurrentSchedule } from './currentSchedule';
import PickList from './PickList';

export interface ScheduleItem {
  id: number;
  name: string;
  level?: string;
}

export const scheduleText = (s: ScheduleItem) => (s.level ? `${s.name} · ${s.level}` : s.name);

/**
 * 메뉴바 현장 선택(높이 32, 최소 폭 220, ▾). 누르면 아래에 찾기 칸이 있는 목록이 열린다.
 * 일정이 하나도 없으면 단추 대신 보조색 글 「일정 없음」.
 */
/** 일정 목록(펼칠 때마다 다시 읽음). 지금 일정이 목록에서 사라졌으면 비운다. */
function useScheduleList() {
  const [items, setItems] = useState<ScheduleItem[] | null>(null);
  const [failed, setFailed] = useState(false);
  const load = useCallback(() => {
    api<ScheduleItem[]>('/api/schedules')
      .then((list) => {
        setItems(list);
        setFailed(false);
        const cur = useCurrentSchedule.getState().current;
        if (cur && !list.some((s) => s.id === cur.id)) useCurrentSchedule.getState().setCurrent(null);
      })
      .catch(() => setFailed(true));
  }, []);
  useEffect(load, [load]);
  return { items, failed, load };
}

/** 열린 동안 바깥을 누르면 닫는다. */
function useOutsideClose(rootRef: RefObject<HTMLDivElement | null>, open: boolean, close: () => void) {
  useEffect(() => {
    if (!open) return;
    const onPointer = (e: PointerEvent) => !rootRef.current?.contains(e.target as Node) && close();
    document.addEventListener('pointerdown', onPointer);
    return () => document.removeEventListener('pointerdown', onPointer);
  }, [open, rootRef, close]);
}

interface SitePopupProps {
  items: ScheduleItem[];
  failed: boolean;
  currentId: number | undefined;
  onPick(s: ScheduleItem): void;
  onClose(): void;
}

/** 찾기 칸이 있는 일정 목록(폭 320, 줄 32, 최대 높이 280). */
function SitePopup({ items, failed, currentId, onPick, onClose }: SitePopupProps) {
  const [query, setQuery] = useState('');
  const shown = items.filter((s) => scheduleText(s).toLowerCase().includes(query.trim().toLowerCase()));
  return (
    <PickList
      className="os-site-pop"
      label="일정 찾기"
      placeholder="일정 찾기"
      query={query}
      onQuery={setQuery}
      onClose={onClose}
      empty={failed ? '일정 목록을 불러오지 못했습니다.' : '찾은 일정이 없습니다.'}
      groups={[{ items: shown.map((s) => ({ key: String(s.id), label: scheduleText(s), selected: s.id === currentId, run: () => onPick(s) })) }]}
    />
  );
}

export default function ScheduleSelector() {
  const current = useCurrentSchedule((s) => s.current);
  const { items, failed, load } = useScheduleList();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const dismiss = useCallback(() => setOpen(false), []);
  useOutsideClose(rootRef, open, dismiss);

  if (items?.length === 0 && !current) return <span className="os-site-none">일정 없음</span>;

  const known = current ? items?.find((s) => s.id === current.id) : undefined;
  const label = current ? (known ? scheduleText(known) : current.name) : '일정 고르기';
  const close = () => {
    setOpen(false);
    buttonRef.current?.focus();
  };

  return (
    <div ref={rootRef} className="os-site" onBlur={(e) => open && !rootRef.current?.contains(e.relatedTarget as Node) && setOpen(false)}>
      <button
        ref={buttonRef}
        type="button"
        className="os-site-btn"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => {
          if (!open) load();
          setOpen(!open);
        }}
      >
        <span className="os-site-label">{label}</span>
        <span className="os-site-caret" aria-hidden="true">
          ▾
        </span>
      </button>
      {open && (
        <SitePopup
          items={items ?? []}
          failed={failed}
          currentId={current?.id}
          onClose={close}
          onPick={(s) => {
            useCurrentSchedule.getState().setCurrent({ id: s.id, name: s.name });
            close();
          }}
        />
      )}
    </div>
  );
}
