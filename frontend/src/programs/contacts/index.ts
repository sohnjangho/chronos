import { lazy } from 'react';
import { glyph } from '../../os/glyph';
import type { ProgramManifest } from '../../os/registry';

// 「연락처」(Task 75). 프로젝트(일정)마다 따로 둔 주소록 + 오른쪽 대화 자리. 현장 관리자에게는 없다(noField).
// params: id(일정, 없으면 OS 지금 일정) · contact(고를 사람 id) · tab('messages' | 'calls') · compose · activity · call — 뒤의 넷은 대화 칸에 넘긴다.
const manifest: ProgramManifest = {
  id: 'contacts',
  name: '연락처',
  tone: 'red',
  kind: 'work',
  noField: true,
  defaultSize: { w: 1280, h: 820 },
  icon: glyph('M5 3h12a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5z', 'M11 12a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5', 'M7 17c.6-2 2.1-3 4-3s3.4 1 4 3', 'M19 7h2', 'M19 11h2', 'M19 15h2'),
  component: lazy(() => import('./Contacts')),
};

export default manifest;
