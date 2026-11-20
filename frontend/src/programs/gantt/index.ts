import { lazy } from 'react';
import { glyph } from '../../os/glyph';
import type { ProgramManifest } from '../../os/registry';

// 「간트차트」. params: id(일정, 없으면 OS 의 지금 일정) · activity(고르고 보일 액티비티).
const manifest: ProgramManifest = {
  id: 'gantt',
  name: '간트차트',
  tone: 'orange',
  kind: 'work',
  defaultSize: { w: 1600, h: 900 },
  icon: glyph('M4 4v16h16', 'M7 7h7', 'M10 11h8', 'M8 15h6'),
  component: lazy(() => import('./Gantt')),
};

export default manifest;
