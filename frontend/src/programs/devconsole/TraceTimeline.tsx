// 실행 추적: 시간순 표(종류 · 이름 · 시각 · 시간 · 모델 · 토큰 · 결과). 줄을 누르면 입력·출력 원문이 접힌 블록으로 열린다.
// 알려진 한계를 그대로 보인다: 도구 시작 시각은 「어림」, 컨텍스트 조립 시간은 실제보다 김(＊), 잘린 답 뒤 단계는 「짝 없음」.
// 연락 기록(Task 108)의 하네스 사건(kind harness)도 같은 줄로 그린다: 이름 · 시도 · 「확인 필요」 · 판정, 펼치면 기계 출력(접힘).
import { useMemo, useState } from 'react';
import Badge, { type Tone } from '../../shared/ui/Badge';
import type { TraceItem } from './devApi';
import { clock, count, seconds } from './format';
import { CONTEXT_MS_NOTE } from './NodeDetail';
import RawBlock from './RawBlock';
import { REFUSAL_SIGNALS, STEP_SIGNALS } from './signals';

const KIND: Record<TraceItem['kind'], { label: string; tone: Tone }> = {
  context: { label: '컨텍스트', tone: 'neutral' },
  llm: { label: '모델', tone: 'info' },
  tool: { label: '도구', tone: 'success' },
  inner_llm: { label: '도구 안 모델', tone: 'warning' },
  harness: { label: '하네스', tone: 'neutral' },
};
const ESTIMATE_NOTE = '단계 기록에는 시각이 없어, 이 도구를 부른 답이 끝난 때에 앞 단계 시간을 더한 어림입니다.';
const UNPAIRED_NOTE = '이 도구를 부른 답이 길어서 잘려 어느 답이 불렀는지 읽을 수 없습니다. 시각은 앞 단계 뒤에 둔 어림입니다.';
const INNER_NOTE = '도구 안 모델 호출은 글을 남기지 않습니다(모델·토큰·시간만).';
const CHECK_NOTE = '보냈는지 알 수 없는 결과입니다. 실패가 아니며 자동으로 다시 보내지 않습니다 — 사람이 확인해 정합니다.';
const UNKNOWN_NOTE = '모양이 틀렸거나 하네스 낱말에 없는 사건입니다. 저장된 값은 보이지 않습니다.';

/** 시간이 없는(끝 기록이 없는) 호출은 턴이 실행 중일 때만 「진행 중」, 아니면 「끝나지 않음」.
 * 규칙이 막은 도구(역할 규칙·가져오기 되풀이)는 「거절: 까닭」. */
function result(t: TraceItem, running: boolean): { text: string; danger: boolean } {
  if (t.harness) return { text: t.harness.verdict_label, danger: t.harness.verdict === 'blocked' };
  if (t.ok && t.ms === null && (t.kind === 'llm' || t.kind === 'tool')) return { text: running ? '진행 중' : '끝나지 않음', danger: false };
  if (t.ok) return { text: '성공', danger: false };
  if (t.error === 'stopped') return { text: '멈춤', danger: false };
  const head = (t.signals ?? []).some((f) => REFUSAL_SIGNALS.has(f)) ? '거절' : '실패';
  return { text: t.error ? `${head}: ${t.error}` : head, danger: true };
}

/** 하네스 사건의 태그: 사건 이름(도구 호출은 이름에 도구가 이미 있다) · 묶음(이름에 없을 때) · 시도 차례 · 확인 필요. */
function HarnessTags({ t }: { t: TraceItem }) {
  const h = t.harness;
  if (!h) return null;
  return (
    <>
      {h.rule && !h.rule.startsWith('tool:') && <code className="dc-o-rule" title="사건 이름">{h.rule}</code>}
      {!h.unknown && !t.label.startsWith(h.group_label) && <span className="dc-tag">{h.group_label}</span>}
      {h.attempt !== null && <span className="dc-tag is-info">{`시도 ${h.attempt}`}</span>}
      {h.needs_check && <span className="dc-tag is-warn" title={CHECK_NOTE}>확인 필요</span>}
    </>
  );
}

/** 펼친 하네스 사건: 코드·차례는 접힌 기계 출력으로. */
function HarnessBody({ t }: { t: TraceItem }) {
  const h = t.harness!;
  if (h.unknown) return <p className="dc-muted">{UNKNOWN_NOTE}</p>;
  const machine = { group: h.group, rule: h.rule, verdict: h.verdict, order: h.order, code: h.code, attempt: h.attempt };
  return (
    <>
      {h.needs_check && <p className="dc-muted">{CHECK_NOTE}</p>}
      <RawBlock label="기계 출력" value={machine} />
    </>
  );
}

/** 그 단계의 신호 태그(저장된 근거 · 정보 API · 역할 거절 …). 예전 서버는 signals 가 없다. */
function SignalTags({ t }: { t: TraceItem }) {
  return (t.signals ?? [])
    .filter((f) => STEP_SIGNALS[f])
    .map((f) => (
      <span key={f} className={`dc-tag ${STEP_SIGNALS[f].warn ? 'is-warn' : 'is-info'}`} title={STEP_SIGNALS[f].label}>
        {STEP_SIGNALS[f].short}
      </span>
    ));
}

interface RowProps {
  t: TraceItem;
  running: boolean;
  loop: number | null;
  group: number;
  open: boolean;
  onToggle(): void;
}

function Row({ t, running, loop, group, open, onToggle }: RowProps) {
  const r = result(t, running);
  const unpaired = t.kind === 'tool' && t.parallel_group === null;
  const tokenText = t.input_tokens || t.output_tokens ? `${count(t.input_tokens)} → ${count(t.output_tokens)}` : '—';
  return (
    <li className={`dc-tr${group > 1 ? ' is-par' : ''}`}>
      <button type="button" className="dc-tr-row" aria-expanded={open} onClick={onToggle}>
        <span className="dc-c-kind">
          <Badge tone={KIND[t.kind].tone}>{KIND[t.kind].label}</Badge>
        </span>
        <span className="dc-c-name">
          <span className="dc-ellipsis" title={t.label}>
            {t.label}
          </span>
          {loop !== null && <span className="dc-tag">{`${loop}바퀴`}</span>}
          {group > 1 && <span className="dc-tag is-info" title="한 답이 함께 부른 도구입니다.">{`동시 ${group}`}</span>}
          {unpaired && <span className="dc-tag is-warn" title={UNPAIRED_NOTE}>짝 없음</span>}
          <SignalTags t={t} />
          <HarnessTags t={t} />
        </span>
        <span className="dc-c-time">
          {clock(t.started_at)}
          {t.kind === 'tool' && <span className="dc-tag is-warn" title={ESTIMATE_NOTE}>어림</span>}
        </span>
        <span className="dc-c-dur">
          {t.ms === null ? '—' : seconds(t.ms)}
          {t.kind === 'context' && t.ms !== null && <span className="dc-star" title={CONTEXT_MS_NOTE}>＊</span>}
        </span>
        <span className="dc-c-model dc-ellipsis" title={t.model ?? undefined}>
          {t.model ?? '—'}
        </span>
        <span className="dc-c-tok">{tokenText}</span>
        <span className={`dc-c-res dc-ellipsis${r.danger ? ' is-danger' : ''}`} title={r.text}>
          {r.text}
        </span>
      </button>
      {open && (
        <div className="dc-tr-body">
          {t.kind === 'harness' ? (
            <HarnessBody t={t} />
          ) : t.kind === 'inner_llm' ? (
            <p className="dc-muted">{INNER_NOTE}</p>
          ) : (
            <>
              <RawBlock label="입력 원문" value={t.input_text} />
              <RawBlock label="출력 원문" value={t.output_text} empty={t.ms === null ? (running ? '아직 없음 (진행 중)' : '없음 (끝나지 않음)') : '없음'} />
            </>
          )}
          {t.error && t.error !== 'stopped' && <p className="dc-error">{t.error}</p>}
        </div>
      )}
    </li>
  );
}

interface Props {
  items: TraceItem[];
  running: boolean;
  /** 줄이 없을 때의 글. */
  empty?: string;
}

export default function TraceTimeline({ items, running, empty = '이 요청에는 아직 기록이 없습니다.' }: Props) {
  const [open, setOpen] = useState<Set<number>>(new Set());
  const { loops, groups } = useMemo(() => {
    const loops = new Map<number, number>();
    const groups = new Map<number, number>();
    for (const t of items) {
      if (t.kind === 'llm') loops.set(t.seq, loops.size + 1);
      if (t.kind === 'tool' && t.parallel_group !== null) groups.set(t.parallel_group, (groups.get(t.parallel_group) ?? 0) + 1);
    }
    return { loops, groups };
  }, [items]);
  const toggle = (seq: number) => setOpen((s) => new Set(s.has(seq) ? [...s].filter((x) => x !== seq) : [...s, seq]));
  const notes = [
    items.some((t) => t.kind === 'tool') && `「어림」 ${ESTIMATE_NOTE}`,
    items.some((t) => t.kind === 'context') && `＊ ${CONTEXT_MS_NOTE}`,
    items.some((t) => t.kind === 'tool' && t.parallel_group === null) && `「짝 없음」 ${UNPAIRED_NOTE}`,
  ].filter(Boolean) as string[];
  if (items.length === 0) return <p className="dc-empty">{empty}</p>;
  return (
    <div className="dc-trace">
      <div className="dc-tr-head" aria-hidden="true">
        {['종류', '이름', '시각', '시간', '모델', '토큰 (입력 → 출력)', '결과'].map((h) => (
          <span key={h}>{h}</span>
        ))}
      </div>
      <ol className="dc-tr-list" aria-label="실행 추적">
        {items.map((t) => (
          <Row
            key={t.seq}
            t={t}
            running={running}
            loop={loops.get(t.seq) ?? null}
            group={t.parallel_group === null ? 0 : (groups.get(t.parallel_group) ?? 0)}
            open={open.has(t.seq)}
            onToggle={() => toggle(t.seq)}
          />
        ))}
      </ol>
      <ul className="dc-notes">
        {notes.map((n) => (
          <li key={n}>{n}</li>
        ))}
      </ul>
    </div>
  );
}
