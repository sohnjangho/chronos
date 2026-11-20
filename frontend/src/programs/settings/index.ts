import { lazy } from 'react';
import { glyph } from '../../os/glyph';
import type { ProgramManifest } from '../../os/registry';

// 화면은 이 프로그램 작업에서 만든다. 그때 component 를 lazy(() => import('./화면파일')) 로 바꾼다.
const manifest: ProgramManifest = {
  id: 'settings',
  name: '설정',
  kind: 'system',
  defaultSize: { w: 1300, h: 860 },
  icon: glyph('M4 7h16', 'M4 17h16', 'M9 4v6', 'M15 14v6'),
  component: lazy(() => import('../../os/Placeholder')),
};

export default manifest;
