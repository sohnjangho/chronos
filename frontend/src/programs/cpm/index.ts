import { lazy } from 'react';
import { glyph } from '../../os/glyph';
import type { ProgramManifest } from '../../os/registry';

// 「CPM」 네트워크(계획 2 Task 31). params: id(일정, 없으면 OS 의 지금 일정) · activity.
const manifest: ProgramManifest = {
  id: 'cpm',
  name: 'CPM',
  tone: 'fuchsia',
  kind: 'work',
  defaultSize: { w: 1600, h: 900 },
  icon: glyph(
    'M7 12a2 2 0 1 1-4 0a2 2 0 1 1 4 0',
    'M14 6a2 2 0 1 1-4 0a2 2 0 1 1 4 0',
    'M14 18a2 2 0 1 1-4 0a2 2 0 1 1 4 0',
    'M21 12a2 2 0 1 1-4 0a2 2 0 1 1 4 0',
    'M6.5 10.6l3.5-3.2',
    'M6.5 13.4l3.5 3.2',
    'M14 7.4l3.5 3.2',
    'M14 16.6l3.5-3.2',
  ),
  component: lazy(() => import('./Cpm')),
};

export default manifest;
