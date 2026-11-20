import { lazy } from 'react';
import { glyph } from '../../os/glyph';
import type { ProgramManifest } from '../../os/registry';

// 「지연 기록」(Task 36). params: id(일정, 없으면 OS 지금 일정) · event(고를 사건) · activity·days·before(채워 여는 새 사건 양식).
const manifest: ProgramManifest = {
  id: 'delays',
  name: '지연 기록',
  tone: 'brown',
  kind: 'work',
  defaultSize: { w: 1400, h: 860 },
  icon: glyph('M12 7v5l3 2', 'M20 12a8 8 0 1 1-2.3-5.6', 'M20 4v4h-4'),
  component: lazy(() => import('./Delays')),
};

export default manifest;
