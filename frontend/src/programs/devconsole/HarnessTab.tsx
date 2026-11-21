// AX 인재전쟁(약속선) 스타일 하네스 카탈로그 및 실시간 [차단 시험] 탭.
import { useState } from 'react';
import Badge from '../../shared/ui/Badge';
import { devApi, type CatalogOut, type HarnessRule, type HarnessTestOut } from './devApi';

const AREAS = ['전체', '입력', '조건 점검', '승인', '루프'] as const;

function RuleRow({
  rule,
  tested,
  testing,
  onTest,
}: {
  rule: HarnessRule;
  tested: HarnessTestOut | undefined;
  testing: boolean;
  onTest(id: string): void;
}) {
  const [openFeedback, setOpenFeedback] = useState(false);
  return (
    <tr className="dc-cat-row">
      <td className="dc-cat-id">
        <b>{rule.id}</b>
      </td>
      <td className="dc-cat-area">{rule.area}</td>
      <td className="dc-cat-main">
        <div className="dc-cat-title">{rule.title}</div>
        <p className="dc-muted">{rule.description}</p>
        <button type="button" className="dc-link" onClick={() => setOpenFeedback((o) => !o)}>
          {`${openFeedback ? '▼' : '▶'} 막을 때 모델이 받는 글`}
        </button>
        {openFeedback && <pre className="dc-code-block">{rule.feedback_sample}</pre>}
        {tested && (
          <div className="dc-harness-test-res" role="status">
            <div className="dc-harness-test-head">
              <Badge tone="danger">차단 시험 완료</Badge>
              <span>{`시뮬레이션 입력: ${tested.simulated_input}`}</span>
            </div>
            <pre className="dc-code-block">{JSON.stringify(tested.model_feedback, null, 2)}</pre>
          </div>
        )}
      </td>
      <td className="dc-cat-code">
        <code>{rule.code}</code>
        <span className="dc-tag is-warn">{rule.mode}</span>
      </td>
      <td className="dc-cat-stat">
        <Badge tone="success">구현</Badge>
      </td>
      <td className="dc-cat-counts">
        <Badge tone="success">{`통과 ${rule.passed_count}`}</Badge>
        {rule.blocked_count > 0 && <Badge tone="danger">{`차단 ${rule.blocked_count}`}</Badge>}
      </td>
      <td className="dc-cat-act">
        <button type="button" className="dc-btn" disabled={testing} onClick={() => onTest(rule.id)}>
          {testing ? '시험 중…' : '차단 시험'}
        </button>
      </td>
    </tr>
  );
}

export default function HarnessTab({ catalog }: { catalog: CatalogOut }) {
  const [area, setArea] = useState<string>('전체');
  const [results, setResults] = useState<Record<string, HarnessTestOut>>({});
  const [busyId, setBusyId] = useState<string | null>(null);

  const rules = area === '전체' ? catalog.harness : catalog.harness.filter((r) => r.area === area);

  async function runTest(ruleId: string) {
    setBusyId(ruleId);
    try {
      const res = await devApi.testHarness(ruleId);
      setResults((prev) => ({ ...prev, [ruleId]: res }));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="dc-scroll dc-cat-wrap">
      <div className="dc-cat-header">
        <h2 className="dc-cat-h2">하네스 (Harness Engineering)</h2>
        <p className="dc-muted">
          어기면 일정 무결성·자원 한도·권한이 틀어지는 규칙을 코드로 강제하는 지점입니다. 구현 {catalog.harness.length}개.
          「차단 시험」을 누르면 임시 상태에서 규칙을 일부러 어겨 보고 하네스가 모델에 돌려주는 차단·자가점검(reflection) JSON을 그대로 보여 줍니다.
        </p>
      </div>
      <div className="dc-note">
        <b>원천 연동</b> — 이 화면의 검사 위치·반려 문구·세션 통과/차단 수는 실제 실행 코드(<code>app/tools/harness/check.py</code>, <code>app/agent/loop.py</code>)와 워크플로우 실행 기록(DB)에서 직접 집계합니다.
      </div>
      <div className="dc-principles-box">
        <b>원칙</b>
        <ul>
          {catalog.principles.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      </div>
      <div className="dc-chip-bar" role="group" aria-label="하네스 위치 필터">
        {AREAS.map((a) => (
          <button key={a} type="button" className={`dc-mode-btn${area === a ? ' is-on' : ''}`} aria-pressed={area === a} onClick={() => setArea(a)}>
            {a}
          </button>
        ))}
      </div>
      <table className="dc-cat-table" aria-label="하네스 규칙 목록">
        <thead>
          <tr>
            <th>번호</th>
            <th>위치</th>
            <th>규칙과 강제 방식</th>
            <th>코드</th>
            <th>상태</th>
            <th>세션 기록</th>
            <th>시험</th>
          </tr>
        </thead>
        <tbody>
          {rules.map((r) => (
            <RuleRow key={r.id} rule={r} tested={results[r.id]} testing={busyId === r.id} onTest={(id) => void runTest(id)} />
          ))}
        </tbody>
      </table>
    </div>
  );
}
