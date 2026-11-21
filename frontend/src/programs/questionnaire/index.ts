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
  icon: glyph('M9.5 3.5h5a1 1 0 0 1 1 1v2h-7v-2a1 1 0 0 1 1-1z', 'M8.5 5H7a2 2 0 0 0-2 2v11.5a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-1.5', 'M8.5 12.5l2.2 2.2 4.8-4.8', 'M8.5 17.5h7'),
  component: lazy(() => import('./Questionnaire')),
};

export default manifest;
