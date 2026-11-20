import { lazy } from 'react';
import { glyph } from '../../os/glyph';
import type { ProgramManifest } from '../../os/registry';

const manifest: ProgramManifest = {
  id: 'explorer',
  name: '탐색기',
  tone: 'sky',
  kind: 'system',
  defaultSize: { w: 1100, h: 720 },
  icon: glyph('M3 6h6l2 2h10v11H3z', 'M3 11h18'),
  component: lazy(() => import('./Explorer')),
};

export default manifest;
