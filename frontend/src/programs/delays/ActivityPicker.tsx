// 대상 액티비티 고르기(화면 검수 2): WBS 묶음으로 나눈 목록 + 찾기(id·이름·묶음 이름). 목록은 정해진 높이 안에서 스크롤한다.
// 키보드: 찾기 칸에서 ↓ 로 목록에 들어가고, 목록 안에서 ↑↓·Home·End 로 옮기고 Enter·Space 로 고른다(목록은 Tab 한 번).
import { useId, useRef, useState, type KeyboardEvent, type RefObject } from 'react';
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

/** 목록 안 단추 사이를 ↑↓·Home·End 로 옮긴다. */
function moveFocus(list: HTMLElement | null, key: string, from: Element | null): boolean {
  const items = [...(list?.querySelectorAll<HTMLButtonElement>('[role="option"]') ?? [])];
  if (items.length === 0) return false;
  const at = items.indexOf(from as HTMLButtonElement);
  const next = { ArrowDown: Math.min(at + 1, items.length - 1), ArrowUp: Math.max(at - 1, 0), Home: 0, End: items.length - 1 }[key];
  if (next === undefined) return false;
  items[next].focus();
  return true;
}

function Options({ groups, value, onChange, listRef }: { groups: Group[]; value: string; onChange: (aid: string) => void; listRef: RefObject<HTMLDivElement | null> }) {
  const first = groups[0]?.items[0]?.id;
  const tabStop = groups.some((g) => g.items.some((a) => a.id === value)) ? value : first;
  return groups.map((g) => (
    <div role="group" aria-label={g.name} key={g.code || '-'}>
      <div className="dl-pick-group" aria-hidden="true">{`${g.code ? `${g.code} ` : ''}${g.name}`}</div>
      {g.items.map((a) => (
        <button
          key={a.id}
          type="button"
          role="option"
          aria-selected={a.id === value}
          tabIndex={a.id === tabStop ? 0 : -1}
          className="dl-pick-item"
          onClick={() => onChange(a.id)}
          onKeyDown={(e) => moveFocus(listRef.current, e.key, e.currentTarget) && e.preventDefault()}
        >
          <span className="dl-pick-id">{a.id}</span>
          <span className="dl-pick-name">{a.name}</span>
        </button>
      ))}
    </div>
  ));
}

export default function ActivityPicker({ view, viewError, value, onChange, disabled, error }: Props) {
  const [query, setQuery] = useState('');
  const listRef = useRef<HTMLDivElement>(null);
  const errorId = useId();
  const describedBy = error ? errorId : undefined;
  const groups = view ? groupsOf(view, query) : [];
  const fromSearch = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown' && moveFocus(listRef.current, 'Home', null)) e.preventDefault();
  };
  const empty = !view ? (viewError ? `일정을 읽을 수 없습니다: ${viewError}` : '일정을 읽는 중…') : groups.length === 0 ? '맞는 액티비티 없음' : null;
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
            aria-describedby={describedBy}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={fromSearch}
          />
          <div className="dl-pick-list">
            {empty && <p className="dl-muted">{empty}</p>}
            <div role="listbox" aria-label="대상 액티비티" aria-describedby={describedBy} ref={listRef}>
              <Options groups={groups} value={value} onChange={onChange} listRef={listRef} />
            </div>
          </div>
        </>
      )}
      {error && (
        <span className="dl-error" id={errorId}>
          {error}
        </span>
      )}
    </div>
  );
}
