import type { ProgramProps } from '../../os/registry';
import ScheduleFrame from '../../shared/schedule/ScheduleFrame';
import ProgressTab from './ProgressTab';

/** 「공정률」: 창 틀(제목·머리줄·화면 맥락)은 ScheduleFrame, 안쪽은 진행 API 또는 현장 모바일 협업 허브. */
export default function Progress({ windowId, params }: ProgramProps) {
  return (
    <ScheduleFrame windowId={windowId} params={params} programId="progress" name="공정률">
      <ProgressTab initialView={params?.view === 'field' ? 'field' : 'dashboard'} humanRead={params?.tab === 'human-read'} />
    </ScheduleFrame>
  );
}
