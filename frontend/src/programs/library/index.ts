import { lazy } from 'react';
import { glyph } from '../../os/glyph';
import type { ProgramManifest } from '../../os/registry';

const manifest: ProgramManifest = {
  id: 'library',
  name: '자료함',
  tone: 'cyan',
  kind: 'work',
  defaultSize: { w: 1400, h: 860 },
  icon: glyph('M5 4.5h14a1.5 1.5 0 0 1 1.5 1.5v2.5a1 1 0 0 1-1 1h-15a1 1 0 0 1-1-1V6A1.5 1.5 0 0 1 5 4.5z', 'M5 9.5h14v8.5a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2z', 'M9.5 13.5h5'),
  component: lazy(() => import('./Library')),
};

export default manifest;
