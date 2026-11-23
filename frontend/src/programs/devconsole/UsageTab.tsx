// 사용량·비용: 기간(7/14/30일)과 묶는 기준(모델·사용자·날짜·작업 종류)으로 표 + 토큰 가로 막대, 합계 줄, 근거 검색 수,
// 11-23: 따로 센 호출(정보 API · Liner 검색 대 다시 쓰기 · 그림 읽기 · 임베딩, UsageCounters).
// 비용은 Liner 가 보낸 값만(cost_known 이 거짓이면 "—" 와 안내).
import { useEffect, useState } from 'react';
import { ApiError } from '../../shared/api';
import Field from '../../shared/ui/Field';
import { devApi, type UsageGroup, type UsageOut, type UsageRow, type UsageTotals } from './devApi';
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
    </div>
  );
}
