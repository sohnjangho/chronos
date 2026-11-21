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
  icon: glyph('M6 4.5h12a2.5 2.5 0 0 1 2.5 2.5v7a2.5 2.5 0 0 1-2.5 2.5H10l-4.5 3.5v-3.5H6A2.5 2.5 0 0 1 3.5 14V7A2.5 2.5 0 0 1 6 4.5z', 'M8 9h8', 'M8 12.2h5'),
  menus: [
    {
      label: '대화',
      items: [
        // 대화 상태는 창 밖 store 에 있다(처음 쓸 때 불러온다 — 시작 묶음을 키우지 않게).
        { label: '새 대화', action: () => import('./chatStore').then(({ useChat }) => useChat.getState().newChat()) },
        // 도움말: 답은 OS 전체의 에이전트가 만든다 — 창을 닫아도 이어지고, 다시 열면 이어서 보인다.
        { label: '창을 닫아도 도는 답은 이어집니다 · 다시 열면 이어서 보입니다', action: () => {}, disabled: true, separatorBefore: true },
      ],
    },
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
