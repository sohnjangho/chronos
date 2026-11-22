import { lazy } from 'react';
import { glyph } from '../../os/glyph';
import type { ProgramManifest } from '../../os/registry';

const manifest: ProgramManifest = {
  id: 'reports',
  name: '보고서',
  tone: 'emerald',
  kind: 'work',
  defaultSize: { w: 1400, h: 860 },
  icon: glyph('M7 3.5h7l4 4V19a1.5 1.5 0 0 1-1.5 1.5h-9.5A1.5 1.5 0 0 1 5.5 19V5A1.5 1.5 0 0 1 7 3.5z', 'M14 3.5V8h4.5', 'M9 12h6', 'M9 15.5h4'),
  component: lazy(() => import('./Reports')),
};

export default manifest;
