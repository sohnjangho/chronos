// 실행 추적의 「연락」(Task 108): 연락 기록 하나의 머리 줄(누구와 · 누가 시작 · 권한 방식 · 등급 · 상태)과 하네스 사건 시간표.
// 사건은 서버가 harness.types 의 묶음으로 나눠 준다 — 묶음(수와 함께)으로 거르고 이름·코드로 찾는다. 읽기만 한다.
// Task 109: 위에 다섯 마디 흐름도(OutreachFlow), 도구 사건 줄은 공용 한글 도구 이름(outreach.<이름>).
// Task 110: 통화는 머리 줄에 통화 시간, 받아쓰기는 줄 수만(글은 연락처 프로그램에서), 결과 모름은 「확인 필요」.
import { useEffect, useMemo, useState } from 'react';
import { ApiError } from '../../shared/api';
import { TOOL_LABELS } from '../../shared/toolLabels';
import Badge from '../../shared/ui/Badge';
import { devApi, type OutreachDetail, type OutreachRow, type TraceItem } from './devApi';
import { hourMinute } from './format';
import { channelOf, classOf, modeOf, rowStatusOf, starterOf, whoOf } from './outreachText';
import TraceTimeline from './TraceTimeline';
import { OutreachFlow } from './TurnFlowDiagram';

/** 도구 사건 줄(「도구 find_contact」)의 도구 이름을 공용 한글 이름으로(「도구 · 연락처 찾기」). 표에 없는 이름은 그대로. */
function named(t: TraceItem): TraceItem {
  const code = t.harness?.group === 'tool' ? t.harness.code : null;
  const label = code ? TOOL_LABELS[`outreach.${code}`] : undefined;
  return label && t.label.endsWith(` ${code}`) ? { ...t, label: `${t.label.slice(0, -code!.length - 1)} · ${label}` } : t;
}

/** 통화 시간: 초가 없으면 「—」(받지 않음·걸지 않음). */
const talkTime = (s: number | null | undefined) => (typeof s === 'number' ? `${Math.floor(s / 60)}분 ${s % 60}초` : '—');

const ALL = 'all';
const NONE_NOTE = '이 연락에는 남은 하네스 사건이 없습니다.';

function Head({ d }: { d: OutreachDetail }) {
  const h = d.head;
  const s = rowStatusOf(h);
  return (
    <div className="dc-stats dc-o-head" role="group" aria-label="이 연락">
      <Badge tone={s.tone}>{s.label}</Badge>
      <b className="dc-ellipsis" title={whoOf(h)}>{whoOf(h)}</b>
      <span>{channelOf(h)}</span>
      <span>
        시작 <b>{starterOf(h)}</b>
      </span>
      <span>
        권한 <b>{modeOf(h.send_mode)}</b>
        {h.approved_by && <span className="dc-muted">{` (${h.approved_by})`}</span>}
      </span>
      <span>
        등급 <b>{classOf(h.caller_class)}</b>
      </span>
      {h.kind === 'call' && (
        <span>
          통화 <b>{talkTime(h.duration_s)}</b>
        </span>
      )}
      {h.schedule_name && <span className="dc-ellipsis" title={h.schedule_name}>{h.schedule_name}</span>}
      <span className="dc-muted">{hourMinute(h.at)}</span>
    </div>
  );
}

function Notes({ d }: { d: OutreachDetail }) {
  const lines = d.head.transcript_lines;
  const what = d.head.kind === 'call' ? '걸렸는지(끝났는지)' : '보냈는지';
  return (
    <>
      {d.needs_check > 0 && (
        <p className="dc-note">{`확인 필요 ${d.needs_check}건 — ${what} 알 수 없는 결과입니다. 실패가 아니며 자동으로 다시 보내지 않습니다.`}</p>
      )}
      {d.head.kind === 'call' && typeof lines === 'number' && <p className="dc-muted">{`받아쓰기 ${lines}줄 — 연락처 프로그램에서 봅니다`}</p>}
      {d.head.fail_reason && <p className="dc-muted">{`남은 까닭: ${d.head.fail_reason}`}</p>}
      {d.omitted > 0 && <p className="dc-muted">{`앞선 사건 ${d.omitted}개는 줄의 기록 상한(최근 것만 남김)으로 보이지 않습니다.`}</p>}
    </>
  );
}

const haystack = (t: TraceItem) => {
  const h = t.harness;
  return [t.label, h?.group_label, h?.rule, h?.code, h?.verdict_label, h?.attempt ? `시도 ${h.attempt}` : '']
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
};

function Filters({ d, group, onGroup, query, onQuery }: { d: OutreachDetail; group: string; onGroup(g: string): void; query: string; onQuery(q: string): void }) {
  const chips = [{ key: ALL, label: '전체', count: d.timeline.length }, ...d.groups.filter((g) => g.count > 0)];
  return (
    <div className="dc-o-filters">
      <div className="dc-chip-bar" role="radiogroup" aria-label="사건 묶음">
        {chips.map((c) => (
          <button key={c.key} type="button" role="radio" aria-checked={group === c.key} className={`dc-mode-btn${group === c.key ? ' is-on' : ''}`} onClick={() => onGroup(c.key)}>
            {`${c.label} ${c.count}`}
          </button>
        ))}
      </div>
      <input type="search" className="dc-pick-search dc-o-search" aria-label="사건 찾기" placeholder="이름·코드·도구로 찾기" value={query} onChange={(e) => onQuery(e.target.value)} />
    </div>
  );
}

export default function OutreachTrace({ row }: { row: Pick<OutreachRow, 'kind' | 'id'> }) {
  const [data, setData] = useState<OutreachDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [group, setGroup] = useState(ALL);
  const [query, setQuery] = useState('');
  useEffect(() => {
    let live = true;
    devApi.outreach(row.kind, row.id).then(
      (d) => live && setData(d),
      (e: unknown) => live && setError(e instanceof ApiError ? e.message : '연락 기록을 읽을 수 없습니다.'),
    );
    return () => {
      live = false;
    };
  }, [row.kind, row.id]);
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (data?.timeline ?? []).map(named).filter(
      (t) => (group === ALL || (t.harness?.group ?? 'unknown') === group) && (!q || haystack(t).includes(q)),
    );
  }, [data, group, query]);
  if (error) return <p className="dc-error dc-pad" role="alert">{error}</p>;
  if (!data) return <p className="dc-empty">불러오는 중…</p>;
  return (
    <div className="dc-o-trace">
      <Head d={data} />
      <Notes d={data} />
      {data.flow && data.flow.length > 0 && <OutreachFlow flow={data.flow} lit={data.branches_lit ?? []} kind={data.head.kind} direction={data.head.direction} />}
      {data.timeline.length > 0 && <Filters d={data} group={group} onGroup={setGroup} query={query} onQuery={setQuery} />}
      <TraceTimeline items={shown} running={false} empty={data.timeline.length ? '찾는 사건이 없습니다.' : NONE_NOTE} />
    </div>
  );
}
