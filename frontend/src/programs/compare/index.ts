import { lazy } from 'react';
import { glyph } from '../../os/glyph';
import type { ProgramManifest } from '../../os/registry';

// 「비교판」 기준·비교 두 안과 여러 안 요약(비교 API). params: id(일정) · base · other(ref: current·plan·v:<n>·s:<복사본 id>).
const manifest: ProgramManifest = {
  id: 'compare',
  name: '비교판',
  tone: 'lime',
  kind: 'work',
  defaultSize: { w: 1600, h: 900 },
  icon: glyph('M5.5 4.5h4A1.5 1.5 0 0 1 11 6v12a1.5 1.5 0 0 1-1.5 1.5h-4A1.5 1.5 0 0 1 4 18V6a1.5 1.5 0 0 1 1.5-1.5z', 'M14.5 4.5h4A1.5 1.5 0 0 1 20 6v12a1.5 1.5 0 0 1-1.5 1.5h-4A1.5 1.5 0 0 1 13 18V6a1.5 1.5 0 0 1 1.5-1.5z', 'M6.5 9h2', 'M15.5 9h2', 'M6.5 13h2', 'M15.5 13h2'),
  component: lazy(() => import('./Compare')),
};

export default manifest;
