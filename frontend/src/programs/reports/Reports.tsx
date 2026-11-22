import type { ProgramProps } from '../../os/registry';
import ScheduleFrame from '../../shared/schedule/ScheduleFrame';
import ReportsTab from './ReportsTab';

/** 「보고서」: 월간·분기별 보고서 작성 및 프로젝트별 양식 학습·기억·타 프로젝트 선택 재사용. */
export default function Reports({ windowId, params }: ProgramProps) {
  return (
    <ScheduleFrame windowId={windowId} params={params} programId="reports" name="보고서">
      <ReportsTab />
    </ScheduleFrame>
  );
}
