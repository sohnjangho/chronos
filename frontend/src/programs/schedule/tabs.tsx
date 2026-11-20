// 일정판 탭 목록(탭 줄은 이것으로 끝이다). 다음 작업은 자기 탭의 component 한 줄만 바꾼다.
//   예: { id: 'gantt', label: '간트', component: lazy(() => import('./gantt/GanttTab')) }
// 탭 화면은 일정이 읽힌 뒤에만 그려진다 — useSchedule((s) => s.view)! 로 읽어도 된다.
import { lazy, type ComponentType } from 'react';
import TableTab from './table/TableTab';

export type TabId = 'table' | 'gantt' | 'cpm' | 'progress';

export interface TabProps {
  windowId: string;
}

export interface ScheduleTab {
  id: TabId;
  label: string;
  component: ComponentType<TabProps>;
}

function NextBundle() {
  return <p className="sch-empty">다음 묶음에서 만듭니다</p>;
}

export const TABS: ScheduleTab[] = [
  { id: 'table', label: '스케줄표', component: TableTab },
  { id: 'gantt', label: '간트', component: lazy(() => import('./gantt/GanttTab')) },
  { id: 'cpm', label: 'CPM', component: NextBundle },
  { id: 'progress', label: '진행', component: NextBundle },
];

export const asTab = (id: string | undefined): TabId | null => TABS.find((t) => t.id === id)?.id ?? null;
