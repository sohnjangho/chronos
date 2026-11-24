// 연락 하네스 격자(Task 98) 칸 하나의 결과 칸과 가드 판정 표시. 가드 판정은 서버가 정한다(같은 자식의 그냥 돌리기가 통과하고 무른
// 실행이 지키는 곳 기대에서 실패해야 확인됨) — 그냥 돌려도 실패하면 「가드 확인 불가」(초록도 빨강도 아님, 세지 않음).
import Badge from '../../shared/ui/Badge';
import type { HarnessTestOut } from './devApi';
import RawBlock from './RawBlock';

export interface Outcome {
  run?: HarnessTestOut;
  broken?: HarnessTestOut;
  error?: string;
  busy?: boolean;
}

/** [글, 칸 꼴] — 확인됨(초록) · 확인 안 됨(빨강) · 확인 불가(옅게, null). */
export function guardTag(r: HarnessTestOut): [string, string] {
  if (r.guard_confirmed === true) return ['가드 확인됨', 'is-pass'];
  if (r.guard_confirmed === false) return ['가드 확인 안 됨', 'is-fail'];
  return ['가드 확인 불가', 'is-todo'];
}

export function ResultPanel({ id, outcome }: { id: string; outcome: Outcome }) {
  const shown = [outcome.run, outcome.broken].filter((r): r is HarnessTestOut => !!r);
  return (
    <section className="dc-og-result" aria-label={`${id} 결과`}>
      {shown.map((r) => (
        <div key={r.broken_guard ? 'broken' : 'run'} className="dc-og-result-one">
          <div className="dc-harness-test-head">
            <b>{r.broken_guard ? `${id} — 가드 「${r.broken_guard}」 끄고` : id}</b>
            {r.broken_guard ? (
              <Badge tone={r.guard_confirmed === true ? 'success' : r.guard_confirmed === false ? 'danger' : 'neutral'}>
                {`${guardTag(r)[0]} — ${r.guard_reason ?? ''}`}
              </Badge>
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
