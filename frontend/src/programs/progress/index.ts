import { lazy } from 'react';
import { glyph } from '../../os/glyph';
import type { ProgramManifest } from '../../os/registry';

// 「공정률」 계획·실적 공정률과 S-커브(진행 API). params: id(일정, 없으면 OS 의 지금 일정).
const manifest: ProgramManifest = {
  id: 'progress',
  name: '공정률',
  tone: 'rose',
  kind: 'work',
  defaultSize: { w: 1400, h: 860 },
  icon: glyph('M6.5 17c3 0 4.2-1.8 5.8-5.2S16 6.8 19.5 6.8V19H6.5z', 'M4.5 4.5v13a1.5 1.5 0 0 0 1.5 1.5h13.5'),
  component: lazy(() => import('./Progress')),
};

export default manifest;
