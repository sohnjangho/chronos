import { lazy } from 'react';
import { glyph } from '../../os/glyph';
import type { ProgramManifest } from '../../os/registry';

const manifest: ProgramManifest = {
  id: 'approvals',
  name: '승인함',
  tone: 'amber',
  kind: 'system',
  defaultSize: { w: 1200, h: 760 },
  badge: 'approvals',
  icon: glyph('M4 4h16v16H4z', 'M8 12l3 3 5-6'),
  component: lazy(() => import('./Approvals')),
};

export default manifest;
