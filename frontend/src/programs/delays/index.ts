import { lazy } from 'react';
import { glyph } from '../../os/glyph';
import type { ProgramManifest } from '../../os/registry';

// 「지연 기록」 자리(화면은 이후 작업이 채운다).
const manifest: ProgramManifest = {
  id: 'delays',
  name: '지연 기록',
  tone: 'brown',
  kind: 'work',
  defaultSize: { w: 1400, h: 860 },
  icon: glyph('M12 7v5l3 2', 'M20 12a8 8 0 1 1-2.3-5.6', 'M20 4v4h-4'),
  component: lazy(() => import('../../os/Placeholder')),
};

export default manifest;
