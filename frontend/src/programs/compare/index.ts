import { lazy } from 'react';
import { glyph } from '../../os/glyph';
import type { ProgramManifest } from '../../os/registry';

// 「비교판」 자리(화면은 이후 작업이 채운다).
const manifest: ProgramManifest = {
  id: 'compare',
  name: '비교판',
  tone: 'lime',
  kind: 'work',
  defaultSize: { w: 1600, h: 900 },
  icon: glyph('M4 5h7v14H4z', 'M13 5h7v14h-7z', 'M7 9h1', 'M16 9h1', 'M7 13h1', 'M16 13h1'),
  component: lazy(() => import('../../os/Placeholder')),
};

export default manifest;
