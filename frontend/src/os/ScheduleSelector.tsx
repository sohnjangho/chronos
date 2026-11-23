import { useCallback, useEffect, useRef, useState, type RefObject } from 'react';
import { api } from '../shared/api';
import { useCurrentSchedule } from './currentSchedule';
import PickList from './PickList';
import { useSession } from './session';
import { useWindows } from './windowStore';

export interface ScheduleItem {
  id: number;
  name: string;
  level?: string;
}

export const scheduleText = (s: ScheduleItem) => (s.level ? `${s.name} · ${s.level}` : s.name);

/** 일정 목록(펼치거나 reloadToken 이 바뀔 때마다 다시 읽음). 지금 일정이 사라졌으면 비운다. */
function useScheduleList(reloadToken: number) {
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
  useEffect(load, [load, reloadToken]);
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
  /** 새 프로젝트 단추를 보일까(현장 관리자는 일정을 만들 수 없다, F4). */
  canCreate: boolean;
  onPick(s: ScheduleItem): void;
  onCreateDirect(): void;
  onCreateAi(): void;
  onClose(): void;
}

/** 찾기 칸이 있는 일정 목록 + 새 프로젝트 생성 단추. */
function SitePopup({ items, failed, currentId, canCreate, onPick, onCreateDirect, onCreateAi, onClose }: SitePopupProps) {
  const [query, setQuery] = useState('');
  const shown = items.filter((s) => scheduleText(s).toLowerCase().includes(query.trim().toLowerCase()));
  return (
    <div className="os-site-pop">
      {canCreate && (
        <div className="os-site-actions">
          <button type="button" className="os-site-act-btn" onClick={onCreateDirect}>
            + 새 프로젝트 직접 만들기
          </button>
          <button type="button" className="os-site-act-btn" onClick={onCreateAi}>
            ✦ AI로 새 프로젝트 일정 생성
          </button>
        </div>
      )}
      <PickList
        label="일정 찾기"
        placeholder="일정 찾기"
        query={query}
        onQuery={setQuery}
        onClose={onClose}
        empty={failed ? '일정 목록을 불러오지 못했습니다.' : '찾은 일정이 없습니다.'}
        groups={[{ items: shown.map((s) => ({ key: String(s.id), label: scheduleText(s), selected: s.id === currentId, run: () => onPick(s) })) }]}
      />
    </div>
  );
}

export default function ScheduleSelector() {
  const current = useCurrentSchedule((s) => s.current);
  const creatingNewProject = useCurrentSchedule((s) => s.creatingNewProject);
  const reloadToken = useCurrentSchedule((s) => s.reloadToken);
  const canCreate = useSession((s) => s.session?.user.role !== 'field');
  const { items, failed, load } = useScheduleList(reloadToken);
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const dismiss = useCallback(() => setOpen(false), []);
  useOutsideClose(rootRef, open, dismiss);

  if (items?.length === 0 && !current) {
    return (
      <div className="os-site">
        <span className="os-site-none">{creatingNewProject ? '새 프로젝트 생성 중' : '일정 없음'}</span>
        {canCreate && (
          <button
            type="button"
            className="os-site-new-mini"
            onClick={() => useCurrentSchedule.getState().openNewProjectModal('direct')}
          >
            + 새 프로젝트
          </button>
        )}
      </div>
    );
  }

  const known = current ? items?.find((s) => s.id === current.id) : undefined;
  const label = current
    ? known
      ? scheduleText(known)
      : current.name
    : creatingNewProject
      ? '새 프로젝트 생성 중'
      : '일정 고르기';
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
          canCreate={canCreate}
          onClose={close}
          onCreateDirect={() => {
            setOpen(false);
            useCurrentSchedule.getState().openNewProjectModal('direct');
          }}
          onCreateAi={() => {
            setOpen(false);
            useCurrentSchedule.getState().enterNewProjectMode();
            void import('../programs/chat/chatStore').then(({ useChat }) => useChat.getState().newChat(null));
            useWindows.getState().stageLayout('chat');
          }}
          onPick={(s) => {
            useCurrentSchedule.getState().setCurrent({ id: s.id, name: s.name });
            close();
          }}
        />
      )}
    </div>
  );
}
