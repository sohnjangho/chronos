import { lazy } from 'react';
import { glyph } from '../../os/glyph';
import type { ProgramManifest } from '../../os/registry';

// 화면은 이 프로그램 작업에서 만든다. 그때 component 를 lazy(() => import('./화면파일')) 로 바꾼다.
const manifest: ProgramManifest = {
  id: 'schedule',
  name: '일정판',
  kind: 'work',
  defaultSize: { w: 1600, h: 900 },
  icon: glyph('M4 4v16h16', 'M7 7h7', 'M10 11h8', 'M8 15h6'),
  component: lazy(() => import('../../os/Placeholder')),
};

export default manifest;
