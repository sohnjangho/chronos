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
  icon: glyph('M4 4v16h16', 'M7 17c3 0 4-1.5 5.5-5S16 7 19 7'),
  component: lazy(() => import('./Progress')),
};

export default manifest;
