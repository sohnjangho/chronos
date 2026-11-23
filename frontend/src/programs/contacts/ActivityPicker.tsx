// 입력창의 「연결할 작업: … ▾」(Task 79). 이 창의 일정(scheduleId) 작업만, WBS 별로 묶고 이름·번호로 찾는다(긴 목록 규칙).
// 목록은 기존 일정 API(getSchedule)로 — 넘겨받은 작업이 있으면 곧바로, 없으면 처음 펼칠 때 읽는다. 넘겨받은 작업이 이 일정에 없으면
// 연결하지 않고 그렇게 말한다(보내면 서버가 404 「작업을 찾을 수 없습니다.」로 막을 것을 미리). 단추의 긴 이름은 잘리고 title·펼친
// 목록(줄을 바꿔 전부 보임)에서 읽는다. 목록은 입력창 안에서 펼쳐진다(창 밖으로 띄우지 않아 잘리거나 넘치지 않는다).
// 건반: 찾기 칸에서 ↓ 로 목록, 줄에서 ↑↓ · Enter/Space 로 고름 · Tab 으로도 줄마다 간다 · Esc 로 닫고 단추로 돌아감.
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { getSchedule, type Activity } from '../../shared/schedule/scheduleApi';

interface Props {
  scheduleId: number;
  /** 연결한 작업 id(없으면 null) */
  value: string | null;
  onChange(id: string | null): void;
  disabled?: boolean;
}

interface Group {
  key: string;
  label: string;
  items: Activity[];
}

/** 작업들을 WBS 별로(처음 나온 차례). 묶음 이름은 「코드 이름」. */
function groupByWbs(activities: Activity[], wbs: { code: string; name: string }[]): Group[] {
  const names = new Map(wbs.map((w) => [w.code, w.name]));
  const groups = new Map<string, Group>();
  for (const a of activities) {
    const key = a.wbs || '';
    if (!groups.has(key)) groups.set(key, { key, label: key ? `${key} ${names.get(key) ?? ''}`.trim() : '분류 없음', items: [] });
    groups.get(key)!.items.push(a);
  }
  return [...groups.values()];
}

/** wanted 가 처음 참이 될 때 그 일정의 작업을 읽는다. 실패하면 retry() 뒤 다시 읽는다. */
function useActivityGroups(scheduleId: number, wanted: boolean) {
  const [groups, setGroups] = useState<Group[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const need = wanted && groups === null && error === null;
  useEffect(() => {
    if (!need) return;
    let live = true;
    getSchedule(scheduleId).then(
      (v) => {
        if (live) setGroups(groupByWbs(v.activities ?? [], v.wbs ?? []));
      },
      (e: unknown) => {
        if (live) setError(e instanceof Error && e.message ? e.message : '작업 목록을 읽지 못했습니다.');
      },
    );
    return () => {
      live = false;
    };
  }, [need, scheduleId]);
  return { groups, error, retry: () => setError(null) };
}

interface PanelProps {
  id: string;
  groups: Group[] | null;
  error: string | null;
  value: string | null;
  onChoose(id: string | null): void;
  onClose(): void;
}

/** 펼친 판: 찾기 칸 + 「연결 안 함」 + WBS 묶음별 작업 줄. */
function PickerPanel({ id, groups, error, value, onChoose, onClose }: PanelProps) {
  const [query, setQuery] = useState('');
  const panel = useRef<HTMLDivElement>(null);
  const q = query.trim().toLowerCase();
  const shown = useMemo(
    () =>
      (groups ?? [])
        .map((g) => ({ ...g, items: g.items.filter((a) => !q || `${a.id} ${a.name} ${g.label}`.toLowerCase().includes(q)) }))
        .filter((g) => g.items.length > 0),
    [groups, q],
  );
  const move = (from: HTMLElement | null, step: number) => {
    const list = [...(panel.current?.querySelectorAll<HTMLElement>('[role="option"]') ?? [])];
    const i = from ? list.indexOf(from) : -1;
    list[Math.max(0, Math.min(list.length - 1, i + step))]?.focus();
  };
  const keys = (choice: string | null) => (e: KeyboardEvent<HTMLElement>) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onChoose(choice);
    } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      move(e.currentTarget, e.key === 'ArrowDown' ? 1 : -1);
    }
  };
  const option = (choice: string | null, body: ReactNode) => (
    <div
      key={choice ?? ''}
      role="option"
      tabIndex={0}
      aria-selected={value === choice}
      className={`cmp-opt${value === choice ? ' is-on' : ''}`}
      onClick={() => onChoose(choice)}
      onKeyDown={keys(choice)}
    >
      {body}
    </div>
  );
  const total = groups?.reduce((n, g) => n + g.items.length, 0) ?? 0;

  return (
    <div
      ref={panel}
      className="cmp-pick-panel"
      onKeyDown={(e) => {
        if (e.key !== 'Escape') return;
        e.preventDefault();
        e.stopPropagation();
        onClose();
      }}
    >
      <input
        type="search"
        className="ct-input"
        aria-label="작업 찾기"
        placeholder="작업 이름이나 번호로 찾기"
        value={query}
        autoFocus
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={(e) => {
          if (e.key !== 'ArrowDown') return;
          e.preventDefault();
          move(null, 0);
        }}
      />
      {error ? (
        <p role="alert" className="ct-error cmp-pick-msg">{error}</p>
      ) : groups === null ? (
        <p className="ct-muted cmp-pick-msg">작업 목록을 읽는 중…</p>
      ) : (
        <div role="listbox" id={id} aria-label="연결할 작업" className="cmp-pick-list">
          {!q && option(null, <span className="cmp-opt-name">연결 안 함</span>)}
          {shown.map((g) => (
            <div role="group" aria-label={g.label} key={g.key}>
              <div className="cmp-pick-head" aria-hidden="true">{`${g.label} · ${g.items.length}개`}</div>
              {g.items.map((a) => option(a.id, <><span className="cmp-opt-id">{a.id}</span><span className="cmp-opt-name">{a.name}</span></>))}
            </div>
          ))}
          {shown.length === 0 && <p className="ct-muted cmp-pick-msg">{total === 0 ? '이 일정에 작업이 없습니다.' : '찾는 작업이 없습니다.'}</p>}
        </div>
      )}
    </div>
  );
}

export default function ActivityPicker({ scheduleId, value, onChange, disabled }: Props) {
  const [open, setOpen] = useState(false);
  const [missing, setMissing] = useState<string | null>(null);
  const button = useRef<HTMLButtonElement>(null);
  const listId = useId();
  const { groups, error, retry } = useActivityGroups(scheduleId, open || value !== null);
  const chosen = value === null ? null : (groups?.flatMap((g) => g.items).find((a) => a.id === value) ?? null);

  // 넘겨받은 작업이 이 일정에 없음 → 연결하지 않는다.
  useEffect(() => {
    if (groups && value !== null && !chosen) {
      setMissing(value);
      onChange(null);
    }
  }, [groups, value, chosen, onChange]);

  const close = () => {
    setOpen(false);
    button.current?.focus();
  };
  const choose = (id: string | null) => {
    setMissing(null);
    onChange(id);
    close();
  };
  const full = chosen ? `${chosen.id} ${chosen.name}` : null;

  return (
    <div className="cmp-pick">
      <button
        ref={button}
        type="button"
        className="cmp-pick-btn"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        title={full ?? undefined}
        disabled={disabled}
        onClick={() => {
          if (open) return close();
          retry();
          setOpen(true);
        }}
      >
        <span className="cmp-pick-text">{`연결할 작업: ${full ?? value ?? '없음'}`}</span>
        <span aria-hidden="true" className="cmp-pick-caret">▾</span>
      </button>
      {missing && <span className="cmp-pick-note">{`넘겨받은 작업 ${missing} 을(를) 이 일정에서 찾지 못해 연결하지 않았습니다.`}</span>}
      {open && <PickerPanel id={listId} groups={groups} error={error} value={value} onChoose={choose} onClose={close} />}
    </div>
  );
}
