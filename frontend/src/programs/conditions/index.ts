import { lazy } from 'react';
import { glyph } from '../../os/glyph';
import type { ProgramManifest } from '../../os/registry';

// 화면은 이 프로그램 작업에서 만든다. 그때 component 를 lazy(() => import('./화면파일')) 로 바꾼다.
const manifest: ProgramManifest = {
  id: 'conditions',
  name: '조건·규칙',
  kind: 'work',
  defaultSize: { w: 1400, h: 860 },
  icon: glyph('M11 6h9', 'M11 12h9', 'M11 18h9', 'M4 6l1.5 1.5L8 5', 'M4 12l1.5 1.5L8 11', 'M4 18h4'),
  component: lazy(() => import('../../os/Placeholder')),
};

export default manifest;
