// 지연 알림(창 안 띠): 버전을 바꾼 고침의 응답에서 어떤 액티비티의 Plan 대비 늦음(서버 status "late +n")이 늘었으면
// "A2020 이(가) Plan보다 3일 늦어졌습니다." + [지연 기록 열기] · [닫기]. 고친 액티비티가 늦어졌으면 그것을, 아니면 처음 것을 짚는다.
// 일수는 서버 status 의 차이만 쓴다(화면은 날짜를 계산하지 않는다). 되돌리기·다시 읽기를 하면 알림을 거둔다.
// 닫으면 저장소에서 지운다 — 창을 다시 열어도 다음 고침 전까지는 다시 뜨지 않는다.
// [지연 기록 열기] 는 고치기 전 버전(before)을 넘긴다: 지연 기록이 source "actual" 로 이미 들어간 늦음을 적게.
import { useWindows } from '../../os/windowStore';
import Button from '../../shared/ui/Button';
import { lateDays } from '../../shared/schedule/format';
import type { LastChange } from '../../shared/schedule/scheduleStore';
import { useSchedule, useScheduleStore } from '../../shared/schedule/scope';

interface Later {
  aid: string;
  /** 는 늦음(근무일). */
  days: number;
  /** 고치기 전에도 늦었는가. */
  already: boolean;
}

/** 늦음이 는 액티비티(고친 액티비티 먼저, 아니면 일정 차례로 처음 것). 없으면 null. */
export function laterOf(c: LastChange): Later | null {
  const old = new Map(c.before.activities.map((a) => [a.id, lateDays(a.status)]));
  const grown = c.after.activities
    .map((a) => ({ aid: a.id, days: lateDays(a.status) - (old.get(a.id) ?? 0), already: (old.get(a.id) ?? 0) > 0 }))
    .filter((x) => x.days > 0);
  return grown.find((x) => x.aid === c.aid) ?? grown[0] ?? null;
}

export default function DelayNotice() {
  const store = useScheduleStore();
  const change = useSchedule((s) => s.lastChange);
  const scheduleId = useSchedule((s) => s.scheduleId);
  const later = change ? laterOf(change) : null;
  if (!change || !later) return null;
  const close = () => store.getState().dismissChange();
  const open = () => {
    close();
    useWindows.getState().open('delays', {
      id: String(scheduleId),
      activity: later.aid,
      days: String(later.days),
      before: String(change.before.version),
    });
  };
  return (
    <div className="sch-delay" role="status">
      <span>{`${later.aid} 이(가) Plan보다 ${later.days}일 ${later.already ? '더 ' : ''}늦어졌습니다.`}</span>
      <Button variant="primary" onClick={open}>
        지연 기록 열기
      </Button>
      <Button onClick={close}>닫기</Button>
    </div>
  );
}
