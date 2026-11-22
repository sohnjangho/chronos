// 탐색기(시안 「탐색기」의 일정 목록과 버전 패널): 위 경로·찾기 · 왼쪽 분류 · 가운데 일정 표 · 오른쪽 요약·버전.
import { useState, type KeyboardEvent } from 'react';
import { useCurrentSchedule } from '../../os/currentSchedule';
import { useSession } from '../../os/session';
import { useWindows } from '../../os/windowStore';
import ConfirmDialog from './ConfirmDialog';
import { dot, domainLabel, eulOf, levelLabel, stamp, type TreeSchedule } from './exApi';
import Tree from './Tree';
import { useExplorerData } from './useExplorerData';
import VersionPanel from './VersionPanel';
import './explorer.css';

type Ask = { kind: 'restore'; n: number } | { kind: 'delete' } | null;

function ScheduleTable({ rows, selected, onSelect }: { rows: TreeSchedule[]; selected: number | null; onSelect(id: number): void }) {
  const onKey = (e: KeyboardEvent, id: number) => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    e.preventDefault();
    onSelect(id);
  };
  return (
    <table className="ex-table" aria-label="일정 목록">
      <thead>
        <tr>
          <th>이름</th>
          <th className="ex-c-domain">분야</th>
          <th className="ex-c-level ex-opt">정밀도</th>
          <th className="ex-c-ver">버전</th>
          <th className="ex-c-date">완료</th>
          <th className="ex-c-date ex-opt">고친 때</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((s) => (
          <tr key={s.id} tabIndex={0} aria-current={s.id === selected ? 'true' : undefined} onClick={() => onSelect(s.id)} onKeyDown={(e) => onKey(e, s.id)}>
            <td>
              <span className="ex-name" title={s.name}>
                {s.name}
              </span>
            </td>
            <td title={domainLabel(s.domain)}>{domainLabel(s.domain)}</td>
            <td className="ex-opt" title={levelLabel(s.level)}>
              {levelLabel(s.level)}
            </td>
            <td>{s.version}</td>
            <td className={s.finish === null ? 'ex-muted-cell' : undefined}>{s.finish === null ? '계산 안 됨' : dot(s.finish)}</td>
            <td className="ex-opt">{stamp(s.updated_at)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** 위 줄: 작업 공간 › 일정 › 고른 것 · 새 프로젝트 · 이름으로 찾기. */
function Bar({ title, query, onQuery }: { title: string; query: string; onQuery(q: string): void }) {
  return (
    <div className="ex-bar">
      <span className="ex-crumb">작업 공간 › 일정 ›</span>
      <b className="ex-ellipsis" title={title}>
        {title}
      </b>
      <span className="ex-gap" />
      <button
        type="button"
        className="ex-new-btn"
        onClick={() => useCurrentSchedule.getState().openNewProjectModal('direct')}
      >
        + 새 프로젝트
      </button>
      <input type="search" className="ex-search" aria-label="이름으로 찾기" placeholder="이름으로 찾기" value={query} onChange={(e) => onQuery(e.target.value)} />
    </div>
  );
}

/** 되돌리기·지우기 전에 묻는 창 안 겹화면. */
function Question({ ask, name, busy, onConfirm, onCancel }: { ask: Ask; name: string | null; busy: boolean; onConfirm(): void; onCancel(): void }) {
  if (ask?.kind === 'restore') {
    return (
      <ConfirmDialog title="버전 되돌리기" confirm="되돌리기" busy={busy} onConfirm={onConfirm} onCancel={onCancel}>
        <p>{`버전 ${ask.n}의 내용으로 새 버전을 만듭니다. 지금까지의 버전은 모두 그대로 남아 다시 되돌릴 수 있습니다.`}</p>
      </ConfirmDialog>
    );
  }
  if (ask?.kind !== 'delete' || name === null) return null;
  return (
    <ConfirmDialog title="일정 지우기" confirm="지우기" danger busy={busy} onConfirm={onConfirm} onCancel={onCancel}>
      <p className="ex-wrap">{`「${name}」${eulOf(name)} 지웁니다. 모든 버전과 변경 이력이 함께 지워지고 되돌릴 수 없습니다.`}</p>
    </ConfirmDialog>
  );
}

/** OS 의 지금 일정으로 정하고 「스케줄」에서 연다. */
function openBoard(s: TreeSchedule) {
  useCurrentSchedule.getState().setCurrent({ id: s.id, name: s.name });
  useWindows.getState().open('schedule-table', { id: String(s.id) });
}

export default function Explorer() {
  const d = useExplorerData();
  const admin = useSession((s) => s.session?.user.role === 'admin');
  const [domain, setDomain] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [ask, setAsk] = useState<Ask>(null);
  const [busy, setBusy] = useState(false);
  const all = d.schedules ?? [];
  const q = query.trim().toLowerCase();
  const rows = all.filter((s) => (domain === null || s.domain === domain) && (!q || s.name.toLowerCase().includes(q)));

  async function confirm() {
    if (!ask) return;
    setBusy(true);
    await (ask.kind === 'restore' ? d.restore(ask.n) : d.remove());
    setBusy(false);
    setAsk(null);
  }

  return (
    <div className="ex-root">
      <Bar title={d.schedule?.name ?? (domain === null ? '전체' : domainLabel(domain))} query={query} onQuery={setQuery} />
      {d.notice && (
        <p className={`ex-notice is-${d.notice.tone}`} role={d.notice.tone === 'error' ? 'alert' : 'status'}>
          {d.notice.text}
        </p>
      )}
      <div className="ex-body">
        <Tree schedules={all} domain={domain} onDomain={setDomain} />
        <div className="ex-list">
          {d.schedules === null && <p className="ex-muted">불러오는 중…</p>}
          {d.schedules !== null && rows.length === 0 && <p className="ex-muted">{all.length === 0 ? '아직 저장한 일정이 없습니다.' : '찾는 이름의 일정이 없습니다.'}</p>}
          {rows.length > 0 && <ScheduleTable rows={rows} selected={d.schedule?.id ?? null} onSelect={d.select} />}
        </div>
        <VersionPanel
          schedule={d.schedule}
          view={d.view}
          versions={d.versions}
          versionsError={d.versionsError}
          onRetry={d.retry}
          admin={admin}
          onOpen={() => d.schedule && openBoard(d.schedule)}
          onDelete={() => setAsk({ kind: 'delete' })}
          onRestore={(n) => setAsk({ kind: 'restore', n })}
        />
      </div>
      <Question ask={ask} name={d.schedule?.name ?? null} busy={busy} onConfirm={() => void confirm()} onCancel={() => setAsk(null)} />
    </div>
  );
}
