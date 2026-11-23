// 문자 초안 카드(Task 83 — notify.draft_message 의 card{kind:"outreach_draft"}). 카드 자료에 번호는 없다.
// 받는 사람(이름·담당·협력사) · 채널 · 글(+번역)을 점선 상자에. 「승인 받기」면 [버리기][고치기][보내기] — [보내기]는 연락처 대화 칸과 같다:
// 한 번 누름 = 요청 하나, 답이 오고 그 줄을 다시 읽을 때까지 잠김, 결과 글은 서버 판정 그대로(labels.outcomeLabel), 나갔는지 모르면
// SEND_UNKNOWN. 그 줄이 이미 초안이 아니면(보냈음·버렸음 — 카드를 그릴 때 한 번 읽거나, 409·404 뒤에 다시 읽어 안다) 단추 대신 지금 상태 한 줄.
import { useEffect, useRef, useState } from 'react';
import { useWindows } from '../../../os/windowStore';
import { ApiError } from '../../../shared/api';
import { channelLabel, outcomeLabel, SEND_UNKNOWN, senderTag, statusLabel, type Label } from '../../../shared/outreach/labels';
import { outreachApi, sendOutcomeUnknown, type Message, type Outcome } from '../../../shared/outreach/outreachApi';
import Button from '../../../shared/ui/Button';
import { asNum, asObj, asText, Card, type CardProps } from './Card';
import './outreachCards.css';

const GONE = '이 초안은 이제 없습니다(버렸거나 지웠습니다)';

/** 카드 contact {name, role_title, company} → 「박현장 · 골조 팀장 · 대한골조」. 없으면 null. */
export function contactLine(v: unknown): string | null {
  const c = asObj(v);
  const parts = [asText(c.name), asText(c.role_title), asText(c.company)].filter(Boolean);
  return parts.length ? parts.join(' · ') : null;
}

/** needs_approval → 머리 줄 끝 글(알림 설정의 권한 이름). 칸이 없으면 적지 않는다. */
export const permissionText = (v: unknown) => (v === true ? '승인 받기' : v === false ? '위임' : undefined);

/** 판정 글. 모르는 판정에 글도 없으면 코드 그대로(빈 줄로 그리지 않는다). */
export function said(o: Outcome): Label {
  const l = outcomeLabel(o);
  return l.text ? l : { text: o.code, tone: l.tone };
}

/** 그 줄의 지금 모습: 그 사람과의 대화에서 id 바로 앞까지 하나를 읽는다 — 그 줄이면 그것, 아니면 null(없음). */
async function readRow(sid: number, contactId: number, id: number): Promise<Message | null> {
  const t = await outreachApi.thread(sid, contactId, { before: id + 1, limit: 1 });
  const m = t.messages.at(-1);
  return m !== undefined && m.id === id ? m : null;
}
const tryRead = (sid: number, contactId: number, id: number) => readRow(sid, contactId, id).catch(() => undefined);

/** undefined = 모름(읽기 전·읽지 못함 — 카드 자료로 그림), null = 없음, Message = 지금 모습. */
type Now = Message | null | undefined;

function stateLine(now: Now): Label | null {
  if (now === null) return { text: `지금 상태: ${GONE}`, tone: 'muted' };
  if (now === undefined || now.status === 'draft') return null;
  const s = statusLabel(now);
  return { text: `지금 상태: ${s.text} · ${senderTag(now)}`, tone: s.tone };
}

/** 줄 하나에 한 번에 요청 하나. 끝나면 그 줄을 다시 읽은 뒤에 잠금을 푼다(대화 칸의 useActions 와 같은 차례). */
function useDraftRow(sid: number | null, contactId: number | null, id: number | null) {
  const [now, setNow] = useState<Now>(undefined);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<Label | null>(null);
  const inFlight = useRef(false);
  const known = sid !== null && contactId !== null && id !== null;

  useEffect(() => {
    if (sid === null || contactId === null || id === null) return;
    let live = true;
    void tryRead(sid, contactId, id).then((m) => live && m !== undefined && setNow(m));
    return () => {
      live = false;
    };
  }, [sid, contactId, id]);

  async function run(verb: string, work: (sid: number, id: number) => Promise<void>) {
    if (!known || inFlight.current) return;
    inFlight.current = true;
    setBusy(verb);
    setNote(null);
    let stale: string | null = null;
    try {
      await work(sid, id);
    } catch (e) {
      // 이미 초안이 아님(409)·없음(404): 다시 읽은 지금 상태가 말한다. 그 밖은 서버 글 그대로.
      if (e instanceof ApiError && (e.status === 409 || e.status === 404)) stale = e.message;
      else setNote({ text: e instanceof Error && e.message ? e.message : '요청을 처리할 수 없습니다.', tone: 'bad' });
    }
    const fresh = await tryRead(sid, contactId, id);
    if (fresh !== undefined) setNow(fresh);
    else if (stale) setNote({ text: stale, tone: 'bad' });
    inFlight.current = false;
    setBusy(null);
  }

  const send = () =>
    run('send', async (s, i) => {
      let r;
      try {
        r = await outreachApi.send(s, i);
      } catch (e) {
        // 답이 오지 않았다·서버 오류·읽지 못한 답: 나갔을 수도 있다 — 「실패」가 아니라 「모름」, 다시 읽은 줄이 상태를 말한다.
        if (sendOutcomeUnknown(e)) return void setNote({ text: SEND_UNKNOWN, tone: 'warn' });
        throw e;
      }
      setNow(r.message);
      if (r.outcome) setNote(said(r.outcome));
    });
  const discard = () =>
    run('discard', async (s, i) => {
      await outreachApi.remove(s, i);
      setNow(null);
    });
  return { now, busy, note, send, discard };
}

export default function OutreachDraftCard({ data }: CardProps) {
  const sid = asNum(data.schedule_id);
  const id = asNum(data.message_id);
  const contactId = asNum(asObj(data.contact).id);
  const { now, busy, note, send, discard } = useDraftRow(sid, contactId, id);
  const channel = now?.channel ?? asText(data.channel);
  const body = now ? now.body : asText(data.body);
  const bodyKo = now ? now.body_ko : asText(data.body_ko);
  const who = contactLine(data.contact);
  const state = stateLine(now);
  // 지금 상태가 이미 같은 말을 하면(확인 필요 등) 결과 글을 한 번 더 적지 않는다 — 대화 칸의 말풍선과 같다.
  const shown = note && !(now && note.text === statusLabel(now).text) ? note : null;
  const canAct = data.needs_approval === true && state === null && sid !== null && id !== null && contactId !== null;
  const title = channel === 'sms' || channel === 'kakao' ? `${channelLabel(channel)} 초안` : '연락 초안';
  const locked = busy !== null;
  return (
    <Card title={title} extra={permissionText(data.needs_approval)}>
      <dl className="ch-kv">
        <div>
          <dt>받는 사람</dt>
          <dd className="ch-wrap">{who ?? '알 수 없음'}</dd>
        </div>
      </dl>
      <div className="oc-draft">
        <p className="oc-body">{body}</p>
        {bodyKo && (
          <p className="oc-ko">
            <span className="oc-ko-tag">번역</span>
            <span>{bodyKo}</span>
          </p>
        )}
      </div>
      {state && <p className={`oc-line is-${state.tone}`}>{state.text}</p>}
      <p role="status" className={`oc-line${shown ? ` is-${shown.tone}` : ''}`}>{shown?.text ?? ''}</p>
      {canAct && (
        <div className="ch-actions oc-acts">
          <Button disabled={locked} onClick={() => void discard()}>버리기</Button>
          <Button disabled={locked} onClick={() => useWindows.getState().open('contacts', { id: String(sid), contact: String(contactId), tab: 'messages' })}>
            고치기
          </Button>
          <Button variant="primary" disabled={locked} onClick={() => void send()}>
            {busy === 'send' ? '보내는 중…' : '보내기'}
          </Button>
        </div>
      )}
    </Card>
  );
}
