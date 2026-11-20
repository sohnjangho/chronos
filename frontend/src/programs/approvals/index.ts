import { lazy } from 'react';
import { glyph } from '../../os/glyph';
import type { ProgramManifest } from '../../os/registry';

// 화면은 이 프로그램 작업에서 만든다. 그때 component 를 lazy(() => import('./화면파일')) 로 바꾼다.
const manifest: ProgramManifest = {
  id: 'approvals',
  name: '승인함',
  tone: 'amber',
  kind: 'system',
  defaultSize: { w: 1200, h: 760 },
  badge: 'approvals',
  icon: glyph('M4 4h16v16H4z', 'M8 12l3 3 5-6'),
  component: lazy(() => import('../../os/Placeholder')),
};

export default manifest;
