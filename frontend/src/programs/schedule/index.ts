import { lazy } from 'react';
import { glyph } from '../../os/glyph';
import type { ProgramManifest } from '../../os/registry';

// params: id(일정, 없으면 OS 의 지금 일정) · tab(table·gantt·cpm·progress) · activity(고를 액티비티).
const manifest: ProgramManifest = {
  id: 'schedule',
  name: '일정판',
  tone: 'blue',
  kind: 'work',
  defaultSize: { w: 1600, h: 900 },
  icon: glyph('M4 4v16h16', 'M7 7h7', 'M10 11h8', 'M8 15h6'),
  component: lazy(() => import('./Schedule')),
};

export default manifest;
