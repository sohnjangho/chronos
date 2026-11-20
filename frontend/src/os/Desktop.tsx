import { useEffect, type CSSProperties } from 'react';
import { useApprovalPolling } from './approvals';
import AppDrawer from './AppDrawer';
import ApprovalWidget from './ApprovalWidget';
import ContextPanel from './ContextPanel';
import ShellDialogs from './Dialogs';
import Dock from './Dock';
import { useDock } from './dockStore';
import LockScreen from './LockScreen';
import MenuBar from './MenuBar';
import SearchPalette from './SearchPalette';
import { useSession } from './session';
import { useShell } from './shell';
import { useShellShortcuts } from './shortcuts';
import { useTheme } from './theme';
import Window from './Window';
import { activeWindow, useWindows } from './windowStore';
import { useZoom } from './zoom';

/** 사용자가 바뀌면 그 사람의 화면 설정(테마·배율·Dock)을 읽는다. */
function useUserPrefs() {
  const userId = useSession((s) => s.session?.user.id ?? null);
  useEffect(() => {
    useTheme.getState().load(userId);
    useZoom.getState().load(userId);
    useDock.getState().load(userId);
  }, [userId]);
}

/**
 * 바탕화면: 메뉴바 · 위젯 · 창 · Dock. 빈 곳을 누르면 활성 창이 풀린다.
 * 잠기면 잠금 화면이 위를 덮고 아래는 손댈 수 없다. 브라우저 크기가 바뀌면 창을 화면 안으로 다시 맞춘다.
 */
export default function Desktop() {
  const wins = useWindows((s) => s.wins);
  const deactivated = useWindows((s) => s.deactivated);
  const locked = useSession((s) => s.locked);
  const announcement = useShell((s) => s.announcement);
  const inset = useWindows((s) => s.insetRight);
  useApprovalPolling();
  useUserPrefs();
  useShellShortcuts();
  useEffect(() => {
    const onResize = () => useWindows.getState().fitToScreen();
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);
  const active = activeWindow({ wins, deactivated });

  return (
    <div className="os-desktop" style={{ '--inset-right': `${inset}px` } as CSSProperties}>
      <div
        className="os-screen"
        data-testid="desktop-surface"
        inert={locked}
        onPointerDown={(e) => e.target === e.currentTarget && useWindows.getState().clearActive()}
      >
        <MenuBar />
        <ApprovalWidget />
        <div className="os-windows">
          {wins.map((w) => (
            <Window key={w.id} win={w} active={w === active} />
          ))}
        </div>
        <Dock />
        <ShellDialogs />
        <ContextPanel />
        <AppDrawer />
        <SearchPalette />
      </div>
      {locked && <LockScreen />}
      <div role="status" className="os-sr-only">
        {announcement}
      </div>
    </div>
  );
}
