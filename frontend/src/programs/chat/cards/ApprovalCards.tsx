import { useEffect, useState } from 'react';
import { useWindows } from '../../../os/windowStore';
import Badge, { type Tone } from '../../../shared/ui/Badge';
import Button from '../../../shared/ui/Button';
import { getApproval, type ApprovalState } from '../chatApi';
import { asList, asNum, asObj, asText, Card, reasonLabel, reasonTone, ruleLine, SummaryLines, type CardProps } from './Card';

const by = (name: string | null) => (name ? ` · ${name}` : '');

/** 지금 결정을 글과 색으로. 대기 중이면 null(카드의 「결정을 기다립니다」가 그대로 보인다). */
function decision(a: ApprovalState): [string, Tone] | null {
  switch (a.status) {
    case 'approved':
      return [`승인됨${by(a.decided_by)}`, 'success'];
    case 'rejected':
      return [`${a.retry ? '다시 짜기로 거부됨' : '거부됨'}${by(a.decided_by)}`, 'danger'];
    case 'conflict':
      return ['그 사이 일정이 바뀌어 반영하지 못함', 'warning'];
    case 'auto':
      return ['자동 적용됨', 'info'];
    default:
      return null;
  }
}

/** 승인 건의 지금 상태(다시 연 대화에서도 결정이 보이게). 못 읽으면 null. */
function useApprovalState(id: number | null): ApprovalState | null {
  const [state, setState] = useState<ApprovalState | null>(null);
  useEffect(() => {
    if (id === null) return;
    let live = true;
    getApproval(id).then(
      (a) => live && setState(a),
      () => {},
    );
    return () => {
      live = false;
    };
  }, [id]);
  return state;
}

/** 승인 요청(approval 사건, Task 11): 제목·사유 배지·내 규칙(summary.rule, Task 35)·요약 숫자·지금 결정·[승인함에서 보기]. */
export function ApprovalCard({ data }: CardProps) {
  const id = asNum(data.id);
  const reasons = asList(data.reasons).map(asText).filter(Boolean);
  const state = useApprovalState(id);
  const decided = state && decision(state);
  const rule = ruleLine(asObj(data.summary).rule);
  return (
    <Card title="승인 요청" extra={decided ? <Badge tone={decided[1]}>{decided[0]}</Badge> : '승인함에서 결정을 기다립니다'}>
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
      {rule && <p className="ch-wrap">{rule}</p>}
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
