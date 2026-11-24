// 사용량·비용: 기간(7/14/30일)과 묶는 기준(모델·사용자·날짜·작업 종류)으로 표 + 토큰 가로 막대, 합계 줄, 근거 검색 수,
// 11-23: 따로 센 호출(정보 API · Liner 검색 대 다시 쓰기 · 그림 읽기 · 임베딩, UsageCounters).
// Task 108: 연락 사용량(문자·장문·카카오톡·자동 답, 제공사 요금 — 알려 주지 않으면 그렇게 적는다).
// Task 110: 통화 사용량(통화 시간 · 건 통화 수 · 음성 모델 · 받아쓰기(기록이 있을 때만) · 통화 요약 — 알려 준 값만).
// 비용은 Liner 가 보낸 값만(cost_known 이 거짓이면 "—" 와 안내).
import { useEffect, useState } from 'react';
import { ApiError } from '../../shared/api';
import Field from '../../shared/ui/Field';
import { devApi, type CallUsage, type OutreachUsage, type UsageGroup, type UsageOut, type UsageRow, type UsageTotals } from './devApi';
import { cost, count } from './format';
import UsageCounters from './UsageCounters';

const PERIODS = [7, 14, 30];
const GROUPS: { value: UsageGroup; label: string }[] = [
  { value: 'model', label: '모델' },
  { value: 'user', label: '사용자' },
  { value: 'day', label: '날짜' },
  { value: 'purpose', label: '작업 종류' },
];
const PURPOSES: Record<string, string> = {
  light: '가벼운 일',
  normal: '보통 일',
  hard: '어려운 일',
  longdoc: '긴 문서 읽기',
  vision: '그림 읽기',
  embedding: '임베딩',
};
export const COST_NOTE = 'Liner가 비용 값을 보내지 않아 비용은 비어 있습니다(토큰만 셉니다).';

function KeyCell({ row, group }: { row: UsageRow; group: UsageGroup }) {
  const label = group === 'purpose' ? PURPOSES[row.key] : undefined;
  return (
    <th scope="row" className="dc-u-key">
      <span className="dc-ellipsis" title={row.key}>
        {label ?? row.key}
      </span>
      {label && <span className="dc-muted">{` ${row.key}`}</span>}
    </th>
  );
}

const costText = (data: UsageOut, t: UsageTotals) => (data.cost_known && t.cost !== null ? cost(t.cost) : '—');

function UsageTable({ data, group }: { data: UsageOut; group: UsageGroup }) {
  const max = Math.max(1, ...data.rows.map((r) => r.input_tokens + r.output_tokens));
  const head = GROUPS.find((g) => g.value === group)!.label;
  return (
    <div className="dc-u-wrap">
      <table className="dc-u" aria-label="사용량">
        <thead>
          <tr>
            <th scope="col">{head}</th>
            <th scope="col">호출</th>
            <th scope="col">입력 토큰</th>
            <th scope="col">출력 토큰</th>
            <th scope="col" className="dc-u-barcol">토큰</th>
            <th scope="col">비용</th>
            <th scope="col">실패</th>
          </tr>
        </thead>
        <tbody>
          {data.rows.length === 0 && (
            <tr>
              <td colSpan={7} className="dc-muted">
                이 기간에 기록된 모델 호출이 없습니다.
              </td>
            </tr>
          )}
          {data.rows.map((r) => {
            const total = r.input_tokens + r.output_tokens;
            return (
              <tr key={r.key}>
                <KeyCell row={r} group={group} />
                <td>{count(r.calls)}</td>
                <td>{count(r.input_tokens)}</td>
                <td>{count(r.output_tokens)}</td>
                <td className="dc-u-barcol">
                  <div className="dc-u-bar" role="meter" aria-label={`${r.key} 토큰`} aria-valuemin={0} aria-valuemax={max} aria-valuenow={total}>
                    <i style={{ width: `${(100 * total) / max}%` }} />
                  </div>
                </td>
                <td>{costText(data, r)}</td>
                <td className={r.failed ? 'is-danger' : undefined}>{count(r.failed)}</td>
              </tr>
            );
          })}
        </tbody>
        <tfoot>
          <tr>
            <th scope="row">합계</th>
            <td>{count(data.totals.calls)}</td>
            <td>{count(data.totals.input_tokens)}</td>
            <td>{count(data.totals.output_tokens)}</td>
            <td className="dc-u-barcol" />
            <td>{costText(data, data.totals)}</td>
            <td>{count(data.totals.failed)}</td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

export const FEE_UNREPORTED = '제공사가 알려 주지 않음';
const MODEL_FEE_UNREPORTED = '모델이 알려 주지 않음';
/** 글 쪽 모델 사용 종류(outreach_usage.kind, Task 109). 모르는 종류는 받은 그대로. */
const TEXT_KIND: Record<string, string> = { text_reply: '문자 답', draft: '초안', translation: '번역' };

/** 연락 글 쪽 모델 사용: 받은 문자에 답 만들기 · 초안 · 번역의 횟수·토큰·요금(모델이 알려 준 것만). */
function TextModelTable({ rows }: { rows: NonNullable<OutreachUsage['text_models']> }) {
  return (
    <div className="dc-u-wrap">
      <table className="dc-u" aria-label="연락 글 모델 사용량">
        <thead>
          <tr>
            <th scope="col">글 쪽 모델</th>
            <th scope="col">횟수</th>
            <th scope="col">입력 토큰</th>
            <th scope="col">출력 토큰</th>
            <th scope="col" title="여러 번 가운데 일부만 알려 주었으면 알려 준 것만 더한 값입니다.">요금(알려 준 것)</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.kind}>
              <th scope="row">{TEXT_KIND[r.kind] ?? r.kind}</th>
              <td>{count(r.count)}</td>
              <td>{count(r.input_tokens)}</td>
              <td>{count(r.output_tokens)}</td>
              <td className={r.cost === null ? 'dc-muted' : undefined}>{r.cost === null ? MODEL_FEE_UNREPORTED : cost(r.cost)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** 연락 사용량: 나간 것(차지한 순간 기준 — 하루 상한이 세는 수와 같다). 장문은 문자의 일부. */
function OutreachUsageTable({ o }: { o: OutreachUsage }) {
  const lines: [string, string, string][] = [
    ['문자 (단문·장문)', count(o.sms), '대신 문자로 나간 카카오톡 포함'],
    ['그 가운데 장문', count(o.long), ''],
    ['카카오톡', count(o.kakao), ''],
    ['자동 답·고정 안내', count(o.auto_replies), '문자 수에 이미 들어 있음'],
    ['제공사 요금', o.provider_cost === null ? FEE_UNREPORTED : cost(o.provider_cost), '메시지마다의 요금은 제공사가 주지 않습니다'],
  ];
  return (
    <div className="dc-u-wrap">
      <table className="dc-u" aria-label="연락 사용량">
        <thead>
          <tr>
            <th scope="col">연락</th>
            <th scope="col">건수·요금</th>
            <th scope="col">메모</th>
          </tr>
        </thead>
        <tbody>
          {lines.map(([name, value, note]) => (
            <tr key={name}>
              <th scope="row">{name}</th>
              <td>{value}</td>
              <td className="dc-u-note">{note}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const UNREPORTED = '알려 주지 않음';
/** 통화 쪽 모델 사용 종류(outreach_usage.kind, Task 110). 모르는 종류는 받은 그대로. */
const CALL_KIND: Record<string, string> = { voice_model: '음성 모델', transcription: '받아쓰기', summary: '통화 요약' };

/** 통화 사용량: 통화 시간 · 건 통화 수, 통화 쪽 모델의 횟수·초·토큰·요금 — 백엔드가 알려 준 값만(토큰 0 = 알려 주지 않음). */
function CallUsageTable({ c }: { c: CallUsage }) {
  const minutes = `${Math.floor(c.call_seconds / 60)}분 ${c.call_seconds % 60}초`;
  return (
    <div className="dc-u-wrap">
      <p className="dc-u-search">{`통화 시간 ${minutes} (건 통화·받은 통화) · 건 통화 ${count(c.calls_placed)}통 (걸려고 줄에 넣은 것 — 결과를 모르는 통화 포함)`}
        {c.calls_answered !== undefined && ` · 받은 통화 ${count(c.calls_answered)}통 · 받기 전 거절 ${count(c.calls_rejected ?? 0)}통`}</p>
      <table className="dc-u" aria-label="통화 사용량">
        <thead>
          <tr>
            <th scope="col">통화 쪽 모델</th>
            <th scope="col">횟수</th>
            <th scope="col">초</th>
            <th scope="col">토큰(입력·출력)</th>
            <th scope="col" title="여러 번 가운데 일부만 알려 주었으면 알려 준 것만 더한 값입니다.">요금(알려 준 것)</th>
          </tr>
        </thead>
        <tbody>
          {c.models.map((m) => {
            const tokens = m.input_tokens + m.output_tokens > 0;
            return (
              <tr key={m.kind}>
                <th scope="row">{CALL_KIND[m.kind] ?? m.kind}</th>
                <td>{count(m.count)}</td>
                <td>{m.seconds > 0 ? count(m.seconds) : '—'}</td>
                <td className={tokens ? undefined : 'dc-muted'}>{tokens ? `${count(m.input_tokens)} · ${count(m.output_tokens)}` : UNREPORTED}</td>
                <td className={m.cost === null ? 'dc-muted' : undefined}>{m.cost === null ? UNREPORTED : cost(m.cost)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function UsageTab() {
  const [days, setDays] = useState(14);
  const [group, setGroup] = useState<UsageGroup>('model');
  const [data, setData] = useState<{ key: string; body: UsageOut } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const key = `${days}-${group}`;

  useEffect(() => {
    let alive = true;
    devApi.usage(days, group).then(
      (body) => {
        if (!alive) return;
        setData({ key: `${days}-${group}`, body });
        setError(null);
      },
      (e: unknown) => alive && setError(e instanceof ApiError ? e.message : '사용량을 읽을 수 없습니다.'),
    );
    return () => {
      alive = false;
    };
  }, [days, group]);

  const body = data?.key === key ? data.body : null;
  return (
    <div className="dc-usage">
      <div className="dc-u-controls">
        <Field label="기간">
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {PERIODS.map((d) => (
              <option key={d} value={d}>{`${d}일`}</option>
            ))}
          </select>
        </Field>
        <Field label="묶는 기준">
          <select value={group} onChange={(e) => setGroup(e.target.value as UsageGroup)}>
            {GROUPS.map((g) => (
              <option key={g.value} value={g.value}>
                {g.label}
              </option>
            ))}
          </select>
        </Field>
        {body && <span className="dc-u-search">{`근거 검색 ${count(body.searches.calls)}번 · 실패 ${count(body.searches.failed)}`}</span>}
      </div>
      {error && (
        <p className="dc-error" role="alert">
          {error}
        </p>
      )}
      {body && !body.cost_known && <p className="dc-note">{COST_NOTE}</p>}
      {body ? <UsageTable data={body} group={group} /> : !error && <p className="dc-empty">불러오는 중…</p>}
      {body?.counters && <UsageCounters counters={body.counters} />}
      {body?.outreach && <OutreachUsageTable o={body.outreach} />}
      {body?.outreach?.text_models && body.outreach.text_models.length > 0 && <TextModelTable rows={body.outreach.text_models} />}
      {body?.outreach?.calls && <CallUsageTable c={body.outreach.calls} />}
    </div>
  );
}
