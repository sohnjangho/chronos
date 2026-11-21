import { lazy } from 'react';
import { glyph } from '../../os/glyph';
import type { ProgramManifest } from '../../os/registry';

const manifest: ProgramManifest = {
  id: 'workflow',
  name: '워크플로우',
  tone: 'indigo',
  kind: 'system',
  defaultSize: { w: 1400, h: 860 },
  icon: glyph('M5.5 4h3A1.5 1.5 0 0 1 10 5.5v3A1.5 1.5 0 0 1 8.5 10h-3A1.5 1.5 0 0 1 4 8.5v-3A1.5 1.5 0 0 1 5.5 4z', 'M15.5 4h3A1.5 1.5 0 0 1 20 5.5v3A1.5 1.5 0 0 1 18.5 10h-3A1.5 1.5 0 0 1 14 8.5v-3A1.5 1.5 0 0 1 15.5 4z', 'M10.5 14.5h3a1.5 1.5 0 0 1 1.5 1.5v3a1.5 1.5 0 0 1-1.5 1.5h-3A1.5 1.5 0 0 1 9 19v-3a1.5 1.5 0 0 1 1.5-1.5z', 'M10 7h4', 'M17 10v2.2a1 1 0 0 1-1 1h-4v1.3'),
  component: lazy(() => import('./Workflow')),
};

export default manifest;
