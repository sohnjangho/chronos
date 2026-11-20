import type { ProgramProps } from '../../os/registry';
import ScheduleFrame from '../../shared/schedule/ScheduleFrame';
import CpmTab from './CpmTab';

/** 「CPM」: 일정 네트워크(카드·관계선·상세·관계 고치기·요약 줄·PNG). 창 제목·머리줄·화면 맥락·params.activity 는 틀이 한다. */
export default function Cpm({ windowId, params }: ProgramProps) {
  return (
    <ScheduleFrame windowId={windowId} params={params} programId="cpm" name="CPM">
      <CpmTab />
    </ScheduleFrame>
  );
}
