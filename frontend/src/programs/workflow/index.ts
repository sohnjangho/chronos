import { lazy } from 'react';
import { glyph } from '../../os/glyph';
import type { ProgramManifest } from '../../os/registry';

const manifest: ProgramManifest = {
  id: 'workflow',
  name: '워크플로우',
  tone: 'indigo',
  kind: 'system',
  defaultSize: { w: 1400, h: 860 },
  icon: glyph('M4 4h5v5H4z', 'M15 4h5v5h-5z', 'M9.5 15h5v5h-5z', 'M9 6.5h6', 'M17.5 9v3H12v3'),
  component: lazy(() => import('./Workflow')),
};

export default manifest;
