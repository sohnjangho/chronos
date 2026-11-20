import { lazy } from 'react';
import { glyph } from '../../os/glyph';
import type { ProgramManifest } from '../../os/registry';

// 「스케줄」 일정 표. params: id(일정, 없으면 OS 의 지금 일정) · activity(고르고 보일 액티비티).
const manifest: ProgramManifest = {
  id: 'schedule-table',
  name: '스케줄',
  tone: 'blue',
  kind: 'work',
  defaultSize: { w: 1600, h: 900 },
  icon: glyph('M4 5h16v14H4z', 'M4 10h16', 'M4 14.5h16', 'M9 5v14'),
  component: lazy(() => import('./ScheduleTable')),
};

export default manifest;
