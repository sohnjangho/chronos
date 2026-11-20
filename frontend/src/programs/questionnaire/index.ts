import { lazy } from 'react';
import { glyph } from '../../os/glyph';
import type { ProgramManifest } from '../../os/registry';

// 화면은 이 프로그램 작업에서 만든다. 그때 component 를 lazy(() => import('./화면파일')) 로 바꾼다.
const manifest: ProgramManifest = {
  id: 'questionnaire',
  name: '질문지',
  tone: 'teal',
  kind: 'system',
  defaultSize: { w: 1180, h: 860 },
  icon: glyph('M9 3h6v3H9z', 'M7 4.5H5V21h14V4.5h-2', 'M8 12l2 2 4-4', 'M8 17.5h8'),
  component: lazy(() => import('../../os/Placeholder')),
};

export default manifest;
