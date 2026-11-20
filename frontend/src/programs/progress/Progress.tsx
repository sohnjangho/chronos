import type { ProgramProps } from '../../os/registry';
import ScheduleFrame from '../../shared/schedule/ScheduleFrame';

/** 「공정률」: 계획 2 Task 32 가 이 자리(children)에 S-커브·공정률 화면을 넣는다. 그때까지는 안내 글만(누를 것 없음). */
export default function Progress({ windowId, params }: ProgramProps) {
  return (
    <ScheduleFrame windowId={windowId} params={params} programId="progress" name="공정률">
      <p className="sch-empty">다음 묶음에서 만듭니다</p>
    </ScheduleFrame>
  );
}
