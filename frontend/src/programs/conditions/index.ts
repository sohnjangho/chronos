import { lazy } from 'react';
import { glyph } from '../../os/glyph';
import type { ProgramManifest } from '../../os/registry';

// params: id(일정, 없으면 OS 의 지금 일정). 네 겹을 나란히 보이고 값을 바꾸면 미리 본다(Task 18).
const manifest: ProgramManifest = {
  id: 'conditions',
  name: '조건·규칙',
  tone: 'green',
  kind: 'work',
  defaultSize: { w: 1400, h: 860 },
  icon: glyph('M11 6h9', 'M11 12h9', 'M11 18h9', 'M4 6l1.5 1.5L8 5', 'M4 12l1.5 1.5L8 11', 'M4 18h4'),
  component: lazy(() => import('./Conditions')),
};

export default manifest;
