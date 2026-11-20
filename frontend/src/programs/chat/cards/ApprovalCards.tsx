import { useWindows } from '../../../os/windowStore';
import Badge from '../../../shared/ui/Badge';
import Button from '../../../shared/ui/Button';
import { asList, asNum, asText, Card, reasonLabel, reasonTone, SummaryLines, type CardProps } from './Card';

/** 승인 요청(approval 사건, Task 11): 제목·사유 배지·요약 숫자·[승인함에서 보기]. */
export function ApprovalCard({ data }: CardProps) {
  const id = asNum(data.id);
  const reasons = asList(data.reasons).map(asText).filter(Boolean);
  return (
    <Card title="승인 요청" extra="승인함에서 결정을 기다립니다">
      <p className="ch-card-title ch-wrap">{asText(data.title)}</p>
      {reasons.length > 0 && (
        <div className="ch-badges">
          {reasons.map((r) => (
            <Badge key={r} tone={reasonTone(r)}>
              {reasonLabel(r)}
            </Badge>
          ))}
        </div>
      )}
      <SummaryLines summary={data.summary} />
      {id !== null && (
        <div className="ch-actions">
          <Button variant="primary" onClick={() => useWindows.getState().open('approvals', { id: String(id) })}>
            승인함에서 보기
          </Button>
        </div>
      )}
    </Card>
  );
}

/** 자동 적용(auto_applied 카드): 승인 없이 저장한 버전과 요약 숫자. */
export function AutoAppliedCard({ data }: CardProps) {
  const version = asNum(data.version);
  const count = asNum(data.count);
  const head = ['자동으로 저장했습니다', version !== null && `버전 ${version}`, count !== null && `바뀐 액티비티 ${count}개`].filter(Boolean).join(' · ');
  return (
    <Card title="자동 적용">
      <p className="ch-card-title">{head}</p>
      <SummaryLines summary={data.summary} />
    </Card>
  );
}
