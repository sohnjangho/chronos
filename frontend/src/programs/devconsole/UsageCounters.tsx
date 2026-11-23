// 사용량의 따로 센 호출(11-23): 바깥 정보(정보 API·기상청) · 근거 검색(Liner 대 저장된 근거 다시 쓰기) · 모델(그림 읽기·임베딩).
// 비용은 기록된 것만 보인다(정보 API·근거 검색은 비용이 기록되지 않는다 — 「—」).
import type { UsageCounters as Counters, UsageTotals } from './devApi';
import { cost, count } from './format';

interface Line {
  name: string;
  calls: number;
  failed: number | null;
  tokens: string;
  cost: string;
  note: string;
}

const NO_COST = '—';
const llmLine = (name: string, t: UsageTotals, note: string): Line => ({
  name, calls: t.calls, failed: t.failed, tokens: `${count(t.input_tokens)} → ${count(t.output_tokens)}`,
  cost: t.cost !== null ? cost(t.cost) : NO_COST, note,
});

function groups(c: Counters): [string, Line[]][] {
  return [
    ['바깥 정보', [
      { name: '정보 API 조회 (info.call)', calls: c.info_api.calls, failed: c.info_api.failed, tokens: NO_COST, cost: NO_COST, note: '한 요청 4번까지' },
      { name: '기상청 날씨 조회 (info.weather)', calls: c.weather.calls, failed: c.weather.failed, tokens: NO_COST, cost: NO_COST, note: '' },
    ]],
    ['근거 검색', [
      { name: 'Liner 근거 검색', calls: c.searches.calls, failed: c.searches.failed, tokens: NO_COST, cost: NO_COST, note: '' },
      { name: '저장된 근거 다시 씀', calls: c.reuses.calls, failed: null, tokens: NO_COST, cost: NO_COST, note: `Liner 호출 ${count(c.reuses.calls)}번 아낌` },
    ]],
    ['모델', [llmLine('그림 읽기 (vision)', c.vision, '사진 판독·그림 턴'), llmLine('임베딩 (embedding)', c.embedding, '자료함 뜻 검색')]],
  ];
}

export default function UsageCounters({ counters }: { counters: Counters }) {
  return (
    <div className="dc-u-wrap">
      <table className="dc-u" aria-label="따로 센 호출">
        <thead>
          <tr>
            <th scope="col">따로 센 호출</th>
            <th scope="col">호출</th>
            <th scope="col">실패</th>
            <th scope="col">토큰 (입력 → 출력)</th>
            <th scope="col">비용</th>
            <th scope="col">메모</th>
          </tr>
        </thead>
        {groups(counters).map(([group, lines]) => (
          <tbody key={group} aria-label={group}>
            <tr className="dc-u-group">
              <th scope="rowgroup" colSpan={6}>{group}</th>
            </tr>
            {lines.map((l) => (
              <tr key={l.name}>
                <th scope="row">{l.name}</th>
                <td>{count(l.calls)}</td>
                <td className={l.failed ? 'is-danger' : undefined}>{l.failed === null ? NO_COST : count(l.failed)}</td>
                <td>{l.tokens}</td>
                <td>{l.cost}</td>
                <td className="dc-u-note">{l.note}</td>
              </tr>
            ))}
          </tbody>
        ))}
      </table>
    </div>
  );
}
