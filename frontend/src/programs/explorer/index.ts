import { lazy } from 'react';
import { glyph } from '../../os/glyph';
import type { ProgramManifest } from '../../os/registry';

// 화면은 이 프로그램 작업에서 만든다. 그때 component 를 lazy(() => import('./화면파일')) 로 바꾼다.
const manifest: ProgramManifest = {
  id: 'explorer',
  name: '탐색기',
  kind: 'system',
  defaultSize: { w: 1100, h: 720 },
  icon: glyph('M3 6h6l2 2h10v11H3z', 'M3 11h18'),
  component: lazy(() => import('../../os/Placeholder')),
};

export default manifest;
