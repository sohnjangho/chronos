import { lazy } from 'react';
import { glyph } from '../../os/glyph';
import type { ProgramManifest } from '../../os/registry';

// params: id(질문지) · session(제출 뒤 이어 갈 대화, 없으면 질문지를 만든 대화).
const manifest: ProgramManifest = {
  id: 'questionnaire',
  name: '질문지',
  tone: 'teal',
  kind: 'system',
  defaultSize: { w: 1180, h: 860 },
  icon: glyph('M9 3h6v3H9z', 'M7 4.5H5V21h14V4.5h-2', 'M8 12l2 2 4-4', 'M8 17.5h8'),
  component: lazy(() => import('./Questionnaire')),
};

export default manifest;
