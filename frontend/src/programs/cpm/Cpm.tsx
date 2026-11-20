import type { ProgramProps } from '../../os/registry';
import ScheduleFrame from '../../shared/schedule/ScheduleFrame';

/** 「CPM」: 계획 2 Task 31 이 이 자리(children)에 네트워크 화면을 넣는다. 그때까지는 안내 글만(누를 것 없음). */
export default function Cpm({ windowId, params }: ProgramProps) {
  return (
    <ScheduleFrame windowId={windowId} params={params} programId="cpm" name="CPM">
      <p className="sch-empty">다음 묶음에서 만듭니다</p>
    </ScheduleFrame>
  );
}
