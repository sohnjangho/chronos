import Button from '../ui/Button';
import { useSchedule, useScheduleStore } from './scope';

/**
 * [되돌리기][다시 하기]: 이 일정을 보는 모든 창에서 고친 것의 이력(일정 저장소 하나). 일정이 그 칸의 버전일 때만 켜진다.
 * title 과 알림에 버전 메모를 보인다. 스케줄과 간트차트의 도구줄이 같이 쓴다.
 */
export default function History() {
  const store = useScheduleStore();
  const undo = useSchedule((s) => s.undo.at(-1));
  const redo = useSchedule((s) => s.redo.at(-1));
  const version = useSchedule((s) => s.view?.version);
  const title = (verb: string, note?: string) => (note ? `${verb}: ${note}` : verb);
  return (
    <>
      <Button disabled={!undo || undo.expect !== version} title={title('되돌리기', undo?.note)} onClick={() => void store.getState().undoLast()}>
        되돌리기
      </Button>
      <Button disabled={!redo || redo.expect !== version} title={title('다시 하기', redo?.note)} onClick={() => void store.getState().redoLast()}>
        다시 하기
      </Button>
    </>
  );
}
