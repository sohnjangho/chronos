// 근무시간 칸: 요일 칩(월=0 … 일=6) + 시작·끝. 요일을 하나도 고르지 않으면 null = 프로젝트 기본(달력의 근무일 08:00~18:00).
import type { Hours } from './contactsApi';

const DAYS = ['월', '화', '수', '목', '금', '토', '일'];
const DEFAULT = { start: '08:00', end: '18:00' };

interface Props {
  value: Hours | null;
  onChange: (h: Hours | null) => void;
  /** 저장된 값의 설명(「근무 중 · 18:00 까지」 등). 새 사람이면 없음. */
  label?: string;
  error?: string;
}

export default function HoursField({ value, onChange, label, error }: Props) {
  const toggle = (d: number) => {
    const days = value?.days ?? [];
    const next = days.includes(d) ? days.filter((x) => x !== d) : [...days, d].sort((a, b) => a - b);
    onChange(next.length ? { start: value?.start ?? DEFAULT.start, end: value?.end ?? DEFAULT.end, days: next } : null);
  };
  const setTime = (key: 'start' | 'end', t: string) => value && onChange({ ...value, [key]: t });
  return (
    <fieldset className="ct-fieldset ct-field" aria-label="근무시간">
      <legend className="ct-label">근무시간</legend>
      <div className="ct-days">
        {DAYS.map((d, i) => (
          <button key={d} type="button" className="ct-day" aria-pressed={value?.days.includes(i) ?? false} onClick={() => toggle(i)}>
            {d}
          </button>
        ))}
      </div>
      {value ? (
        <div className="ct-times">
          <label className="ct-time">
            <span>시작</span>
            <input className="ct-input" type="time" value={value.start} onChange={(e) => setTime('start', e.target.value)} />
          </label>
          <label className="ct-time">
            <span>끝</span>
            <input className="ct-input" type="time" value={value.end} onChange={(e) => setTime('end', e.target.value)} />
          </label>
          <button type="button" className="ct-link" onClick={() => onChange(null)}>
            프로젝트 기본으로
          </button>
        </div>
      ) : (
        <p className="ct-hint">프로젝트 기본(일정 달력의 근무일 08:00~18:00) — 요일을 고르면 이 사람만 따로 정합니다.</p>
      )}
      {label && <p className="ct-hint">{`지금: ${label}`}</p>}
      {error && (
        <p className="ct-error" role="alert">
          {error}
        </p>
      )}
    </fieldset>
  );
}
