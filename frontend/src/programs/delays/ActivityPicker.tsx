// 대상 액티비티 고르기(화면 검수 2): WBS 묶음으로 나눈 목록 + 찾기(id·이름·묶음 이름). 목록은 정해진 높이 안에서 스크롤한다.
import { useState } from 'react';
import type { Activity, ScheduleView } from '../../shared/schedule/scheduleApi';

interface Props {
  view: ScheduleView | null;
  viewError: string | null;
  value: string;
  onChange: (aid: string) => void;
  /** 반영된 사건: 대상은 고칠 수 없다(고른 것만 보인다). */
  disabled?: boolean;
  error?: string;
}

interface Group {
  code: string;
  name: string;
  items: Activity[];
}

/** WBS 차례대로 묶는다. 모르는 묶음의 액티비티는 맨 뒤 「WBS 없음」. */
function groupsOf(view: ScheduleView, query: string): Group[] {
  const q = query.trim().toLowerCase();
  const names = new Map(view.wbs.map((w) => [w.code, w.name]));
  const groups: Group[] = view.wbs.map((w) => ({ code: w.code, name: w.name, items: [] }));
  const rest: Group = { code: '', name: 'WBS 없음', items: [] };
  for (const a of view.activities) {
    const wbsName = names.get(a.wbs) ?? '';
    if (q && ![a.id, a.name, wbsName].some((s) => s.toLowerCase().includes(q))) continue;
    (groups.find((g) => g.code === a.wbs) ?? rest).items.push(a);
  }
  return [...groups, rest].filter((g) => g.items.length > 0);
}

function Chosen({ view, value }: { view: ScheduleView | null; value: string }) {
  const name = view?.activities.find((a) => a.id === value)?.name;
  return <span className="dl-pick-chosen">{value ? `${value}${name ? ` ${name}` : ''}` : '고르지 않음'}</span>;
}

export default function ActivityPicker({ view, viewError, value, onChange, disabled, error }: Props) {
  const [query, setQuery] = useState('');
  const groups = view ? groupsOf(view, query) : [];
  return (
    <div className="dl-pick">
      <div className="dl-pick-head">
        <span className="dl-label">대상 액티비티</span>
        <Chosen view={view} value={value} />
      </div>
      {!disabled && (
        <>
          <input
            className="dl-input"
            type="search"
            placeholder="액티비티 찾기"
            aria-label="액티비티 찾기"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div role="listbox" aria-label="대상 액티비티" className="dl-pick-list">
            {!view && <p className="dl-muted">{viewError ? `일정을 읽을 수 없습니다: ${viewError}` : '일정을 읽는 중…'}</p>}
            {view && groups.length === 0 && <p className="dl-muted">맞는 액티비티 없음</p>}
            {groups.map((g) => (
              <div role="group" aria-label={g.name} key={g.code || '-'}>
                <div className="dl-pick-group" aria-hidden="true">{`${g.code ? `${g.code} ` : ''}${g.name}`}</div>
                {g.items.map((a) => (
                  <button
                    key={a.id}
                    type="button"
                    role="option"
                    aria-selected={a.id === value}
                    className="dl-pick-item"
                    onClick={() => onChange(a.id)}
                  >
                    <span className="dl-pick-id">{a.id}</span>
                    <span className="dl-pick-name">{a.name}</span>
                  </button>
                ))}
              </div>
            ))}
          </div>
        </>
      )}
      {error && <span className="dl-error">{error}</span>}
    </div>
  );
}
