import { useState } from 'react';
import Button from '../../../shared/ui/Button';
import { VisualDialog, VisualPanel } from '../../../shared/visual/VisualFrame';
import { getVisual } from '../../../shared/visual/visualApi';
import { asNum, asText, Card, type CardProps } from './Card';

/**
 * 보고서용 그림(visual.make 의 visual 카드, Task 44): 저장된 그림을 id 로 읽어 보인다(Liner HTML 은 sandbox iframe,
 * 대조 실패면 우리 그림과 까닭). [크게 보기]는 같은 그림을 대화상자에 크게. 값은 서버가 저장된 일정에서 계산한 표 그대로다.
 */
export default function VisualCard({ data }: CardProps) {
  const [big, setBig] = useState(false);
  const title = asText(data.title);
  const sid = asNum(data.schedule_id);
  const vid = asNum(data.visual_id);
  if (sid === null || vid === null) return <div className="ch-line-card is-muted ch-wrap">그림을 찾을 수 없습니다.</div>;
  return (
    <Card title={`보고서용 그림 — ${title}`} extra={<Button onClick={() => setBig(true)}>크게 보기</Button>}>
      <VisualPanel key={vid} load={() => getVisual(sid, vid)} height={460} />
      {big && (
        <VisualDialog onClose={() => setBig(false)}>
          <VisualPanel load={() => getVisual(sid, vid)} height={640} />
        </VisualDialog>
      )}
    </Card>
  );
}
