import { lazy } from 'react';
import { glyph } from '../../os/glyph';
import type { ProgramManifest } from '../../os/registry';

// 「개발 콘솔」(관리자만): 에이전트 구조 · 실행 추적 · 사용량·비용.
const manifest: ProgramManifest = {
  id: 'devconsole',
  name: '개발 콘솔',
  tone: 'graphite',
  kind: 'system',
  adminOnly: true,
  defaultSize: { w: 1600, h: 900 },
  icon: glyph('M5.5 4.5h13A2 2 0 0 1 20.5 6.5v11a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2v-11a2 2 0 0 1 2-2z', 'M7.5 9.8l2.8 2.2-2.8 2.2', 'M12.5 14.5h4'),
  component: lazy(() => import('./DevConsole')),
};

export default manifest;
