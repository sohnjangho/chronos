import type { ProgramProps } from '../../os/registry';
import ScheduleFrame from '../../shared/schedule/ScheduleFrame';
import ProgressTab from './ProgressTab';

/** 「공정률」: 창 틀(제목·머리줄·화면 맥락)은 ScheduleFrame, 안쪽은 진행 API 로 그린 공정률 화면. */
export default function Progress({ windowId, params }: ProgramProps) {
  return (
    <ScheduleFrame windowId={windowId} params={params} programId="progress" name="공정률">
      <ProgressTab />
    </ScheduleFrame>
  );
}
