// 하네스 규칙 목록: 묶음(일정 계산 · 에이전트 루프 · 외부 정보 · 권한 · 가져오기·생성 · 현장 · 연락 하네스) + 찾기 + [차단 시험].
// 「연락 하네스」 묶음(Task 98)은 규칙 줄이 아니라 상황 격자(OutreachGrid)로 그린다 — 같은 묶음 고르기·찾기를 쓴다.
// 시험 결과(관측값)는 접힌 나무로 보인다(화면 검수 3).
import { useState } from 'react';
import Badge from '../../shared/ui/Badge';
import { devApi, type HarnessRule, type HarnessTestOut, type OutreachGridOut } from './devApi';
import OutreachGrid from './OutreachGrid';
import RawBlock from './RawBlock';

const GROUPS = ['일정 계산', '에이전트 루프', '외부 정보', '권한', '가져오기·생성', '현장', '기타'];
/** 예전 서버는 group 이 없다 — 위치(area)로 묶는다. */
const FROM_AREA: Record<string, string> = { '조건 점검': '일정 계산', 승인: '권한', 루프: '에이전트 루프', 입력: '에이전트 루프' };
const groupOf = (r: HarnessRule) => r.group ?? FROM_AREA[r.area] ?? '기타';
const NO_RECORD = '이 규칙은 실행 기록에 남는 값이 없어 세지 않습니다.';

function Counts({ rule }: { rule: HarnessRule }) {
  const { passed_count: passed, blocked_count: blocked } = rule;
  if (passed === null && blocked === null) {
    return <span className="dc-muted" title={NO_RECORD}>기록 없음</span>;
  }
  return (
    <>
      {passed !== null && <Badge tone="success">{`통과 ${passed}`}</Badge>}
      {blocked !== null && blocked > 0 && <Badge tone="danger">{`차단 ${blocked}`}</Badge>}
    </>
  );
}

function TestResult({ tested }: { tested: HarnessTestOut }) {
  return (
    <div className="dc-harness-test-res" role="status">
      <div className="dc-harness-test-head">
        {tested.blocked ? <Badge tone="danger">차단 시험 완료</Badge> : <Badge tone="warning">차단 안 됨</Badge>}
        {tested.engine === 'live_harness' && <Badge tone="success">실엔진 검증</Badge>}
        {tested.elapsed_ms !== undefined && <Badge tone="neutral">{`${tested.elapsed_ms}ms`}</Badge>}
        <span>{`시뮬레이션 입력: ${tested.simulated_input}`}</span>
      </div>
      <RawBlock label="관측값" value={tested.model_feedback} />
    </div>
  );
}

interface RowProps {
  rule: HarnessRule;
  tested: HarnessTestOut | undefined;
  testing: boolean;
  onTest(id: string): void;
}

function RuleRow({ rule, tested, testing, onTest }: RowProps) {
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
        {tested && <TestResult tested={tested} />}
      </td>
      <td>
        <div className="dc-cat-code">
          <code>{rule.code}</code>
          <span className="dc-tag is-warn">{rule.mode}</span>
        </div>
      </td>
      <td className="dc-cat-stat">
        <Badge tone="success">구현</Badge>
      </td>
      <td>
        <div className="dc-cat-counts">
          <Counts rule={rule} />
        </div>
      </td>
      <td className="dc-cat-act">
        <button type="button" className="dc-btn" disabled={testing} onClick={() => onTest(rule.id)}>
          {testing ? '시험 중…' : '차단 시험'}
        </button>
      </td>
    </tr>
  );
}

const matches = (r: HarnessRule, q: string) => !q || [r.id, r.title, r.description, r.code, r.area].some((t) => t.toLowerCase().includes(q));

export default function HarnessRules({ rules, outreach }: { rules: HarnessRule[]; outreach?: OutreachGridOut }) {
  const [group, setGroup] = useState('전체');
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<Record<string, HarnessTestOut>>({});
  const [busyId, setBusyId] = useState<string | null>(null);
  const q = query.trim().toLowerCase();
  const shown = rules.filter((r) => (group === '전체' || groupOf(r) === group) && matches(r, q));
  const present = GROUPS.filter((g) => rules.some((r) => groupOf(r) === g));
  const cells = outreach ? outreach.rows.reduce((n, r) => n + Object.values(r.cells).filter((c) => c.runnable).length, 0) + outreach.channel_only.length : 0;
  const showRules = group !== outreach?.group;
  const showGrid = outreach && (group === '전체' || group === outreach.group);

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
    <>
      <div className="dc-harness-tools">
        <div className="dc-chip-bar" role="group" aria-label="하네스 묶음 필터">
          {['전체', ...present].map((g) => (
            <button key={g} type="button" className={`dc-mode-btn${group === g ? ' is-on' : ''}`} aria-pressed={group === g} onClick={() => setGroup(g)}>
              {g === '전체' ? `전체 ${rules.length + cells}` : `${g} ${rules.filter((r) => groupOf(r) === g).length}`}
            </button>
          ))}
          {outreach && (
            <button type="button" className={`dc-mode-btn${group === outreach.group ? ' is-on' : ''}`} aria-pressed={group === outreach.group}
              onClick={() => setGroup(outreach.group)}>
              {`${outreach.group} ${cells}`}
            </button>
          )}
        </div>
        <input type="search" className="dc-search" aria-label="규칙 찾기" placeholder="번호 · 규칙 · 코드로 찾기" value={query} onChange={(e) => setQuery(e.target.value)} />
      </div>
      {!showRules ? null : shown.length === 0 ? (
        <p className="dc-empty">찾는 규칙이 없습니다.</p>
      ) : (
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
          {GROUPS.filter((g) => shown.some((r) => groupOf(r) === g)).map((g) => (
            <tbody key={g} aria-label={`${g} 규칙`}>
              <tr className="dc-cat-group">
                <th colSpan={7} scope="rowgroup">{`${g} · ${shown.filter((r) => groupOf(r) === g).length}개`}</th>
              </tr>
              {shown
                .filter((r) => groupOf(r) === g)
                .map((r) => (
                  <RuleRow key={r.id} rule={r} tested={results[r.id]} testing={busyId === r.id} onTest={(id) => void runTest(id)} />
                ))}
            </tbody>
          ))}
        </table>
      )}
      {showGrid && <OutreachGrid grid={outreach} query={q} />}
    </>
  );
}
