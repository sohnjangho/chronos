import type { ProgramProps } from '../../os/registry';
import ScheduleFrame from '../../shared/schedule/ScheduleFrame';
import GanttTab from './GanttTab';

/** 「간트차트」: 표 · 날짜 막대 · 자원 줄. 조건·규칙 미리 보기도 여기에 그린다. 저장소·고른 줄은 다른 도구 창과 함께 쓴다. */
export default function Gantt({ windowId, params }: ProgramProps) {
  return (
    <ScheduleFrame windowId={windowId} params={params} programId="gantt" name="간트차트">
      <GanttTab />
    </ScheduleFrame>
  );
}
