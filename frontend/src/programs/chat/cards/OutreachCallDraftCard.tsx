// 전화 초안 카드(Task 83 — notify.draft_call 의 card{kind:"outreach_call_draft"}). 카드 자료에 번호는 없다.
// 받는 사람 · 통화 목적 · 물어볼 것 · 말하지 않을 것 · 언어. [전화 걸기 창 열기]는 연락처 창의 그 사람 통화 탭을 그 통화로 연다
// (거는 것은 그 창에서 사람이 — 이 카드는 전화를 걸지 않는다).
import { useWindows } from '../../../os/windowStore';
import Button from '../../../shared/ui/Button';
import { asList, asNum, asObj, asText, Card, type CardProps } from './Card';
import { contactLine, permissionText } from './OutreachDraftCard';
import './outreachCards.css';

/** 연락처 언어 코드 → 이름(연락처 창의 언어 목록과 같은 넷). 모르는 코드는 그대로. */
const LANGUAGE: Readonly<Record<string, string>> = { ko: '한국어', en: '영어', zh: '중국어', vi: '베트남어' };

const texts = (v: unknown) => asList(v).map(asText).filter(Boolean);

export default function OutreachCallDraftCard({ data }: CardProps) {
  const sid = asNum(data.schedule_id);
  const callId = asNum(data.call_id);
  const contactId = asNum(asObj(data.contact).id);
  const questions = texts(data.questions);
  const avoid = texts(data.avoid);
  const language = asText(data.language);
  return (
    <Card title="전화 초안" extra={permissionText(data.needs_approval)}>
      <dl className="ch-kv oc-kv">
        <div>
          <dt>받는 사람</dt>
          <dd className="ch-wrap">{contactLine(data.contact) ?? '알 수 없음'}</dd>
        </div>
        <div>
          <dt>통화 목적</dt>
          <dd className="ch-wrap">{asText(data.purpose) || '없음'}</dd>
        </div>
        <div>
          <dt>물어볼 것</dt>
          <dd>
            {questions.length ? (
              <ol className="oc-list">
                {questions.map((q, i) => (
                  <li key={i}>{q}</li>
                ))}
              </ol>
            ) : (
              '없음'
            )}
          </dd>
        </div>
        <div>
          <dt>말하지 않을 것</dt>
          <dd>
            {avoid.length ? (
              <ul className="oc-list">
                {avoid.map((a, i) => (
                  <li key={i}>{a}</li>
                ))}
              </ul>
            ) : (
              '없음'
            )}
          </dd>
        </div>
        {language && (
          <div>
            <dt>언어</dt>
            <dd>{LANGUAGE[language] ?? language}</dd>
          </div>
        )}
      </dl>
      {sid !== null && callId !== null && contactId !== null && (
        <div className="ch-actions oc-acts">
          <Button
            variant="primary"
            onClick={() => useWindows.getState().open('contacts', { id: String(sid), contact: String(contactId), tab: 'calls', call: String(callId) })}
          >
            전화 걸기 창 열기
          </Button>
        </div>
      )}
    </Card>
  );
}
