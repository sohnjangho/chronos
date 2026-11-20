import Badge from '../../../shared/ui/Badge';
import { dotDate } from '../labels';
import { asList, asNum, asObj, asText, Card, type CardProps } from './Card';
import './cards2.css';

/** 가정을 받친 근거 번호(evidence_id) — 대화 글의 "[근거 n]" 과 근거 카드의 번호와 같다. */
function Cites({ ids }: { ids: unknown }) {
  const list = asList(ids).map(asNum).filter((n): n is number => n !== null);
  if (list.length === 0) return null;
  return (
    <span className="ch-cites">
      {list.map((n) => (
        <span key={n} className="ch-cite">{`[근거 ${n}]`}</span>
      ))}
    </span>
  );
}

/**
 * 생성 결과 카드(generate.run 의 generation_result): 준공·액티비티·크리티컬·가정(받친 근거 번호)·남은 위반·점검하지 않은 조건.
 * 자동 점검 안 된 조건은 따로 세고 통과라고 쓰지 않는다.
 */
export default function ResultCard({ data }: CardProps) {
  const ok = data.ok === true;
  const assumptions = asList(data.assumptions).map(asObj);
  const violations = asList(data.violations).map((v) => asText(asObj(v).message)).filter(Boolean);
  const conflict = asList(data.conflict).map(asText).filter(Boolean);
  const uncheckable = asNum(data.uncheckable_count) ?? 0;
  const invalid = asNum(data.invalid_count) ?? 0;
  const finish = dotDate(data.finish);
  return (
    <Card title="결과" tone={ok ? undefined : 'warn'} extra={ok ? undefined : <Badge tone="warning">초안에 문제가 남음</Badge>}>
      {asText(data.reason) && <p className="ch-wrap">{asText(data.reason)}</p>}
      <ul className="ch-plain ch-lines">
        {finish && (
          <li>
            준공 <b>{finish}</b>
          </li>
        )}
        <li>
          액티비티 <b>{asNum(data.activity_count) ?? 0}</b>개 · 크리티컬 <b>{asNum(data.critical_count) ?? 0}</b>개
        </li>
        {assumptions.map((a, i) => (
          <li key={i} className="ch-wrap">
            가정: {asText(a.label)} <b>{asText(a.value)}</b>
            <Cites ids={a.evidence_ids} />
          </li>
        ))}
        {violations.length > 0 && <li>남은 위반 {violations.length}개</li>}
        {uncheckable > 0 && <li>자동 점검 안 됨 {uncheckable}개</li>}
        {invalid > 0 && <li>형식이 틀린 조건 {invalid}개</li>}
        {conflict.length > 0 && <li className="ch-wrap">서로 맞지 않는 조건: {conflict.join(', ')}</li>}
      </ul>
      {violations.length > 0 && (
        <ul className="ch-plain ch-violations">
          {violations.map((m, i) => (
            <li key={i} className="ch-wrap">{m}</li>
          ))}
        </ul>
      )}
    </Card>
  );
}
