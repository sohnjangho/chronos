// 「전화 걸기」 창(Task 92, 시안 ③): 받는 사람 · 통화 목적 · 물어볼 것 · 말하지 않을 것 · 연결 · 언어 · 음성(고른 까닭) · 근무시간 줄(CallForm),
// [에이전트에게 다시 쓰게](대화로 보냄) [고치기] [전화 걸기]. 근무시간 밖이면 [전화 걸기] 대신 「지금은 근무시간 밖입니다 — [<다음 근무 시작>에 예약]」
// — 다음 근무 시작은 서버가 준 시각(주소록 자세히의 next_start, 문이 막아 둔 줄이면 그 제안이 아직 앞일 때 그것). 서버가 그 시각을 거절하면
// (지난 시각·공휴일) 그 글과 함께 다른 시각을 고르는 칸을 보인다. 근무시간을 읽지 못하면 그렇게 말하고 [전화 걸기]를 둔다(문이 정한다).
// 새 통화는 먼저 쓰고 [저장](초안 — 걸지 않음)한 뒤 그 초안을 확인하고 건다. [전화 걸기]는 진짜 전화로 이어진다: 한 번에 요청 하나(두 번 눌러도),
// 걸기 바로 전에 그 줄을 다시 읽어 보인 것과 다르면 걸지 않고 새 내용을 보인다(승인한 내용 = 거는 내용). 결과는 문의 판정 글 그대로이고,
// 답을 못 받으면(시간 초과 포함) 「…확인하지 못했습니다」(실패가 아니다) 뒤 다시 읽는다. 번호는 서버가 가려 주고 번호가 든 글은 서버가 막는다.
// 통화가 준비되지 않은 언어(Task 100 — 진단 P10 전)면 「이 언어는 통화가 준비되지 않았습니다 — 한국어로 겁니다」(서버가 한국어로 건다).
import { useEffect, useRef, useState } from 'react';
import { useWindows } from '../../os/windowStore';
import { ApiError } from '../../shared/api';
import {
  CALL_UNKNOWN, callOutcomeLabel, callSender, callStatusLabel, kstShort, outcomeLabel, SCHEDULE_UNKNOWN, type Label,
} from '../../shared/outreach/labels';
import { outreachApi, sendOutcomeUnknown, type Call, type CallLanguage, type CallPatch, type CallResult } from '../../shared/outreach/outreachApi';
import Button from '../../shared/ui/Button';
import { aheadOf } from './CallCard';
import { EditForm, formOf, formProblem, lines, Rows, type Form, HOURS_UNREAD } from './CallForm';
import { getPerson, type PersonBrief, type PersonDetail } from './contactsApi';
import XferDialog from './XferDialog';

export const TITLE = '전화 걸기';
export const CHANGED = '내용이 바뀌었습니다 — 확인한 뒤 다시 눌러 주세요';
export const UNREAD = '지금 상태를 읽지 못해 걸지 않았습니다 — 다시 눌러 주세요';
/** AI 전화가 되는 언어(서버 languages.CALLABLE 과 같다 — 음성 진단 P10 이 통과한 언어만, 11-24 영어). 나머지는 서버가 한국어로 건다. */
export const CALLABLE_LANGUAGES: ReadonlySet<string> = new Set(['ko', 'en']);
export const NOT_CALLABLE = '이 언어는 통화가 준비되지 않았습니다 — 한국어로 겁니다';
const PLACEABLE = new Set(['draft', 'blocked_hours']);
const RETRY_TIME = new Set(['past_time', 'outside_hours']); // 다른 시각을 고르면 되는 거절
const KST_MS = 9 * 3_600_000;
const errText = (e: unknown, fallback: string) => (e instanceof Error && e.message ? e.message : fallback);
/** 시간대 붙은 ISO → datetime-local 칸의 값(한국 시각). */
const kstLocal = (iso: string) => new Date(new Date(iso).getTime() + KST_MS).toISOString().slice(0, 16);

/** 보인 내용과 다시 읽은 내용이 같은가(걸기 전 확인). */
const same = (a: Call, b: Call) =>
  a.purpose === b.purpose && a.questions.join('\n') === b.questions.join('\n') && a.avoid.join('\n') === b.avoid.join('\n') &&
  a.language === b.language && (a.activity?.id ?? null) === (b.activity?.id ?? null) && a.voice_id === b.voice_id;

/** [전화 걸기]의 결과 줄: 줄에 넣음·실패·확인 필요는 문의 판정 그대로, 막혀 줄이 바뀌었으면 「<줄 상태> — <문의 글>」. */
function placeResult(r: CallResult): Label {
  const o = r.outcome;
  if (['queued', 'failed', 'unsure'].includes(o.code)) return callOutcomeLabel(o);
  const tone = outcomeLabel(o).tone;
  return r.call.status === 'draft' ? { text: o.message, tone } : { text: `${callStatusLabel(r.call).text} — ${o.message}`, tone };
}

/** [고치기]의 PATCH: 바꾼 칸만 — 서버가 가린 글([번호])이 다른 칸을 고칠 때 되써지지 않게(바꾸지 않은 칸은 보내지 않는다). */
function changedFields(row: Call, body: { purpose: string; questions: string[]; avoid: string[]; language: CallLanguage }, activity: string | null): CallPatch {
  const patch: CallPatch = {};
  if (body.purpose !== row.purpose) patch.purpose = body.purpose;
  if (body.questions.join('\n') !== row.questions.join('\n')) patch.questions = body.questions;
  if (body.avoid.join('\n') !== row.avoid.join('\n')) patch.avoid = body.avoid;
  if (body.language !== row.language) patch.language = body.language;
  if (activity !== (row.activity?.id ?? null)) patch.activity_id = activity;
  return patch;
}

/** 근무 밖이면 예약할 시각(찾지 못했으면 null). 근무 중이거나 근무시간을 아직·끝내 모르면 undefined — [전화 걸기], 문이 정한다. */
function scheduleAt(row: Call, detail: PersonDetail | null): string | null | undefined {
  if (!detail || detail.working_now) return undefined;
  return (row.status === 'blocked_hours' ? aheadOf(row.scheduled_at) : null) ?? detail.next_start;
}

interface Props {
  scheduleId: number;
  person: PersonBrief;
  /** 열 초안 id(없으면 새 통화를 쓴다) */
  callId: number | null;
  /** 걸 수 없는 까닭(수신 거부·번호 없음 …) */
  blocked: string | null;
  onClose(): void;
  /** 초안을 만들었거나 고쳤거나 걸었다 — 통화 목록을 다시 읽는다. */
  onChanged(): void;
}

/** 지금 이 창의 동작 하나(두 번 눌러도 하나). 요청마다 시간 한도가 있어(outreachApi) 잠금이 영원하지 않다. */
function useLock() {
  const [busy, setBusy] = useState<string | null>(null);
  const inFlight = useRef(false);
  const run = async (verb: string, work: () => Promise<void>) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(verb);
    try {
      await work();
    } finally {
      inFlight.current = false;
      setBusy(null);
    }
  };
  return { busy, run };
}

/** 사람 자세히(근무시간·음성)와 그 통화 줄. reread·show 는 순번을 올려 늦게 온 옛 읽기가 새 모습을 덮지 못하게 한다. */
function useCallData(scheduleId: number, personId: number, callId: number | null) {
  const [detail, setDetail] = useState<PersonDetail | null>(null);
  const [detailFailed, setDetailFailed] = useState(false);
  const [row, setRow] = useState<Call | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const seq = useRef(0);
  const alive = useRef(true);
  const readPerson = () =>
    getPerson(scheduleId, personId).then(
      (d) => alive.current && (setDetail(d), setDetailFailed(false)),
      () => alive.current && setDetailFailed(true), // 근무시간 줄은 「읽지 못했습니다」 — 걸지 말지는 문이 정한다
    );
  useEffect(() => {
    alive.current = true;
    void readPerson();
    if (callId !== null) {
      const mine = ++seq.current;
      outreachApi.getCall(scheduleId, callId).then(
        (r) => alive.current && mine === seq.current && setRow(r),
        (e: unknown) => alive.current && mine === seq.current && setLoadError(errText(e, '통화를 읽을 수 없습니다.')),
      );
    }
    return () => {
      alive.current = false;
    };
  }, [scheduleId, personId, callId]);
  const reread = async (id: number) => {
    const mine = ++seq.current;
    const fresh = await outreachApi.getCall(scheduleId, id);
    if (alive.current && mine === seq.current) setRow(fresh);
    return fresh;
  };
  const show = (r: Call) => {
    seq.current += 1;
    if (alive.current) setRow(r);
  };
  return { detail, detailFailed, row, loadError, reread, show, readPerson };
}
type CallData = ReturnType<typeof useCallData>;

/** [전화 걸기]·[예약]. 걸기는 바로 전에 그 줄을 다시 읽어 보인 것과 같을 때만 문에 넣는다. 끝나면 목록을 다시 읽게 한다. */
function useCallActions(scheduleId: number, data: CallData, run: ReturnType<typeof useLock>['run'], setNote: (n: Label | null) => void, onChanged: () => void) {
  const [pick, setPick] = useState<string | null>(null); // 서버가 시각을 거절했을 때 고를 다른 시각(datetime-local 값)
  const place = (shown: Call) =>
    run('place', async () => {
      setNote(null);
      let fresh: Call;
      try {
        fresh = await data.reread(shown.id);
      } catch {
        return setNote({ text: UNREAD, tone: 'warn' });
      }
      if (!PLACEABLE.has(fresh.status)) return; // 이미 걸었거나 예약됐다 — 지금 상태 줄이 말한다
      if (!same(shown, fresh)) return setNote({ text: CHANGED, tone: 'warn' });
      try {
        const r = await outreachApi.placeCall(scheduleId, shown.id);
        data.show(r.call);
        setNote(placeResult(r));
        if (r.call.status === 'blocked_hours') await data.readPerson(); // 문이 근무 밖이라 했다 — 근무시간을 다시 읽는다
      } catch (e) {
        // 답이 오지 않았다: 서버가 받아 걸었을 수도 있다 — 「실패」가 아니라 「모름」, 다시 읽은 줄이 상태를 말한다.
        setNote(sendOutcomeUnknown(e) ? { text: CALL_UNKNOWN, tone: 'warn' } : { text: errText(e, '요청을 처리할 수 없습니다.'), tone: 'bad' });
        await data.reread(shown.id).catch(() => undefined);
      }
      onChanged();
    });
  const schedule = (shown: Call, at: string) =>
    run('schedule', async () => {
      setNote(null);
      try {
        data.show(await outreachApi.scheduleCall(scheduleId, shown.id, at));
        setPick(null);
        setNote({ text: '예약했습니다 — 그 시각에 근무시간·시험 모드를 다시 확인한 뒤 겁니다.', tone: 'info' });
      } catch (e) {
        if (sendOutcomeUnknown(e)) setNote({ text: SCHEDULE_UNKNOWN, tone: 'warn' });
        else {
          setNote({ text: errText(e, '예약할 수 없습니다.'), tone: 'bad' });
          if (e instanceof ApiError && RETRY_TIME.has(e.code)) setPick(kstLocal(at));
        }
        await data.reread(shown.id).catch(() => undefined);
      }
      onChanged();
    });
  return { place, schedule, pick, setPick };
}

/** [에이전트에게 다시 쓰게]: 대화에 요청 글을 보낸다(이름·담당·협력사·초안 번호와 목적 — 서버가 번호를 가린 글). */
function rewrite(r: Call, person: PersonBrief) {
  const c = r.contact;
  const who = c ? `${c.name}(${[c.role_title, c.company].filter(Boolean).join(' · ')})` : person.name;
  const asked = r.questions.length ? ` 물어볼 것: ${r.questions.join(' / ')}.` : '';
  useWindows.getState().open('chat', { ask: `${who}에게 걸 전화 초안 #${r.id}의 목적과 물어볼 것을 다시 써 주세요. 지금 통화 목적: ${r.purpose}.${asked}` });
}

interface ViewProps {
  row: Call;
  /** 아직 걸 수 있는 줄(초안·근무시간 밖으로 막힘) */
  draftLike: boolean;
  /** 근무시간 밖이면 예약할 시각(찾지 못했으면 null), 아니면 undefined */
  at: string | null | undefined;
  hoursUnread: boolean;
  blocked: string | null;
  busy: string | null;
  pick: string | null;
  setPick(v: string): void;
  onSchedule(at: string): void;
}

/** 확인 보기의 아래: 지금 상태(이미 걸었거나 막혔으면) · 근무 밖 예약 줄 · 다른 시각 고르기 · 걸 수 없는 까닭. */
function ViewFoot({ row, draftLike, at, hoursUnread, blocked, busy, pick, setPick, onSchedule }: ViewProps) {
  const status = callStatusLabel(row);
  const sender = callSender(row);
  const off = busy !== null || blocked !== null;
  return (
    <>
      {!draftLike && <p className={`cl-state is-${status.tone}`}>{`지금 상태: ${status.text} · ${sender.tag}${sender.approver ? ` · ${sender.approver} 승인` : ''}`}</p>}
      {draftLike && row.status === 'blocked_hours' && <p className={`cl-state is-${status.tone}`}>{`지금 상태: ${status.text}`}</p>}
      {draftLike && hoursUnread && <p className="th-note is-warn">{`${HOURS_UNREAD} — [전화 걸기]를 누르면 근무시간은 서버가 다시 봅니다.`}</p>}
      {at !== undefined && (
        <p className="cl-off">
          {at ? '지금은 근무시간 밖입니다 — ' : '지금은 근무시간 밖이고 다음 근무 시작을 찾지 못했습니다 — 연락처의 근무시간을 확인해 주세요.'}
          {at && (
            <Button variant="primary" disabled={off} title={blocked ?? undefined} onClick={() => onSchedule(at)}>
              {busy === 'schedule' ? '예약하는 중…' : `${kstShort(at)}에 예약`}
            </Button>
          )}
        </p>
      )}
      {draftLike && pick !== null && (
        <p className="cl-off cl-pick">
          <label>
            다른 시각(한국 시각)
            <input type="datetime-local" className="ct-input" value={pick} disabled={off} onChange={(e) => setPick(e.target.value)} />
          </label>
          <Button disabled={off || pick === ''} onClick={() => onSchedule(`${pick}:00+09:00`)}>이 시각에 예약</Button>
        </p>
      )}
      {blocked && draftLike && <p className="th-note is-bad">{blocked}</p>}
    </>
  );
}

export default function CallDialog({ scheduleId, person, callId, blocked, onClose, onChanged }: Props) {
  const data = useCallData(scheduleId, person.id, callId);
  const { detail, row } = data;
  const [editing, setEditing] = useState(callId === null);
  const [form, setForm] = useState<Form>(() => formOf(null, 'ko'));
  const [formError, setFormError] = useState<string | null>(null);
  const [note, setNote] = useState<Label | null>(null);
  const { busy, run } = useLock();
  const { place, schedule, pick, setPick } = useCallActions(scheduleId, data, run, setNote, onChanged);
  // 새 통화의 언어는 그 사람의 언어로 시작한다(아직 아무것도 쓰지 않았을 때만).
  useEffect(() => {
    if (callId === null && detail) setForm((f) => (f.purpose || f.questions || f.avoid ? f : { ...f, language: detail.language }));
  }, [callId, detail]);

  const save = () =>
    run('save', async () => {
      const problem = formProblem(form);
      setFormError(problem);
      if (problem) return;
      const body = { purpose: form.purpose.trim(), questions: lines(form.questions), avoid: lines(form.avoid), language: form.language as CallLanguage };
      try {
        if (row === null) data.show(await outreachApi.createCall(scheduleId, { contact_id: person.id, ...body, ...(form.activity ? { activity_id: form.activity } : {}) }));
        else {
          const patch = changedFields(row, body, form.activity);
          if (Object.keys(patch).length > 0) data.show(await outreachApi.patchCall(scheduleId, row.id, patch));
        }
        setEditing(false);
        setNote(null);
        onChanged();
      } catch (e) {
        setFormError(errText(e, '저장할 수 없습니다.')); // 번호가 든 글은 서버가 422 has_phone 으로 막는다 — 그 글 그대로
      }
    });

  const locked = busy !== null;
  const ours = row === null || row.contact === null || row.contact.id === person.id;
  const draftLike = row !== null && PLACEABLE.has(row.status) && ours;
  const at = draftLike ? scheduleAt(row, detail) : undefined;
  const shownNote = note && row && note.text === callStatusLabel(row).text ? null : note; // 지금 상태 줄이 같은 말을 하면 한 번만
  const language = editing || row === null ? form.language : row.language; // 쓰는 중이면 고르는 값, 아니면 저장된 값
  const notCallable = ours && !data.loadError && !(callId !== null && row === null) && !CALLABLE_LANGUAGES.has(language);

  const foot = editing ? (
    <>
      <Button disabled={locked} onClick={() => (row === null ? onClose() : (setEditing(false), setFormError(null)))}>취소</Button>
      <Button variant="primary" disabled={locked || form.purpose.trim() === ''} onClick={() => void save()}>
        {busy === 'save' ? '저장하는 중…' : '저장'}
      </Button>
    </>
  ) : (
    <>
      <Button disabled={locked} onClick={onClose}>닫기</Button>
      {draftLike && row.status === 'draft' && <Button disabled={locked} onClick={() => rewrite(row, person)}>에이전트에게 다시 쓰게</Button>}
      {draftLike && row.status === 'draft' && <Button disabled={locked} onClick={() => (setForm(formOf(row, row.language)), setEditing(true), setNote(null))}>고치기</Button>}
      {draftLike && at === undefined && (
        <Button variant="primary" disabled={locked || blocked !== null} title={blocked ?? undefined} onClick={() => void place(row)}>
          {busy === 'place' ? '거는 중…' : '전화 걸기'}
        </Button>
      )}
    </>
  );

  return (
    <XferDialog title={TITLE} busy={locked} onClose={onClose} foot={foot}>
      <div className="cl-dialog-body">
        {data.loadError ? (
          <p role="alert" className="ct-error">{data.loadError}</p>
        ) : callId !== null && row === null ? (
          <p className="ct-muted">통화를 읽는 중…</p>
        ) : !ours ? (
          <p role="alert" className="ct-error">이 사람의 통화가 아닙니다 — 그 통화의 연락처에서 열어 주세요.</p>
        ) : editing || row === null ? (
          <>
            <Rows row={row} person={person} detail={detail} detailFailed={data.detailFailed} editing />
            <EditForm scheduleId={scheduleId} form={form} setForm={setForm} locked={locked} />
            {formError && <p role="alert" className="th-note is-bad">{formError}</p>}
          </>
        ) : (
          <>
            <Rows row={row} person={person} detail={detail} detailFailed={data.detailFailed} />
            <ViewFoot row={row} draftLike={draftLike} at={at} hoursUnread={data.detailFailed} blocked={blocked} busy={busy} pick={pick} setPick={setPick}
              onSchedule={(when) => void schedule(row, when)} />
          </>
        )}
        {notCallable && <p className="th-note is-warn">{NOT_CALLABLE}</p>}
        {shownNote && (
          <p role="status" className={`th-note is-${shownNote.tone}`}>
            {shownNote.text}
          </p>
        )}
      </div>
    </XferDialog>
  );
}
