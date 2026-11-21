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
  icon: glyph('M7.5 6h5a1.5 1.5 0 0 1 0 3h-5a1.5 1.5 0 0 1 0-3z', 'M10.5 10.5h7a1.5 1.5 0 0 1 0 3h-7a1.5 1.5 0 0 1 0-3z', 'M8.5 15h5.5a1.5 1.5 0 0 1 0 3H8.5a1.5 1.5 0 0 1 0-3z', 'M4 4.5v15'),
  component: lazy(() => import('./Gantt')),
};

export default manifest;
