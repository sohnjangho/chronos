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
  icon: glyph('M5.5 4.5h13A2 2 0 0 1 20.5 6.5v11a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2v-11a2 2 0 0 1 2-2z', 'M3.8 9.5h16.4', 'M3.8 14.2h16.4', 'M9.2 4.8v14.4'),
  component: lazy(() => import('./ScheduleTable')),
};

export default manifest;
