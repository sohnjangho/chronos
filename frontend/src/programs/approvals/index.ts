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
  icon: glyph('M12 3.5l7 2.8v5.4c0 4.5-3 7.9-7 9.3-4-1.4-7-4.8-7-9.3V6.3z', 'M8.8 12.2l2.3 2.3 4.4-4.8'),
  component: lazy(() => import('./Approvals')),
};

export default manifest;
