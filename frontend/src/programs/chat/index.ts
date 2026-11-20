import { lazy } from 'react';
import { glyph } from '../../os/glyph';
import type { ProgramManifest } from '../../os/registry';
import { useWindows } from '../../os/windowStore';

const SMALL = { w: 480, h: 760 };
const LARGE = { w: 1560, h: 900 };

/** 창을 그 크기로(확대해 있으면 풀고). 화면 밖으로는 나가지 않는다(setBounds 가 맞춤). */
function resizeTo(windowId: string, size: { w: number; h: number }) {
  const win = useWindows.getState().wins.find((w) => w.id === windowId);
  if (!win) return;
  if (win.maximized) useWindows.getState().toggleMaximize(windowId);
  useWindows.getState().setBounds(windowId, { x: win.x, y: win.y, ...size });
}

// 기본은 작은 화면(480×760). 너비 1100 이상(초록 단추로 확대, 「보기 → 큰 화면」)이면 큰 화면 배치.
const manifest: ProgramManifest = {
  id: 'chat',
  name: '에이전트 대화',
  tone: 'violet',
  kind: 'system',
  defaultSize: SMALL,
  icon: glyph('M4 5h16v11H10l-6 4z', 'M8 9.5h8', 'M8 12.5h5'),
  menus: [
    {
      label: '보기',
      items: [
        { label: '작은 화면', action: (id) => resizeTo(id, SMALL) },
        { label: '큰 화면', action: (id) => resizeTo(id, LARGE) },
      ],
    },
  ],
  component: lazy(() => import('./Chat')),
};

export default manifest;
