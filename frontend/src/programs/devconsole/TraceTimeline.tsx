// 실행 추적: 시간순 표(종류 · 이름 · 시각 · 시간 · 모델 · 토큰 · 결과). 줄을 누르면 입력·출력 원문이 접힌 블록으로 열린다.
// 알려진 한계를 그대로 보인다: 도구 시작 시각은 「어림」, 컨텍스트 조립 시간은 실제보다 김(＊), 잘린 답 뒤 단계는 「짝 없음」.
import { useMemo, useState } from 'react';
import Badge, { type Tone } from '../../shared/ui/Badge';
import type { TraceItem } from './devApi';
import { clock, count, seconds } from './format';
import { CONTEXT_MS_NOTE } from './NodeDetail';
import RawBlock from './RawBlock';

const KIND: Record<TraceItem['kind'], { label: string; tone: Tone }> = {
  context: { label: '컨텍스트', tone: 'neutral' },
  llm: { label: '모델', tone: 'info' },
  tool: { label: '도구', tone: 'success' },
  inner_llm: { label: '도구 안 모델', tone: 'warning' },
};
const ESTIMATE_NOTE = '단계 기록에는 시각이 없어, 이 도구를 부른 답이 끝난 때에 앞 단계 시간을 더한 어림입니다.';
const UNPAIRED_NOTE = '이 도구를 부른 답이 길어서 잘려 어느 답이 불렀는지 읽을 수 없습니다. 시각은 앞 단계 뒤에 둔 어림입니다.';
const INNER_NOTE = '도구 안 모델 호출은 글을 남기지 않습니다(모델·토큰·시간만).';

function result(t: TraceItem): { text: string; danger: boolean } {
  if (t.ok && t.ms === null && (t.kind === 'llm' || t.kind === 'tool')) return { text: '진행 중', danger: false };
  if (t.ok) return { text: '성공', danger: false };
  if (t.error === 'stopped') return { text: '멈춤', danger: false };
  return { text: t.error ? `실패: ${t.error}` : '실패', danger: true };
}

function Row({ t, loop, group, open, onToggle }: { t: TraceItem; loop: number | null; group: number; open: boolean; onToggle(): void }) {
  const r = result(t);
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
          {t.kind === 'inner_llm' ? (
            <p className="dc-muted">{INNER_NOTE}</p>
          ) : (
            <>
              <RawBlock label="입력 원문" value={t.input_text} />
              <RawBlock label="출력 원문" value={t.output_text} empty={t.ms === null ? '아직 없음 (진행 중)' : '없음'} />
            </>
          )}
          {t.error && t.error !== 'stopped' && <p className="dc-error">{t.error}</p>}
        </div>
      )}
    </li>
  );
}

export default function TraceTimeline({ items }: { items: TraceItem[] }) {
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
  if (items.length === 0) return <p className="dc-empty">이 요청에는 아직 기록이 없습니다.</p>;
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
