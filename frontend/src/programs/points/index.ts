import { lazy } from 'react';
import { glyph } from '../../os/glyph';
import type { ProgramManifest } from '../../os/registry';

// 「관리 포인트」(계획 5 Task 11, 시안 B 3주 보드). params: id(일정, 없으면 OS 지금 일정) · activity(고를 포인트).
// 현장 관리자도 읽는다(담당자 연락 단추만 없다 — 서버 403).
const manifest: ProgramManifest = {
  id: 'points',
  name: '관리 포인트',
  tone: 'gold',
  kind: 'work',
  defaultSize: { w: 1500, h: 880 },
  icon: glyph('M4 5h16v14H4z', 'M9.33 5v14', 'M14.67 5v14', 'M5.8 9h2', 'M11 12.5h2', 'M16.2 16h2'),
  component: lazy(() => import('./Points')),
};

export default manifest;
