import { useEffect, useRef } from 'react';
import type { DockEntry } from './dockStore';
import { MenuList, SEPARATOR, stepFocus, type MenuEntry } from './MenuGroup';
import { programs } from './registry';
import { useSession } from './session';
import { useShell } from './shell';
import { useDock } from './dockStore';
import { useWindows } from './windowStore';

const allIds = () => programs(useSession.getState().session?.user.role ?? 'user').map((p) => p.id);

/** 항목 메뉴 줄: 앱 목록은 「열기」만, 프로그램은 창 목록(또는 열기) ─ 옵션 ─ 닫기. */
export function dockMenuItems(entry: DockEntry): MenuEntry[] {
  if (entry.kind === 'apps') return [{ label: '열기', run: () => useShell.getState().setDrawer('open') }];
  if (entry.kind !== 'program') return [];
  const { program, pinned } = entry;
  const w = useWindows.getState();
  const d = useDock.getState();
  const mine = w.wins.filter((x) => x.programId === program.id);
  const options: MenuEntry[] = [
    { type: 'title', label: '옵션' },
    { label: 'Dock에 유지', checked: pinned, run: () => (pinned ? d.unpin(program.id, allIds()) : d.pin(program.id, allIds())) },
    { label: 'Dock에서 제거', disabled: !pinned, run: () => d.unpin(program.id, allIds()) },
  ];
  if (!mine.length) return [{ label: '열기', run: () => w.open(program.id) }, SEPARATOR, ...options];
  return [
    ...mine.map((x) => ({ label: x.minimized ? `${x.title} (최소화)` : x.title, run: () => w.focus(x.id) })),
    SEPARATOR,
    ...options,
    SEPARATOR,
    { label: '닫기', run: () => mine.forEach((x) => w.close(x.id)) },
  ];
}

interface DockMenuProps {
  entry: DockEntry;
  name: string;
  /** 항목 가운데(Dock 틀 기준 px). 메뉴는 그 위에 가운데를 맞춘다. */
  left: number;
  onClose(refocus: boolean): void;
}

/** Dock 항목 메뉴. 열리면 첫 항목에 포커스, Esc 는 닫고 그 항목으로 돌아간다. 바깥을 누르면 닫힌다. */
export default function DockMenu({ entry, name, left, onClose }: DockMenuProps) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    stepFocus(ref.current, 1);
    const onPointer = (e: PointerEvent) => !ref.current?.contains(e.target as Node) && onClose(false);
    document.addEventListener('pointerdown', onPointer);
    return () => document.removeEventListener('pointerdown', onPointer);
  }, [onClose]);
  return (
    <div className="os-dock-menu" style={{ left }}>
      <MenuList
        menu={{ label: name, items: dockMenuItems(entry) }}
        menuRef={ref}
        onPick={() => onClose(true)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown' || e.key === 'ArrowUp') stepFocus(ref.current, e.key === 'ArrowDown' ? 1 : -1);
          else if (e.key === 'Escape') onClose(true);
          else if (e.key === 'Tab') onClose(false);
          else return;
          e.preventDefault();
          e.stopPropagation();
        }}
      />
    </div>
  );
}
