// 위임으로 보낸(건) 결과 카드(Task 83 — notify.send_message·place_call 의 card{kind:"outreach_sent"}). 카드 자료에 번호는 없다.
// [에이전트 발신 · 위임] · 받는 사람 · 문의 판정 글 그대로(labels.outcomeLabel — 「확인 필요」는 보냄이 아니고, 막힌 판정은 그 까닭).
// 단추는 없다(이미 문을 지난 결과다 — 다시 보내기는 연락처 창에서).
import { channelLabel } from '../../../shared/outreach/labels';
import { asText, Card, type CardProps } from './Card';
import { contactLine, said } from './OutreachDraftCard';
import './outreachCards.css';

const channelText = (c: string) => (c === 'sms' || c === 'kakao' ? channelLabel(c) : c === 'call' ? '전화' : c || undefined);

export default function OutreachSentCard({ data }: CardProps) {
  const result = said({ code: asText(data.outcome), message: asText(data.message), scheduled_at: null });
  return (
    <Card title="연락 결과" extra={channelText(asText(data.channel))}>
      <p className="oc-tag">[에이전트 발신 · 위임]</p>
      <dl className="ch-kv">
        <div>
          <dt>받는 사람</dt>
          <dd className="ch-wrap">{data.contact === null ? '지워진 연락처' : (contactLine(data.contact) ?? '알 수 없음')}</dd>
        </div>
      </dl>
      {result.text && <p className={`oc-line is-${result.tone}`}>{result.text}</p>}
    </Card>
  );
}
