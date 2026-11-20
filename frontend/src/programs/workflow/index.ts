import { lazy } from 'react';
import { glyph } from '../../os/glyph';
import type { ProgramManifest } from '../../os/registry';

// 화면은 이 프로그램 작업에서 만든다. 그때 component 를 lazy(() => import('./화면파일')) 로 바꾼다.
const manifest: ProgramManifest = {
  id: 'workflow',
  name: '워크플로우',
  kind: 'system',
  defaultSize: { w: 1400, h: 860 },
  icon: glyph('M4 4h5v5H4z', 'M15 4h5v5h-5z', 'M9.5 15h5v5h-5z', 'M9 6.5h6', 'M17.5 9v3H12v3'),
  component: lazy(() => import('../../os/Placeholder')),
};

export default manifest;
