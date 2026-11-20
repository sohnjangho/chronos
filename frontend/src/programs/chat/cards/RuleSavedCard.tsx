import { asText, ruleLine, type CardProps } from './Card';
import './cards2.css';

/** 바로 저장된 분야 규칙(rules.propose 의 rule_saved 카드, Task 35): 「내 규칙 저장: <글> (분야 전체)」 한 줄. */
export default function RuleSavedCard({ data }: CardProps) {
  return (
    <div className="ch-line-card">
      <span className="ch-rule ch-wrap">{ruleLine(data.rule) ?? `내 규칙을 저장했습니다${asText(data.approval_id) ? ` (승인 건 ${asText(data.approval_id)})` : ''}`}</span>
    </div>
  );
}
