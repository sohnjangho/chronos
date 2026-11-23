// 「전화 걸기」 창(Task 92, 시안 ③): 받는 사람 · 통화 목적 · 물어볼 것 · 말하지 않을 것 · 연결 · 언어 · 음성(고른 까닭) · 근무시간 줄,
// [에이전트에게 다시 쓰게](대화로 보냄) [고치기] [전화 걸기]. 근무시간 밖이면 [전화 걸기] 대신 「지금은 근무시간 밖입니다 — [<다음 근무 시작>에 예약]」.
// 새 통화는 먼저 쓰고 [저장](초안 — 걸지 않음)한 뒤 그 초안을 확인하고 건다. [전화 걸기]는 진짜 전화로 이어진다: 한 번에 요청 하나(두 번 눌러도),
// 걸기 바로 전에 그 줄을 다시 읽어 보인 것과 다르면 걸지 않고 새 내용을 보인다(승인한 내용 = 거는 내용). 결과는 문의 판정 글 그대로이고,
// 답을 못 받으면 「걸었는지 확인하지 못했습니다」(실패가 아니다) 뒤 다시 읽는다. 전화번호는 이 창 어디에도 없다(사람이 쓴 글도 가려 보인다).
import { useEffect, useRef, useState } from 'react';
import { useWindows } from '../../os/windowStore';
import {
  CALL_UNKNOWN, callOutcomeLabel, callSender, callStatusLabel, hasPhone, kstShort, maskPhones, outcomeLabel, type Label,
} from '../../shared/outreach/labels';
import { outreachApi, sendOutcomeUnknown, type Call, type CallLanguage, type CallResult } from '../../shared/outreach/outreachApi';
import Button from '../../shared/ui/Button';
import ActivityPicker from './ActivityPicker';
import { getPerson, LANGUAGES, type PersonBrief, type PersonDetail } from './contactsApi';
import { activityLabel } from './thread';
import XferDialog from './XferDialog';

export const TITLE = '전화 걸기';
export const CHANGED = '내용이 바뀌었습니다 — 확인한 뒤 다시 눌러 주세요';
export const UNREAD = '지금 상태를 읽지 못해 걸지 않았습니다 — 다시 눌러 주세요';
export const PHONE_IN_TEXT = '통화 목적·물어볼 것·말하지 않을 것에는 전화번호를 적을 수 없습니다 — 번호는 앱이 붙입니다.';
const PURPOSE_MAX = 500; // 서버(Task 91)와 같은 값
const LINE_MAX = 200;
const LINES_MAX = 10;
const PLACEABLE = new Set(['draft', 'blocked_hours']);
const CIRCLED = '①②③④⑤⑥⑦⑧⑨⑩';
const WEEKDAYS = ['일', '월', '화', '수', '목', '금', '토'];
const KST_MS = 9 * 3_600_000;
const two = (n: number) => String(n).padStart(2, '0');
const errText = (e: unknown, fallback: string) => (e instanceof Error && e.message ? e.message : fallback);

/** 「근무 밖 · 월 08:00 부터」(주소록 API 의 hours_label — 서버가 근무시간·공휴일을 보고 고른 다음 근무 시작) → 그 시각(KST, 시간대 붙은 ISO).
 *  글에는 요일과 시각만 있으므로 지금부터 가장 가까운 그 요일·시각으로 읽는다. 서버가 예약할 때 근무시간을 다시 보고 틀리면 422 로 막는다. */
export function nextStartFromLabel(label: string, now: Date = new Date()): string | null {
  const m = /근무 밖 · ([일월화수목금토]) (\d{2}):(\d{2}) 부터/.exec(label);
  if (!m) return null;
  const want = WEEKDAYS.indexOf(m[1]);
  const [h, min] = [Number(m[2]), Number(m[3])];
  const k = new Date(now.getTime() + KST_MS);
  for (let i = 0; i < 8; i++) {
    const wall = new Date(Date.UTC(k.getUTCFullYear(), k.getUTCMonth(), k.getUTCDate() + i, h, min));
    if (wall.getUTCDay() !== want || wall.getTime() - KST_MS <= now.getTime()) continue;
    return `${wall.getUTCFullYear()}-${two(wall.getUTCMonth() + 1)}-${two(wall.getUTCDate())}T${two(h)}:${two(min)}:00+09:00`;
  }
  return null;
}

/** 음성 줄: 이 통화에 고른 음성 → 연락처에서 직접 고른 음성 → 설정의 성별 칸(일꾼이 voices.pick 으로 고르는 차례 그대로). */
function voiceLine(row: Call | null, d: PersonDetail | null): string {
  if (row?.voice_id) return `${row.voice_id} · 이 통화에 고른 음성`;
  if (d?.voice_mode === 'manual' && d.voice_id) return `${d.voice_id} · 연락처에서 직접 고른 음성`;
  if (!d) return '설정의 음성 칸에서 고릅니다';
  const slot = d.gender === 'male' ? '남성 연락처에게 걸 때' : d.gender === 'female' ? '여성 연락처에게 걸 때' : '성별 모름';
  return `설정의 「${slot}」 칸에서 고릅니다`;
}

const lines = (text: string) => text.split('\n').map((l) => l.trim()).filter(Boolean);
const langLabel = (code: string) => LANGUAGES.find((l) => l.key === code)?.label ?? code;
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

interface Form {
  purpose: string;
  questions: string;
  avoid: string;
  language: string;
  activity: string | null;
}
const formOf = (row: Call | null, language: string): Form =>
  row
    ? { purpose: row.purpose, questions: row.questions.join('\n'), avoid: row.avoid.join('\n'), language: row.language, activity: row.activity?.id ?? null }
    : { purpose: '', questions: '', avoid: '', language, activity: null };

function formProblem(f: Form): string | null {
  const all = [f.purpose, ...lines(f.questions), ...lines(f.avoid)];
  if (all.some(hasPhone)) return PHONE_IN_TEXT;
  if (lines(f.questions).length > LINES_MAX || lines(f.avoid).length > LINES_MAX) return `물어볼 것·말하지 않을 것은 ${LINES_MAX}줄까지 적을 수 있습니다.`;
  if ([...lines(f.questions), ...lines(f.avoid)].some((l) => l.length > LINE_MAX)) return `한 줄은 ${LINE_MAX}자까지 적을 수 있습니다.`;
  return null;
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

/** 시안 ③의 줄들. 쓰는 중(editing)에는 쓰지 않는 줄(받는 사람·음성·근무시간)만. */
function Rows({ row, person, detail, editing = false }: { row: Call | null; person: PersonBrief; detail: PersonDetail | null; editing?: boolean }) {
  const c = row?.contact;
  const who = c ? `${c.name} ${c.role_title}${c.company ? ` (${c.company})` : ''}` : `${person.name} ${person.role_title}`;
  if (editing)
    return (
      <dl className="cl-kv">
        <dt>받는 사람</dt>
        <dd>{who.trim()}</dd>
        <dt>음성</dt>
        <dd>{voiceLine(row, detail)}</dd>
        <dt>근무시간</dt>
        <dd>{detail?.hours_label ?? '읽는 중…'}</dd>
      </dl>
    );
  return (
    <dl className="cl-kv">
      <dt>받는 사람</dt>
      <dd>{who.trim()}</dd>
      <dt>통화 목적</dt>
      <dd>{row ? maskPhones(row.purpose) : ''}</dd>
      <dt>물어볼 것</dt>
      <dd>
        {row && row.questions.length > 0 ? (
          <ol>
            {row.questions.map((q, i) => (
              <li key={i}>{`${CIRCLED[i] ?? `${i + 1}.`} ${maskPhones(q)}`}</li>
            ))}
          </ol>
        ) : (
          '없음'
        )}
      </dd>
      <dt>말하지 않을 것</dt>
      <dd>{row && row.avoid.length > 0 ? row.avoid.map(maskPhones).join(', ') : '없음'}</dd>
      <dt>연결</dt>
      <dd>{row?.activity ? activityLabel(row.activity) : '없음'}</dd>
      <dt>언어</dt>
      <dd>{langLabel(row?.language ?? detail?.language ?? 'ko')}</dd>
      <dt>음성</dt>
      <dd>{voiceLine(row, detail)}</dd>
      <dt>근무시간</dt>
      <dd>{detail?.hours_label ?? '읽는 중…'}</dd>
    </dl>
  );
}

function EditForm({ scheduleId, form, setForm, locked }: { scheduleId: number; form: Form; setForm(f: Form): void; locked: boolean }) {
  const put = (k: keyof Form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  return (
    <div className="cl-form">
      <label>
        통화 목적
        <textarea className="ct-input ct-textarea" aria-label="통화 목적" maxLength={PURPOSE_MAX} value={form.purpose} readOnly={locked} onChange={put('purpose')} />
      </label>
      <label>
        <span>
          물어볼 것 <span className="cl-hint">— 한 줄에 하나, {LINES_MAX}개까지</span>
        </span>
        <textarea className="ct-input ct-textarea" aria-label="물어볼 것" value={form.questions} readOnly={locked} onChange={put('questions')} />
      </label>
      <label>
        <span>
          말하지 않을 것 <span className="cl-hint">— 한 줄에 하나</span>
        </span>
        <textarea className="ct-input ct-textarea" aria-label="말하지 않을 것" value={form.avoid} readOnly={locked} onChange={put('avoid')} />
      </label>
      <label>
        언어
        <select className="ct-input" value={form.language} disabled={locked} onChange={put('language')}>
          {LANGUAGES.map((l) => (
            <option key={l.key} value={l.key}>
              {l.label}
            </option>
          ))}
        </select>
      </label>
      <ActivityPicker scheduleId={scheduleId} value={form.activity} onChange={(id) => setForm({ ...form, activity: id })} disabled={locked} />
    </div>
  );
}

/** 지금 이 창의 동작 하나(두 번 눌러도 하나). */
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
  const [row, setRow] = useState<Call | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const seq = useRef(0);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    getPerson(scheduleId, personId).then(
      (d) => alive.current && setDetail(d),
      () => undefined, // 근무시간·음성 줄 없이 둔다
    );
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
  /** 그 줄을 다시 읽어 보인다. */
  const reread = async (id: number) => {
    const mine = ++seq.current;
    const fresh = await outreachApi.getCall(scheduleId, id);
    if (alive.current && mine === seq.current) setRow(fresh);
    return fresh;
  };
  /** 동작의 답이 준 줄을 보인다. */
  const show = (r: Call) => {
    seq.current += 1;
    if (alive.current) setRow(r);
  };
  return { detail, row, loadError, reread, show };
}
type CallData = ReturnType<typeof useCallData>;

/** [전화 걸기]·[예약]. 걸기는 바로 전에 그 줄을 다시 읽어 보인 것과 같을 때만 문에 넣는다. 끝나면 목록을 다시 읽게 한다. */
function useCallActions(scheduleId: number, data: CallData, run: ReturnType<typeof useLock>['run'], setNote: (n: Label | null) => void, onChanged: () => void) {
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
        setNote({ text: '예약했습니다 — 그 시각에 근무시간·시험 모드를 다시 확인한 뒤 겁니다.', tone: 'info' });
      } catch (e) {
        setNote({ text: errText(e, '예약할 수 없습니다.'), tone: 'bad' });
        await data.reread(shown.id).catch(() => undefined);
      }
      onChanged();
    });
  return { place, schedule };
}

/** [에이전트에게 다시 쓰게]: 대화에 요청 글을 보낸다(이름·담당·협력사·초안 번호와 목적 — 전화번호는 넣지 않는다). */
function rewrite(r: Call, person: PersonBrief) {
  const c = r.contact;
  const who = c ? `${c.name}(${[c.role_title, c.company].filter(Boolean).join(' · ')})` : person.name;
  const asked = r.questions.length ? ` 물어볼 것: ${r.questions.map(maskPhones).join(' / ')}.` : '';
  const ask = `${who}에게 걸 전화 초안 #${r.id}의 목적과 물어볼 것을 다시 써 주세요. 지금 통화 목적: ${maskPhones(r.purpose)}.${asked}`;
  useWindows.getState().open('chat', { ask });
}

interface ViewProps {
  row: Call;
  person: PersonBrief;
  detail: PersonDetail | null;
  /** 아직 걸 수 있는 줄(초안·근무시간 밖으로 막힘) */
  draftLike: boolean;
  /** 근무시간 밖이면 예약할 시각(찾지 못했으면 null), 근무 중이면 undefined */
  at: string | null | undefined;
  blocked: string | null;
  busy: string | null;
  onSchedule(at: string): void;
}

/** 확인 보기: 시안 ③의 줄 · 지금 상태(이미 걸었거나 막혔으면) · 근무시간 밖 예약 줄 · 걸 수 없는 까닭. */
function View({ row, person, detail, draftLike, at, blocked, busy, onSchedule }: ViewProps) {
  const status = callStatusLabel(row);
  const sender = callSender(row);
  return (
    <>
      <Rows row={row} person={person} detail={detail} />
      {!draftLike && <p className={`cl-state is-${status.tone}`}>{`지금 상태: ${status.text} · ${sender.tag}${sender.approver ? ` · ${sender.approver} 승인` : ''}`}</p>}
      {draftLike && row.status === 'blocked_hours' && <p className={`cl-state is-${status.tone}`}>{`지금 상태: ${status.text}`}</p>}
      {at !== undefined && (
        <p className="cl-off">
          {at ? '지금은 근무시간 밖입니다 — ' : '지금은 근무시간 밖이고 다음 근무 시작을 찾지 못했습니다 — 연락처의 근무시간을 확인해 주세요.'}
          {at && (
            <Button variant="primary" disabled={busy !== null || blocked !== null} title={blocked ?? undefined} onClick={() => onSchedule(at)}>
              {busy === 'schedule' ? '예약하는 중…' : `${kstShort(at)}에 예약`}
            </Button>
          )}
        </p>
      )}
      {blocked && draftLike && <p className="th-note is-bad">{blocked}</p>}
    </>
  );
}

/** 근무시간 밖이면 예약할 시각: 문이 막아 둔 줄이면 문이 제안한 시각, 아니면 머리 줄의 「다음 근무 시작」. 근무 중이면 undefined. */
function scheduleAt(row: Call, detail: PersonDetail | null): string | null | undefined {
  if (row.status === 'blocked_hours') return row.scheduled_at ?? nextStartFromLabel(detail?.hours_label ?? '');
  return detail?.working_now === false ? nextStartFromLabel(detail.hours_label) : undefined;
}

export default function CallDialog({ scheduleId, person, callId, blocked, onClose, onChanged }: Props) {
  const data = useCallData(scheduleId, person.id, callId);
  const { detail, row } = data;
  const [editing, setEditing] = useState(callId === null);
  const [form, setForm] = useState<Form>(() => formOf(null, 'ko'));
  const [formError, setFormError] = useState<string | null>(null);
  const [note, setNote] = useState<Label | null>(null);
  const { busy, run } = useLock();
  const { place, schedule } = useCallActions(scheduleId, data, run, setNote, onChanged);
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
        else data.show(await outreachApi.patchCall(scheduleId, row.id, { ...body, ...(form.activity !== (row.activity?.id ?? null) ? { activity_id: form.activity } : {}) }));
        setEditing(false);
        setNote(null);
        onChanged();
      } catch (e) {
        setFormError(errText(e, '저장할 수 없습니다.'));
      }
    });

  const locked = busy !== null;
  const ours = row === null || row.contact === null || row.contact.id === person.id;
  const draftLike = row !== null && PLACEABLE.has(row.status) && ours;
  const at = draftLike ? scheduleAt(row, detail) : undefined;
  const shownNote = note && row && note.text === callStatusLabel(row).text ? null : note; // 지금 상태 줄이 같은 말을 하면 한 번만

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
            <Rows row={row} person={person} detail={detail} editing />
            <EditForm scheduleId={scheduleId} form={form} setForm={setForm} locked={locked} />
            {formError && <p role="alert" className="th-note is-bad">{formError}</p>}
          </>
        ) : (
          <View row={row} person={person} detail={detail} draftLike={draftLike} at={at} blocked={blocked} busy={busy} onSchedule={(when) => void schedule(row, when)} />
        )}
        {shownNote && (
          <p role="status" className={`th-note is-${shownNote.tone}`}>
            {shownNote.text}
          </p>
        )}
      </div>
    </XferDialog>
  );
}
