import { lazy } from 'react';
import { glyph } from '../../os/glyph';
import type { ProgramManifest } from '../../os/registry';

// 「프로젝트 관리」(11-24). 프로젝트 이름과, 에이전트가 통화·문자에서 쓰는 소개(부를 이름·현장 주소·한 줄 소개·발주처·시공사).
// 현장 관리자는 고칠 수 없어(서버 403) Dock 에도 없다(noField).
const manifest: ProgramManifest = {
  id: 'projects',
  name: '프로젝트 관리',
  tone: 'navy',
  kind: 'work',
  noField: true,
  defaultSize: { w: 1100, h: 720 },
  icon: glyph('M4 7.5h16v11.5H4z', 'M9 7.5V5h6v2.5', 'M4 12.5h16', 'M10.5 12.5v2h3v-2'),
  component: lazy(() => import('./Projects')),
};

export default manifest;
