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

/** 편집 모드의 Dock 차례: 끌어서 옮기거나, 포커스한 줄에서 Alt+←→ 로 옮긴다. */
function DockOrder({ all }: { all: ProgramManifest[] }) {
  const pinned = useDock((s) => s.pinned);
  const allIds = all.map((p) => p.id);
  const byId = new Map(all.map((p) => [p.id, p]));
  const order = (pinned ?? allIds).filter((id) => byId.has(id));
  const [dragId, setDragId] = useState<string | null>(null);
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
      <div className="os-drawer-dock-title">Dock 차례 · 끌어서 옮기거나 Alt+←→</div>
      <ol aria-label="Dock 차례" className="os-drawer-order">
        {order.map((id, i) => (
          <li
            key={id}
            ref={(el) => void refs.current.set(id, el)}
            tabIndex={0}
            draggable
            className={dragId === id ? 'is-dragging' : undefined}
            onDragStart={() => setDragId(id)}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              if (dragId && dragId !== id) move(dragId, i);
              setDragId(null);
            }}
            onDragEnd={() => setDragId(null)}
            onKeyDown={(e) => onKeyDown(e, id, i)}
          >
            <ProgramIcon program={byId.get(id)!} size={32} />
            <span>{byId.get(id)!.name}</span>
          </li>
        ))}
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
        <Button onClick={() => useShell.getState().setDrawer(edit ? 'open' : 'edit')}>{edit ? '완료' : '편집'}</Button>
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
