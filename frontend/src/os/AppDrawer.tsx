import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { useModalFocus } from './modalFocus';
import Button from '../shared/ui/Button';
import { useDock } from './dockStore';
import ProgramIcon from './ProgramIcon';
import { programs, type ProgramManifest } from './registry';
import { useSession } from './session';
import { useShell } from './shell';
import { useWindows } from './windowStore';
import './overlays.css';

/** Dock 차례 한 줄의 ← · → · × 단추. */
function OrderButtons({
  name,
  first,
  last,
  onMove,
  onUnpin,
}: {
  name: string;
  first: boolean;
  last: boolean;
  onMove(delta: -1 | 1): void;
  onUnpin(): void;
}) {
  return (
    <div className="os-drawer-order-btns">
      <button
        type="button"
        className="os-drawer-order-btn"
        aria-label={`${name} 왼쪽으로 이동`}
        disabled={first}
        onClick={() => onMove(-1)}
      >
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M7.5 2.5L4 6l3.5 3.5" />
        </svg>
      </button>
      <button
        type="button"
        className="os-drawer-order-btn"
        aria-label={`${name} 오른쪽으로 이동`}
        disabled={last}
        onClick={() => onMove(1)}
      >
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M4.5 2.5L8 6l-3.5 3.5" />
        </svg>
      </button>
      <button
        type="button"
        className="os-drawer-order-btn"
        aria-label={`${name} Dock에서 빼기`}
        onClick={onUnpin}
      >
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true">
          <path d="M3 3l6 6M9 3L3 9" />
        </svg>
      </button>
    </div>
  );
}

/** 편집 모드의 Dock 차례: 끌어서 옮기거나, 단추(←·→·×) 또는 Alt+←→ 로 조정한다. */
function DockOrder({ all }: { all: ProgramManifest[] }) {
  const pinned = useDock((s) => s.pinned);
  const allIds = all.map((p) => p.id);
  const byId = new Map(all.map((p) => [p.id, p]));
  const order = (pinned ?? allIds).filter((id) => byId.has(id));
  const [dragId, setDragId] = useState<string | null>(null);
  const [overId, setOverId] = useState<string | null>(null);
  const [focusId, setFocusId] = useState<string | null>(null);
  const refs = useRef(new Map<string, HTMLLIElement | null>());
  const move = (id: string, to: number) => useDock.getState().move(id, to, allIds);

  useEffect(() => {
    if (focusId) refs.current.get(focusId)?.focus();
  }, [focusId, order.join(',')]); // 옮긴 줄에 포커스를 남긴다

  function onKeyDown(e: KeyboardEvent, id: string, i: number) {
    if (!e.altKey || (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight')) return;
    e.preventDefault();
    move(id, i + (e.key === 'ArrowRight' ? 1 : -1));
    setFocusId(id);
  }

  return (
    <div className="os-drawer-dock">
      <div className="os-drawer-dock-head">
        <div className="os-drawer-dock-title">Dock 차례 · 끌어서 옮기거나 버튼 / Alt+←→</div>
        <Button disabled={pinned === null} onClick={() => useDock.getState().resetDefault()}>
          기본 순서 복원
        </Button>
      </div>
      <ol aria-label="Dock 차례" className="os-drawer-order">
        {order.map((id, i) => {
          const p = byId.get(id)!;
          const liClass = [dragId === id ? 'is-dragging' : '', overId === id && dragId !== null && dragId !== id ? 'is-drop-target' : '']
            .filter(Boolean)
            .join(' ');
          return (
            <li
              key={id}
              ref={(el) => void refs.current.set(id, el)}
              tabIndex={0}
              draggable
              className={liClass || undefined}
              onDragStart={(e) => {
                setDragId(id);
                e.dataTransfer?.setData('text/plain', id);
              }}
              onDragOver={(e) => {
                e.preventDefault();
                if (overId !== id) setOverId(id);
              }}
              onDragLeave={() => {
                if (overId === id) setOverId(null);
              }}
              onDrop={(e) => {
                e.preventDefault();
                const from = dragId || e.dataTransfer?.getData('text/plain') || null;
                if (from && from !== id) move(from, i);
                setDragId(null);
                setOverId(null);
              }}
              onDragEnd={() => {
                setDragId(null);
                setOverId(null);
              }}
              onKeyDown={(e) => onKeyDown(e, id, i)}
            >
              <ProgramIcon program={p} size={32} />
              <span>{p.name}</span>
              <OrderButtons
                name={p.name}
                first={i === 0}
                last={i === order.length - 1}
                onMove={(d) => move(id, i + d)}
                onUnpin={() => useDock.getState().unpin(id, allIds)}
              />
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function DrawerView({ edit }: { edit: boolean }) {
  const role = useSession((s) => s.session?.user.role ?? 'user');
  const pinned = useDock((s) => s.pinned);
  const [query, setQuery] = useState('');
  const all = programs(role);
  const allIds = all.map((p) => p.id);
  const shown = all.filter((p) => p.name.toLowerCase().includes(query.trim().toLowerCase()));
  const close = () => useShell.getState().setDrawer('closed');
  // 설정·Dock 메뉴에서 곧장 편집으로 연 서랍은 「완료」로 닫는다. 서랍 안에서 편집에 들어갔으면 목록으로 돌아간다(B3).
  const [openedInEdit] = useState(edit);
  const ref = useRef<HTMLDivElement>(null);
  const trap = useModalFocus(ref);
  const launch = (id: string) => {
    useWindows.getState().open(id);
    close();
  };
  const inDock = (id: string) => (pinned ?? allIds).includes(id);
  const toggleDock = (id: string) => (inDock(id) ? useDock.getState().unpin(id, allIds) : useDock.getState().pin(id, allIds));

  return (
    <div
      ref={ref}
      className="os-drawer"
      role="dialog"
      aria-modal="true"
      aria-label="앱 목록"
      onKeyDown={(e) => (e.key === 'Escape' ? close() : trap(e))}
      onPointerDown={(e) => e.target === e.currentTarget && close()}
    >
      <div className="os-drawer-head">
        <input
          type="search"
          className="os-drawer-search"
          aria-label="프로그램 찾기"
          placeholder="프로그램 찾기"
          autoFocus
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && shown[0] && launch(shown[0].id)}
        />
        <Button onClick={() => (edit && openedInEdit ? close() : useShell.getState().setDrawer(edit ? 'open' : 'edit'))}>
          {edit ? '완료' : '편집'}
        </Button>
        <Button aria-label="닫기" title="닫기 (Esc)" onClick={close}>
          ✕
        </Button>
      </div>
      <DrawerGrid shown={shown} edit={edit} inDock={inDock} toggleDock={toggleDock} launch={launch} />
      {edit && <DockOrder all={all} />}
    </div>
  );
}

interface GridProps {
  shown: ProgramManifest[];
  edit: boolean;
  inDock(id: string): boolean;
  toggleDock(id: string): void;
  launch(id: string): void;
}

/** 큰 아이콘(72px) 격자. 편집 모드에서는 칸마다 「Dock에 두기」 체크. */
function DrawerGrid({ shown, edit, inDock, toggleDock, launch }: GridProps) {
  return (
    <div className="os-drawer-grid">
      {shown.map((p) => (
        <div key={p.id} className="os-drawer-cell">
          <button type="button" className="os-drawer-app" aria-label={`${p.name} 열기`} onClick={() => launch(p.id)}>
            <ProgramIcon program={p} size={72} />
            <span className="os-drawer-name">{p.name}</span>
          </button>
          {edit && (
            <label className="os-drawer-keep">
              <input type="checkbox" aria-label={`${p.name} Dock에 두기`} checked={inDock(p.id)} onChange={() => toggleDock(p.id)} />
              Dock에 두기
            </label>
          )}
        </div>
      ))}
      {shown.length === 0 && <p className="os-drawer-empty">찾은 프로그램이 없습니다.</p>}
    </div>
  );
}

/** 앱 서랍(Launchpad): 쓸 수 있는 모든 프로그램을 큰 아이콘 격자로. 편집 모드에서 Dock 에 넣고 빼고 차례를 바꾼다. */
export default function AppDrawer() {
  const mode = useShell((s) => s.drawer);
  return mode === 'closed' ? null : <DrawerView edit={mode === 'edit'} />;
}
