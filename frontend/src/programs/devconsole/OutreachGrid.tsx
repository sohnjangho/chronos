// 하네스 탭의 「연락 하네스」 묶음(Task 98): 설계 표 그대로의 상황 격자(S-01…S-24 × 네 열) + 채널에만 있는 것 · 원칙 · 운영 상한.
// 칸은 서버가 모래상자 자식 프로세스에서 진짜 문·도구·뒤 확인으로 돌린다(기존 차단 시험 길). [가드 끄고 돌리기]는 지키는 곳 하나를 자식 안에서만
// 무른다 — 무르니 실패하면 「가드 확인됨」, 물러도 통과하면 붉은 「가드 확인 안 됨」. 칸 말(가짜에서만·하네스 갈라짐…)은 칸에 붙인다.
// 운영 상한은 설정과 같은 공용 LimitsForm(알림 연결 API) — 콘솔에 사본은 없다. 전부 돌리기는 한 번에 한 칸씩 차례로.
import { useRef, useState } from 'react';
import { ApiError } from '../../shared/api';
import LimitsForm from '../../shared/outreach/LimitsForm';
import Badge from '../../shared/ui/Badge';
import { devApi, type GridCase, type GridCell, type GridRow, type GridNoteKind, type HarnessTestOut, type OutreachGridOut } from './devApi';
import RawBlock from './RawBlock';
import './outreachGrid.css';

const NOTE: Record<GridNoteKind, [string, string]> = {
  simulated: ['가짜에서만', 'is-warn'],
  diverged: ['하네스 갈라짐', 'is-danger'],
  common_only: ['공통 겹만', 'is-info'],
  design_diff: ['설계와 다름', 'is-info'],
};
const MEDIUM: Record<string, string> = { call: '통화', sms: '문자', kakao: '카카오톡' };
const markText = (mark: string) => (mark === 'run' ? '●' : mark === 'none' ? '—' : mark);

interface Outcome { run?: HarnessTestOut; broken?: HarnessTestOut; error?: string; busy?: boolean }
type Results = Record<string, Outcome>;

const failText = (e: unknown) => (e instanceof ApiError ? e.message : '돌리지 못했습니다.');

function NoteTag({ cell }: { cell: GridCell }) {
  if (!cell.note || !cell.note_kind) return null;
  const [label, tone] = NOTE[cell.note_kind];
  return <span className={`dc-tag ${tone}`} title={cell.note}>{label}</span>;
}

interface CellProps {
  id: string;
  label: string;
  cell: GridCell;
  outcome: Outcome | undefined;
  locked: boolean;
  onRun(id: string, broken: boolean): void;
  onPick(id: string): void;
}

function Cell({ id, label, cell, outcome, locked, onRun, onPick }: CellProps) {
  const run = outcome?.run;
  const broken = outcome?.broken;
  return (
    <div className="dc-og-cell" role="group" aria-label={label}>
      <span className="dc-og-mark">{markText(cell.mark)}</span>
      {cell.runnable && (
        <>
          {outcome?.busy ? (
            <span className="dc-og-res">도는 중…</span>
          ) : run ? (
            <button type="button" className={`dc-og-res ${run.passed ? 'is-pass' : 'is-fail'}`} onClick={() => onPick(id)}>
              {run.passed ? '통과' : '실패'}
            </button>
          ) : outcome?.error ? (
            <span className="dc-og-res is-fail" title={outcome.error}>오류</span>
          ) : (
            <span className="dc-og-res is-todo">아직 안 돌림</span>
          )}
          {broken && (
            <button type="button" className={`dc-og-res ${broken.guard_confirmed ? 'is-pass' : 'is-fail'}`} onClick={() => onPick(id)}
              title={`무른 곳: ${broken.broken_guard ?? ''}`}>
              {broken.guard_confirmed ? '가드 확인됨' : '가드 확인 안 됨'}
            </button>
          )}
          <NoteTag cell={cell} />
          <span className="dc-og-acts">
            <button type="button" className="dc-btn" disabled={locked} onClick={() => onRun(id, false)}>돌리기</button>
            {cell.guard && (
              <button type="button" className="dc-btn" disabled={locked} onClick={() => onRun(id, true)} title={`지키는 곳: ${cell.guard}`}>
                가드 끄고 돌리기
              </button>
            )}
          </span>
        </>
      )}
    </div>
  );
}

function ResultPanel({ id, outcome }: { id: string; outcome: Outcome }) {
  const shown = [outcome.run, outcome.broken].filter((r): r is HarnessTestOut => !!r);
  return (
    <section className="dc-og-result" aria-label={`${id} 결과`}>
      {shown.map((r) => (
        <div key={r.broken_guard ? 'broken' : 'run'} className="dc-og-result-one">
          <div className="dc-harness-test-head">
            <b>{r.broken_guard ? `${id} — 가드 「${r.broken_guard}」 끄고` : id}</b>
            {r.broken_guard ? (
              <Badge tone={r.guard_confirmed ? 'success' : 'danger'}>{r.guard_confirmed ? '가드 확인됨 — 무르니 실패함' : '가드 확인 안 됨 — 물러도 통과'}</Badge>
            ) : (
              <Badge tone={r.passed ? 'success' : 'danger'}>{r.passed ? '통과' : '실패'}</Badge>
            )}
            {r.engine === 'live_harness' && <Badge tone="success">실엔진 검증</Badge>}
            {r.elapsed_ms !== undefined && <Badge tone="neutral">{`${r.elapsed_ms}ms`}</Badge>}
          </div>
          <p className="dc-muted">{r.simulated_input}</p>
          {r.note && <p className="dc-og-note" role="note">{r.note}</p>}
          <ul className="dc-og-checks" aria-label="기대">
            {(r.checks ?? []).map((c, i) => (
              <li key={i} className={c.ok ? 'is-ok' : 'is-bad'}>
                <span aria-hidden>{c.ok ? '✓' : '✗'}</span> {c.text}
                {c.guarded && <span className="dc-tag">지키는 곳 기대</span>}
              </li>
            ))}
          </ul>
          <ul className="dc-og-events" aria-label="하네스 사건">
            {(r.events ?? []).map((e, i) => (
              <li key={i}>
                <span className="dc-og-group">{e.group_label}</span> <code>{e.rule}</code>
                <span className={`dc-tag${e.verdict === 'blocked' ? ' is-danger' : e.verdict === 'noted' ? ' is-warn' : ''}`}>{e.verdict}</span>
              </li>
            ))}
          </ul>
          <RawBlock label="기계 출력" value={r} />
        </div>
      ))}
      {outcome.error && <p className="dc-error" role="alert">{outcome.error}</p>}
    </section>
  );
}

function Limits({ grid }: { grid: OutreachGridOut }) {
  return (
    <section className="dc-og-limits" aria-label="운영 상한">
      <details open>
        <summary><b>운영 상한</b> <span className="dc-muted">— 설정 「알림 연결」과 같은 칸·같은 저장소</span></summary>
        <p className="dc-muted">{grid.limits_note}</p>
        {grid.connection_id === null ? (
          <p className="dc-muted">기본 알림 연결이 없어 상한을 볼 수 없습니다(설정 → 알림 연결).</p>
        ) : (
          <LimitsForm connectionId={grid.connection_id} />
        )}
      </details>
    </section>
  );
}

interface TableProps {
  grid: OutreachGridOut;
  results: Results;
  locked: boolean;
  onRun(id: string, broken: boolean): void;
  onPick(id: string): void;
}

function SituationTable({ grid, rows, results, locked, onRun, onPick, onRow }: TableProps & { rows: GridRow[]; onRow(ids: string[]): void }) {
  return (
    <div className="dc-og-scroll">
      <table className="dc-cat-table dc-og-table" aria-label="연락 하네스 격자">
        <thead>
          <tr>
            {['번호', '상황', ...grid.columns.map((c) => c.label), '줄'].map((h) => <th key={h} scope="col">{h}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className="dc-cat-row" aria-label={`${r.id} ${r.title}`}>
              <td className="dc-cat-id"><b>{r.id}</b></td>
              <td className="dc-og-title">
                {r.title}
                {r.refs.length > 0 && <small className="dc-muted">{r.refs.join(' · ')}</small>}
              </td>
              {grid.columns.map((c) => (
                <td key={c.key}>
                  <Cell id={`${r.id}@${c.key}`} label={`${r.id} ${c.label}`} cell={r.cells[c.key]} outcome={results[`${r.id}@${c.key}`]}
                    locked={locked} onRun={onRun} onPick={onPick} />
                </td>
              ))}
              <td className="dc-cat-act">
                <button type="button" className="dc-btn" disabled={locked}
                  onClick={() => onRow(grid.columns.filter((c) => r.cells[c.key]?.runnable).map((c) => `${r.id}@${c.key}`))}>
                  줄 전체 돌리기
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CaseTable({ grid, cases, results, locked, onRun, onPick }: TableProps & { cases: GridCase[] }) {
  const label = (key: string) => grid.columns.find((c) => c.key === key)?.label ?? key;
  return (
    <div className="dc-og-scroll">
      <table className="dc-cat-table dc-og-table" aria-label="채널에만 있는 것">
        <thead>
          <tr>
            {['번호', '채널', '경우', '도는 열', '결과'].map((h) => <th key={h} scope="col">{h}</th>)}
          </tr>
        </thead>
        <tbody>
          {cases.map((c) => (
            <tr key={c.id} className="dc-cat-row">
              <td className="dc-cat-id"><b>{c.id}</b></td>
              <td><span className="dc-tag">{MEDIUM[c.medium] ?? c.medium}</span></td>
              <td className="dc-og-title">
                {c.title}
                {c.refs.length > 0 && <small className="dc-muted">{c.refs.join(' · ')}</small>}
              </td>
              <td className="dc-muted">{label(c.column)}</td>
              <td>
                <Cell id={c.id} label={`${c.id} ${c.title}`} cell={c} outcome={results[c.id]} locked={locked} onRun={onRun} onPick={onPick} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const matchRow = (q: string, texts: string[]) => !q || texts.some((t) => t.toLowerCase().includes(q));

export default function OutreachGrid({ grid, query = '' }: { grid: OutreachGridOut; query?: string }) {
  const [results, setResults] = useState<Results>({});
  const [picked, setPicked] = useState<string | null>(null);
  const [running, setRunning] = useState<{ done: number; total: number } | null>(null);
  const stop = useRef(false);
  const q = query.trim().toLowerCase();
  const rows = grid.rows.filter((r) => matchRow(q, [r.id, r.title, ...r.refs]));
  const cases = grid.channel_only.filter((c) => matchRow(q, [c.id, c.title, c.case, ...c.refs]));
  const allIds = [
    ...grid.rows.flatMap((r) => grid.columns.filter((c) => r.cells[c.key]?.runnable).map((c) => `${r.id}@${c.key}`)),
    ...grid.channel_only.map((c) => c.id),
  ];

  async function runOne(id: string, broken: boolean) {
    setResults((p) => ({ ...p, [id]: { ...p[id], busy: true, error: undefined } }));
    try {
      const res = await devApi.testHarness(id, broken);
      setResults((p) => ({ ...p, [id]: { ...p[id], busy: false, [broken ? 'broken' : 'run']: res } }));
    } catch (e) {
      setResults((p) => ({ ...p, [id]: { ...p[id], busy: false, error: failText(e) } }));
    }
    setPicked(id);
  }

  async function runMany(ids: string[]) {
    stop.current = false;
    setRunning({ done: 0, total: ids.length });
    for (const [i, id] of ids.entries()) {
      if (stop.current) break;
      await runOne(id, false); // 한 번에 한 칸 — 서버도 자식 수를 묶는다
      setRunning({ done: i + 1, total: ids.length });
    }
    setRunning(null);
  }

  const outcomes = allIds.map((id) => results[id]?.run);
  const passed = outcomes.filter((r) => r?.passed === true).length;
  const failed = outcomes.filter((r) => r && !r.passed).length;
  const confirmed = allIds.filter((id) => results[id]?.broken?.guard_confirmed === true).length;
  const loose = allIds.filter((id) => results[id]?.broken && !results[id]?.broken?.guard_confirmed).length;
  const locked = running !== null;
  const table = { grid, results, locked, onRun: (id: string, b: boolean) => void runOne(id, b), onPick: setPicked };

  return (
    <section className="dc-og" aria-label="연락 하네스">
      <div className="dc-cat-header">
        <h3 className="dc-cat-h3">{`${grid.group} — 상황 격자`}</h3>
        <p className="dc-muted">
          상황 대본 하나를 네 길(전화 걸기 · 전화 받기 · 문자 받기 · 우리 글에 온 답)로 돌립니다. 칸마다 서버 밖 모래상자 자식 프로세스(임시 DB · 가짜 통로·음성·글
          세션·LLM)에서 진짜 문·도구·뒤 확인·받기 판정이 돕니다. PM 자료는 건드리지 않습니다.
        </p>
      </div>
      <details className="dc-principles-box">
        <summary><b>원칙 — 한 벌로 두는 것</b></summary>
        <ul>
          {grid.principles.map((p) => <li key={p}>{p}</li>)}
        </ul>
      </details>
      <Limits grid={grid} />
      {grid.error ? (
        <p className="dc-error" role="alert">{grid.error}</p>
      ) : (
        <>
          <div className="dc-og-bar">
            <button type="button" className="dc-btn dc-btn-primary" disabled={locked} onClick={() => void runMany(allIds)}>전부 돌리기</button>
            {locked && <button type="button" className="dc-btn" onClick={() => void (stop.current = true)}>멈추기</button>}
            <span role="status" aria-label="격자 진행" className="dc-og-sum">
              {running && `${running.done} / ${running.total} 돌림 · `}
              {`통과 ${passed} · 실패 ${failed} · 아직 안 돌림 ${allIds.length - passed - failed}`}
              {confirmed + loose > 0 && ` · 가드 확인됨 ${confirmed}${loose ? ` · 가드 확인 안 됨 ${loose}` : ''}`}
            </span>
          </div>
          <SituationTable {...table} rows={rows} onRow={(ids) => void runMany(ids)} />
          <CaseTable {...table} cases={cases} />
          {picked && results[picked] && !results[picked].busy && <ResultPanel id={picked} outcome={results[picked]} />}
        </>
      )}
    </section>
  );
}
