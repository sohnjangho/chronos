// 사용량의 따로 센 호출(11-23): 외부 정보(정보 API·기상청) · 근거 검색(Liner 대 저장된 근거 다시 쓰기) · 모델(그림 읽기·임베딩).
// 비용은 기록된 것만 보인다(정보 API·근거 검색은 비용이 기록되지 않는다 — 「—」).
// 관리 포인트(계획 5 Task 7)의 Premium Data·MCP·Search Agent 는 Liner 가 값을 알리지 않아 호출 수 × 단가로 어림한다(「어림」).
import type { UsageCounters as Counters, UsageTotals } from './devApi';
import { cost, count } from './format';
import { estimate as usd } from './pointsText';

interface Line {
  name: string;
  calls: number;
  failed: number | null;
  tokens: string;
  cost: string;
  note: string;
}

const NO_COST = '—';
/** 호출 수 × 1,000회당 값(USD) → 「어림 $0.0040」. */
const estimate = (calls: number, per1k: number) => `어림 ${usd((calls * per1k) / 1000)}`;
const pointLine = (name: string, c: { calls: number; failed: number } | undefined, per1k: number, note: string): Line[] =>
  c ? [{ name, calls: c.calls, failed: c.failed, tokens: NO_COST, cost: estimate(c.calls, per1k), note }] : [];
const llmLine = (name: string, t: UsageTotals, note: string): Line => ({
  name, calls: t.calls, failed: t.failed, tokens: `${count(t.input_tokens)} → ${count(t.output_tokens)}`,
  cost: t.cost !== null ? cost(t.cost) : NO_COST, note,
});

function groups(c: Counters): [string, Line[]][] {
  const all: [string, Line[]][] = [
    ['외부 정보', [
      { name: '정보 API 조회 (info.call)', calls: c.info_api.calls, failed: c.info_api.failed, tokens: NO_COST, cost: NO_COST, note: '한 요청 4번까지' },
      { name: '기상청 날씨 조회 (info.weather)', calls: c.weather.calls, failed: c.weather.failed, tokens: NO_COST, cost: NO_COST, note: '' },
    ]],
    ['근거 검색', [
      { name: 'Liner 근거 검색', calls: c.searches.calls, failed: c.searches.failed, tokens: NO_COST, cost: NO_COST, note: '' },
      { name: '저장된 근거 다시 씀', calls: c.reuses.calls, failed: null, tokens: NO_COST, cost: NO_COST, note: `Liner 호출 ${count(c.reuses.calls)}번 아낌` },
    ]],
    ['모델', [llmLine('그림 읽기 (vision)', c.vision, '사진 판독·그림 턴'), llmLine('임베딩 (embedding)', c.embedding, '자료함 뜻 검색')]],
    ['관리 포인트 (Liner)', [
      ...pointLine('자재·환율 (Search + Premium Data)', c.knowledge, 2, '$2/1K'),
      ...pointLine('업체·규제 소식 (MCP search_business·search_legal)', c.mcp, 2, '$2/1K'),
      ...pointLine('근거 문장 (Search Agent)', c.search_agent, 20, '$20/1K'),
    ]],
  ];
  return all.filter(([, lines]) => lines.length > 0); // 예전 서버는 관리 포인트 수를 보내지 않는다
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
