import { lazy } from 'react';
import { glyph } from '../../os/glyph';
import type { ProgramManifest } from '../../os/registry';

const manifest: ProgramManifest = {
  id: 'library',
  name: '자료함',
  tone: 'cyan',
  kind: 'work',
  defaultSize: { w: 1400, h: 860 },
  icon: glyph('M4 5h16v4H4z', 'M5 9v10h14V9', 'M9 13h6'),
  component: lazy(() => import('./Library')),
};

export default manifest;
