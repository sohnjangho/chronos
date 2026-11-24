// 시스템 진단(시안 A)의 줄 조각: 「먼저 볼 것」 줄 · 영역 묶음 줄 · 펼친 자세히(지금 상태 · 영향 · 기계 출력 · 저장된 진단 걸음) · 실행 중 턴 줄.
import Badge, { type Tone } from '../../shared/ui/Badge';
import type { HealthOut, NotifyDiagnosis, NotifyStep } from './devApi';
import { type Check, type CheckState, stateLabel, when } from './healthChecks';
import RawBlock from './RawBlock';

export const TONE: Record<CheckState | 'info', Tone> = { ok: 'success', check: 'warning', fail: 'danger', unknown: 'neutral', info: 'info' };
const OUTCOME: Record<NotifyStep['outcome'], [string, Tone]> = {
  ok: ['정상', 'success'],
  failed: ['실패', 'danger'],
  check: ['확인 필요', 'warning'],
  skipped: ['건너뜀', 'neutral'],
};

export const timeOf = (d: Date) => d.toLocaleTimeString('ko-KR', { hour: 'numeric', minute: '2-digit' });

/** 마지막 확인: 오늘이면 「오후 2:46」, 아니면 날짜를 앞에. */
function LastChecked({ c, now }: { c: Check; now: Date }) {
  const { at, server } = c.checkedAt;
  if (!at) return <span className="dc-hl-when" title="아직 확인한 적 없음">—</span>;
  const d = new Date(at);
  if (Number.isNaN(d.getTime())) return <span className="dc-hl-when" title="때를 읽을 수 없음">—</span>;
  const same = d.toDateString() === now.toDateString();
  const text = same ? timeOf(d) : `${d.getMonth() + 1}. ${d.getDate()}. ${timeOf(d)}`;
  return (
    <span className="dc-hl-when" title={`${server ? '서버가 적은 마지막 확인' : '진단을 부른 때'} ${when(at)}`}>
      {text}
    </span>
  );
}

export const Dot = ({ state }: { state: CheckState | 'info' }) => <span className={`dc-hl-dot is-${state}`} aria-hidden="true" />;

function StateBadge({ state, open }: { state: CheckState | 'info'; open?: boolean }) {
  return (
    <Badge tone={TONE[state]} className={state === 'unknown' ? 'dc-hl-unknown' : undefined}>
      {`${stateLabel(state)}${open === undefined ? '' : open ? ' ▾' : ' ▸'}`}
    </Badge>
  );
}

const Name = ({ c }: { c: Check }) => (
  <span className="dc-hl-name dc-ellipsis" title={c.tech ? `${c.name} (${c.tech})` : c.name}>
    {c.name}
    {c.tech && <span className="dc-hl-tech">{c.tech}</span>}
  </span>
);

/** 저장된 마지막 진단의 걸음 줄(문자 연결 · AI 전화 — 다시 돌리지 않는다). 코드는 접힌 기계 출력으로. */
function Diagnosis({ diag, title }: { diag: NotifyDiagnosis; title: string }) {
  return (
    <section className="dc-o-diag">
      <h4>{`${title} · ${when(diag.ran_at)}${diag.state === 'sending' ? ' · 도는 중이거나 끝나지 않음(확인 필요)' : ''}`}</h4>
      <ul className="dc-health-list" aria-label={title}>
        {diag.steps.map((s) => {
          const [label, tone] = OUTCOME[s.outcome];
          return (
            <li key={s.id}>
              <span className="dc-ellipsis" title={s.label}>
                <b>{s.id}</b> {s.label}
              </span>
              <Badge tone={tone}>{label}</Badge>
              <span className="dc-muted dc-o-detail">{s.detail}</span>
            </li>
          );
        })}
      </ul>
      <RawBlock label="걸음 코드" value={Object.fromEntries(diag.steps.map((s) => [s.id, { code: s.code, maybe_sent: s.maybe_sent, pending: s.pending }]))} />
    </section>
  );
}

/** 펼친 줄: 지금 상태 · 영향(할 일) · 기계 출력, 저장된 진단 걸음은 그 아래. */
function Detail({ c }: { c: Check }) {
  return (
    <div className="dc-hl-detail" role="region" aria-label={`${c.name} 자세히`}>
      <div className="dc-hl-cols">
        <div className="dc-hl-col">
          <h4>지금 상태</h4>
          {c.fields.length === 0 && <p className="dc-muted">{c.summary}</p>}
          {c.fields.map((g) => (
            <div key={g.title} className="dc-hl-kvgroup">
              {c.fields.length > 1 && <h5>{g.title}</h5>}
              <dl className="dc-hl-kv" role="group" aria-label={g.title}>
                {g.rows.map(([k, v]) => (
                  <div key={k}>
                    <dt>{k}</dt>
                    <dd>{v}</dd>
                  </div>
                ))}
              </dl>
            </div>
          ))}
        </div>
        <div className="dc-hl-col">
          <h4>영향</h4>
          <p className="dc-muted">{c.impact}</p>
          {c.todo && (
            <p className="dc-hl-todo">
              <b>할 일</b> {c.todo}
            </p>
          )}
          {c.note && (
            <p className="dc-muted" role="note">
              {c.note}
            </p>
          )}
        </div>
        <div className="dc-hl-col">
          <RawBlock label="기계 출력" value={c.raw} />
        </div>
      </div>
      {c.steps && <Diagnosis diag={c.steps.diag} title={c.steps.title} />}
    </div>
  );
}

/** 「먼저 볼 것」 한 줄: 점 · 이름 · 한 줄 요약 · 할 일 · 상태. */
export function PinnedRow({ c, open, onToggle }: { c: Check; open: boolean; onToggle(): void }) {
  return (
    <li className={`dc-hl-item${open ? ' is-open' : ''}`}>
      <button type="button" className="dc-hl-prow" aria-expanded={open} aria-label={`${c.name} — ${stateLabel(c.state)}`} onClick={onToggle}>
        <Dot state={c.state} />
        <Name c={c} />
        <span className="dc-hl-sum">{c.summary}</span>
        <span className="dc-hl-todo">
          <b>할 일</b> {c.todo ?? '—'}
        </span>
        <StateBadge state={c.state} open={open} />
      </button>
      {open && <Detail c={c} />}
    </li>
  );
}

/** 영역 묶음 한 줄: 점 · 이름 · 한 줄 요약 · 마지막 확인 · ▸. */
export function GroupRow({ c, open, onToggle, now }: { c: Check; open: boolean; onToggle(): void; now: Date }) {
  return (
    <li className={`dc-hl-item${open ? ' is-open' : ''}`}>
      <button type="button" className="dc-hl-row" aria-expanded={open} aria-label={`${c.name} — ${stateLabel(c.state)}`} onClick={onToggle}>
        <Dot state={c.state} />
        <Name c={c} />
        <span className="dc-hl-sum dc-ellipsis" title={c.summary}>
          {c.summary}
        </span>
        <LastChecked c={c} now={now} />
        <span className="dc-hl-chev" aria-hidden="true">
          {open ? '▾' : '▸'}
        </span>
      </button>
      {open && <Detail c={c} />}
    </li>
  );
}

/** 실행 중인 에이전트 턴: 턴마다 제목과 [강제 중단](이미 보냈으면 「중단 신호 보냄」). */
export function TurnsRow({ turns, stoppingId, onStop }: { turns: HealthOut['active_turns']; stoppingId: number | null; onStop(id: number): void }) {
  return (
    <li className="dc-hl-item">
      <div className="dc-hl-row is-turns">
        <Dot state="info" />
        <span className="dc-hl-name">실행 중인 에이전트 턴</span>
        {turns.length === 0 ? (
          <span className="dc-hl-sum">지금 실행 중인 턴이 없습니다</span>
        ) : (
          <ul className="dc-hl-turns" aria-label="실행 중 턴 목록">
            {turns.map((t) => (
              <li key={t.chat_session_id}>
                <code>{`#${t.chat_session_id}`}</code>
                <span className="dc-ellipsis" title={t.title}>
                  {t.title}
                </span>
                {t.stop_requested ? (
                  <Badge tone="warning">중단 신호 보냄</Badge>
                ) : (
                  <button type="button" className="dc-btn" disabled={stoppingId === t.chat_session_id} onClick={() => onStop(t.chat_session_id)}>
                    {stoppingId === t.chat_session_id ? '중단 중…' : '강제 중단'}
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </li>
  );
}
