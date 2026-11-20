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
  icon: glyph('M4 5h7v14H4z', 'M13 5h7v14h-7z', 'M7 9h1', 'M16 9h1', 'M7 13h1', 'M16 13h1'),
  component: lazy(() => import('./Compare')),
};

export default manifest;
