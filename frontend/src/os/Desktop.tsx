import { useEffect, useState } from 'react';
import About from './About';
import { useApprovalPolling } from './approvals';
import ApprovalWidget from './ApprovalWidget';
import Dock from './Dock';
import LockScreen from './LockScreen';
import MenuBar from './MenuBar';
import { useSession } from './session';
import Window from './Window';
import { topWindow, useWindows } from './windowStore';

/**
 * 바탕화면: 메뉴바 · 위젯 · 창 · Dock. 잠기면 잠금 화면이 위를 덮고 아래는 손댈 수 없다.
 * 브라우저 크기가 바뀌면 창을 모두 화면 안으로 다시 맞춘다.
 */
export default function Desktop() {
  const wins = useWindows((s) => s.wins);
  const locked = useSession((s) => s.locked);
  const [about, setAbout] = useState(false);
  useApprovalPolling();
  useEffect(() => {
    const onResize = () => useWindows.getState().fitToScreen();
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);
  const active = topWindow(wins);

  return (
    <div className="os-desktop">
      <div className="os-screen" inert={locked}>
        <MenuBar onAbout={() => setAbout(true)} />
        <ApprovalWidget />
        <div className="os-windows">
          {wins.map((w) => (
            <Window key={w.id} win={w} active={w === active} />
          ))}
        </div>
        <Dock />
        {about && <About onClose={() => setAbout(false)} />}
      </div>
      {locked && <LockScreen />}
    </div>
  );
}
