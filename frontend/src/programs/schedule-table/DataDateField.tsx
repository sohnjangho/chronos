// 머리줄 Data Date: 누르면 날짜 칸이 열리고 Enter 로 일정의 Data Date 를 바꾼다(새 버전 — 되돌리기로 돌아감).
// 날짜는 서버가 받은 그대로 다시 그린다(화면은 날짜를 계산하지 않는다). 409 는 다른 고침처럼 다시 불러온다.
import { useState, type KeyboardEvent } from 'react';
import Badge from '../../shared/ui/Badge';
import { isoDate } from '../../shared/schedule/edits';
import { dot } from '../../shared/schedule/format';
import { useNotify, useSchedule, useScheduleStore } from '../../shared/schedule/scope';

export default function DataDateField() {
  const store = useScheduleStore();
  const notify = useNotify();
  const current = useSchedule((s) => s.view?.data_date ?? null);
  const [open, setOpen] = useState(false);

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Escape') setOpen(false);
    if (e.key !== 'Enter') return;
    e.preventDefault();
    const text = e.currentTarget.value.trim();
    const date = text ? isoDate(text) : null;
    if (text && !date) return notify('error', `날짜 형식이 맞지 않습니다: ${text} (예 2027.05.12)`);
    setOpen(false);
    if (date !== current) void store.getState().setDataDate(date);
  }

  if (open)
    return (
      <label className="sch-dd-edit">
        <span className="sch-muted">Data Date</span>
        <input
          className="sch-dd-input"
          aria-label="Data Date"
          placeholder="2027.06.01"
          defaultValue={dot(current)}
          autoFocus
          onKeyDown={onKeyDown}
          onBlur={() => setOpen(false)}
        />
      </label>
    );
  return (
    <button type="button" className="sch-dd" title="눌러서 Data Date 를 바꿉니다" onClick={() => setOpen(true)}>
      <span className="sch-muted">Data Date</span>
      <span className="sch-date">{current ? dot(current) : '없음'}</span>
    </button>
  );
}

/** 머리줄 경고: 직접 입력 방식에서 가중치를 넣지 않은 작업 수(서버 summary.weight_missing). */
export function WeightMissing() {
  const missing = useSchedule((s) => s.view?.summary.weight_missing ?? 0);
  return missing > 0 ? <Badge tone="warning">{`가중치 없는 작업 ${missing}개`}</Badge> : null;
}
