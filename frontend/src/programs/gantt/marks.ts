// 간트에 그릴 조건 표시: 준공 기한(finish_by)과 마일스톤 기한(milestone_by). 조건·규칙 GET(Task 18)을 읽는다.
// 꺼졌거나 뒤 겹에 진 조건(state 'off')은 그리지 않는다. 날짜는 조건에 적힌 그대로다(계산하지 않음).
import { useEffect, useState } from 'react';
import { api } from '../../shared/api';

export interface FinishBy {
  id: string;
  date: string;
  text: string;
}

export interface MilestoneBy extends FinishBy {
  activityId: string;
}

export interface ConditionMarks {
  finishBy: FinishBy[];
  milestoneBy: MilestoneBy[];
}

interface CondLite {
  id: string;
  kind: string;
  params: Record<string, unknown>;
  text: string;
  state: string;
}

export const NO_MARKS: ConditionMarks = { finishBy: [], milestoneBy: [] };
const ISO = /^\d{4}-\d{2}-\d{2}$/;
const dateOf = (c: CondLite) => (typeof c.params.date === 'string' && ISO.test(c.params.date) ? c.params.date : null);

export function marksOf(layers: Record<string, CondLite[]>): ConditionMarks {
  const live = Object.values(layers).flat().filter((c) => c.state !== 'off' && dateOf(c));
  return {
    finishBy: live.filter((c) => c.kind === 'finish_by').map((c) => ({ id: c.id, date: dateOf(c)!, text: c.text })),
    milestoneBy: live
      .filter((c) => c.kind === 'milestone_by' && typeof c.params.activity_id === 'string')
      .map((c) => ({ id: c.id, date: dateOf(c)!, text: c.text, activityId: c.params.activity_id as string })),
  };
}

/** 저장된 일정의 조건 표시. 버전이 바뀌면 다시 읽는다. 못 읽으면 표시 없이 둔다(간트는 그대로 쓸 수 있다). */
export function useConditionMarks(scheduleId: number, version: number): ConditionMarks {
  const [marks, setMarks] = useState<ConditionMarks>(NO_MARKS);
  useEffect(() => {
    let live = true;
    api<{ layers: Record<string, CondLite[]> }>(`/api/schedules/${scheduleId}/conditions`)
      .then((v) => live && setMarks(marksOf(v.layers)))
      .catch(() => live && setMarks(NO_MARKS));
    return () => {
      live = false;
    };
  }, [scheduleId, version]);
  return marks;
}
