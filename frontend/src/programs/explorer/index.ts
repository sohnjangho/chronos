import { lazy } from 'react';
import { glyph } from '../../os/glyph';
import type { ProgramManifest } from '../../os/registry';

const manifest: ProgramManifest = {
  id: 'explorer',
  name: '탐색기',
  tone: 'sky',
  kind: 'system',
  defaultSize: { w: 1100, h: 720 },
  icon: glyph('M5 5.5h4.5l2 2H19a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-10a2 2 0 0 1 2-2z', 'M3.5 10.5h17'),
  component: lazy(() => import('./Explorer')),
};

export default manifest;
