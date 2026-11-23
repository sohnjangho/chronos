// 대화 칸 아래 입력창(Task 79, 시안 ①) — ThreadPane 의 composer 자리(ComposerSlotProps)에 들어간다.
// 위에서부터: 시험 모드 띠 · 「문자 | 카카오톡」 + 「연결할 작업: … ▾」 + 글자 수 · (잠긴 까닭) · 글 · 결과 줄 · [에이전트에게 초안 맡기기](자리만 —
// Task 83) … [보내기]. [보내기]는 누른 때부터 답이 오고 대화를 다시 읽을 때까지 잠긴다(두 번 눌러도, Enter 를 눌러 두어도 요청 하나).
// 글은 서버가 줄을 만들었다고 답했을 때만 비운다. 결과 줄은 서버 판정 그대로(labels.ts 의 statusLabel·outcomeLabel) — 미리 「보냄」을
// 그리지 않고, 「확인 필요」를 보냄으로, 「잠시 뒤 다시」를 「이미 보냈습니다」로 바꾸지 않는다. 줄의 상태는 다시 읽은 대화가 그린다.
import { useEffect, useId, useRef, useState } from 'react';
import { ApiError } from '../../shared/api';
import { channelLabel, outcomeLabel, statusLabel, type Label } from '../../shared/outreach/labels';
import { outreachApi, type MessageChannel, type MessageIn, type MessageResult } from '../../shared/outreach/outreachApi';
import Button from '../../shared/ui/Button';
import ActivityPicker from './ActivityPicker';
import { getNotifyStatus, KIND_LABEL, type NotifyStatus, type PersonBrief } from './contactsApi';
import { SEND_UNKNOWN } from './MessageThread';
import { SMS_BYTES, smsLength } from './smsLength';
import type { ComposerSlotProps } from './ThreadPane';
import './composer.css';

export const KAKAO_LOCKED = '카카오톡은 채널·문안 승인 뒤 쓸 수 있습니다 — 지금은 문자로 보냅니다';
/** 시험 모드 띠. 알림 상태(GET /api/notify/status)는 사람마다 허용 번호인지 알려 주지 않아 「이 사람에게는」이라고 단정하지 않는다. */
export const TEST_BAND = '시험 모드 — 허용 번호가 아니면 실제로 나가지 않고 기록만 남습니다';
const NO_PHONE = '번호 없음 — 번호를 넣은 뒤에 보낼 수 있습니다';
const BAD_PHONE = '번호 오류 — 번호를 고친 뒤에 보낼 수 있습니다';
const COUNT_RULE = `한글·한자·전각 글자·이모지 같은 글자는 2바이트, 영문·숫자·기호·빈칸·줄바꿈은 1바이트로 셉니다(앞뒤 빈칸은 세지 않음). ${SMS_BYTES}바이트까지 문자 1건, 넘으면 장문 문자입니다.`;
const CHANNELS: MessageChannel[] = ['sms', 'kakao'];

/** 판정이 셋(보냄·실패·확인 필요) 중 하나면 그 글, 그 밖(예약·막힘·잠시 뒤 다시)은 「줄이 어떻게 됐나 — 문의 까닭」. */
const OWN_WORDS = new Set(['accepted', 'queued', 'failed', 'unsure']);
export function sendResult(r: MessageResult): Label {
  if (!r.outcome) return statusLabel(r.message);
  const o = outcomeLabel(r.outcome);
  if (OWN_WORDS.has(r.outcome.code)) return o;
  return { text: `${statusLabel(r.message).text} — ${r.outcome.message}`, tone: o.tone };
}

/** 글을 쓸 수 없는 까닭(번호 없음 · 수신 거부 · 번호 오류). */
function inputLock(person: PersonBrief, blocked: string | null): string | null {
  if (!person.has_phone) return NO_PHONE;
  if (blocked) return blocked;
  if (person.phone_invalid) return BAD_PHONE;
  return null;
}

/** 통로마다 고를 수 없는 까닭(없으면 null). 카카오톡은 연결이 준비되기 전(지금은 늘)에는 잠긴다. 번호 없음 등은 inputLock 이 먼저 말한다. */
function channelLocks(person: PersonBrief, status: NotifyStatus | null | undefined): Record<MessageChannel, string | null> {
  const kind = person.phone_kind;
  return {
    sms: person.channels.includes('sms')
      ? null
      : kind && kind !== 'mobile'
        ? `${KIND_LABEL[kind]} 번호라 문자를 받을 수 없습니다`
        : '이 사람은 문자를 받지 않게 되어 있습니다',
    kakao: status?.kakao_ready !== true ? KAKAO_LOCKED : person.channels.includes('kakao') ? null : '이 사람은 카카오톡을 받지 않게 되어 있습니다',
  };
}

function counterText(text: string, channel: MessageChannel | null): string {
  const n = smsLength(text);
  if (channel === 'kakao') return `${n.chars}자`;
  return n.kind === 'sms' ? `${n.chars}자 · ${n.bytes}/${SMS_BYTES}바이트 · 문자 1건` : `${n.chars}자 · ${n.bytes}바이트 · 장문 문자로 나갑니다`;
}

/** [보내기] 한 번 = 요청 하나. 답이 오고 대화를 다시 읽을 때까지 busy. 서버가 줄을 만들었으면 곧바로 made() 를 부른다. */
function useSend(scheduleId: number, onSent: () => Promise<void>) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Label | null>(null);
  const inFlight = useRef(false);
  async function send(body: MessageIn, made: () => void) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setResult(null);
    try {
      const r = await outreachApi.create(scheduleId, body);
      made();
      setResult(sendResult(r));
    } catch (e) {
      // 답을 받지 못함: 나갔는지 모른다(실패가 아니다) — 글은 그대로, 다시 읽은 대화가 상태를 말한다.
      if (e instanceof ApiError && e.status === 0) setResult({ text: SEND_UNKNOWN, tone: 'warn' });
      else setResult({ text: e instanceof Error && e.message ? e.message : '요청을 처리할 수 없습니다.', tone: 'bad' });
    }
    try {
      await onSent();
    } catch {
      // 다시 읽기의 실패는 대화 칸이 보인다.
    }
    inFlight.current = false;
    setBusy(false);
  }
  return { busy, result, send };
}

export default function Composer({ scheduleId, person, compose, activity, blocked, onSent }: ComposerSlotProps) {
  const [status, setStatus] = useState<NotifyStatus | null | undefined>(undefined);
  const [text, setText] = useState(compose ?? '');
  const [activityId, setActivityId] = useState<string | null>(activity ?? null);
  const [picked, setPicked] = useState<MessageChannel>('sms');
  const { busy, result, send } = useSend(scheduleId, onSent);
  const ids = useId();

  useEffect(() => {
    let live = true;
    void getNotifyStatus().then((s) => live && setStatus(s));
    return () => {
      live = false;
    };
  }, []);
  // 다른 프로그램이 같은 사람으로 다시 열며 넘긴 글·작업
  useEffect(() => {
    if (compose !== undefined) setText(compose);
  }, [compose]);
  useEffect(() => {
    if (activity !== undefined) setActivityId(activity);
  }, [activity]);

  const lock = inputLock(person, blocked);
  const locks = channelLocks(person, status);
  const channel: MessageChannel | null = lock ? null : !locks[picked] ? picked : (CHANNELS.find((c) => !locks[c]) ?? null);
  const reasonOf = (c: MessageChannel) => (lock ? lock : locks[c]);
  const reasonId = (c: MessageChannel | 'lock') => `${ids}-${c}`;
  const describe = lock ? reasonId('lock') : channel === null ? reasonId('sms') : undefined;
  const canSend = !busy && channel !== null && smsLength(text).chars > 0;

  async function submit() {
    if (!canSend || channel === null) return;
    const body: MessageIn = { contact_id: person.id, channel, body: text, ...(activityId ? { activity_id: activityId } : {}), send: true };
    await send(body, () => setText('')); // 서버가 줄을 만들었다 — 그 글은 이제 대화에 있다
  }

  return (
    <section className="cmp" aria-label="메시지 입력">
      {status?.test_mode && channel !== null && <p className="th-strip is-warn cmp-band">{TEST_BAND}</p>}
      <div className="cmp-body">
        <div className="cmp-line">
          <div role="group" aria-label="보낼 통로" className="cmp-seg">
            {CHANNELS.map((c) => (
              <button
                key={c}
                type="button"
                className="cmp-seg-item"
                aria-pressed={channel === c}
                disabled={busy || reasonOf(c) !== null}
                aria-describedby={reasonOf(c) ? (lock ? reasonId('lock') : reasonId(c)) : undefined}
                onClick={() => setPicked(c)}
              >
                {channelLabel(c)}
              </button>
            ))}
          </div>
          <ActivityPicker scheduleId={scheduleId} value={activityId} onChange={setActivityId} disabled={busy || channel === null} />
          {channel !== null && <span className="cmp-count" data-testid="sms-count" title={COUNT_RULE}>{counterText(text, channel)}</span>}
        </div>
        {lock ? (
          <p id={reasonId('lock')} className="cmp-lock">{lock}</p>
        ) : (
          CHANNELS.filter((c) => locks[c]).map((c) => (
            <p key={c} id={reasonId(c)} className="cmp-reason">{locks[c]}</p>
          ))
        )}
        <textarea
          className="ct-input ct-textarea cmp-text"
          aria-label="보낼 글"
          aria-describedby={describe}
          placeholder="메시지를 입력하세요"
          rows={3}
          value={text}
          disabled={channel === null}
          readOnly={busy}
          onChange={(e) => setText(e.target.value)}
        />
        <p role="status" className={`th-note cmp-result${result ? ` is-${result.tone}` : ''}`}>{result?.text ?? ''}</p>
        <div className="cmp-line">
          <Button disabled title="준비 중입니다">에이전트에게 초안 맡기기</Button>
          <Button variant="primary" className="cmp-send" disabled={!canSend} onClick={() => void submit()}>
            {busy ? '보내는 중…' : '보내기'}
          </Button>
        </div>
      </div>
    </section>
  );
}
