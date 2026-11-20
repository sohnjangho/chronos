import { lazy } from 'react';
import { glyph } from '../../os/glyph';
import type { ProgramManifest } from '../../os/registry';

// 화면은 이 프로그램 작업에서 만든다. 그때 component 를 lazy(() => import('./화면파일')) 로 바꾼다.
const manifest: ProgramManifest = {
  id: 'chat',
  name: '에이전트 대화',
  tone: 'violet',
  kind: 'system',
  defaultSize: { w: 1560, h: 900 },
  icon: glyph('M4 5h16v11H10l-6 4z', 'M8 9.5h8', 'M8 12.5h5'),
  component: lazy(() => import('../../os/Placeholder')),
};

export default manifest;
