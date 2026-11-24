// 사람 추가·고치기 양식(시안 ⑤). 번호는 가린 꼴로 보이고 「눌러서 보기」(reveal)를 눌러야 전체가 이 양식 안에만 보인다 —
// 양식이 닫히면 함께 사라진다(저장소·URL·로그에 두지 않음). 서버의 422·403 글은 그 칸 아래에(보낸 값은 되풀이하지 않음).
// 수신 거부는 번호에 붙는다: 번호를 바꾸거나 빼면 옛 번호는 모든 프로젝트에서 계속 막히고 새 번호로 따라가지 않는다(Task 72).
// 관리자 등급·참여 프로젝트(11-24)는 PersonLinks — 관리자 등급으로 올리는 저장은 확인을 한 번 묻는다.
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { ApiError } from '../../shared/api';
import Button from '../../shared/ui/Button';
import { CALLABLE_LANGUAGES, NOT_CALLABLE } from './CallDialog';
import {
  getPerson, KIND_LABEL, LANGUAGES, patchPerson, postPerson, revealPhone,
  type AccessLevel, type Company, type Gender, type Hours, type Language, type PersonBody, type PersonDetail, type VoiceMode,
} from './contactsApi';
import HoursField from './HoursField';
import { LEVEL_CONFIRM, LevelField, ProjectsField } from './PersonLinks';

type ErrKey = 'name' | 'role_title' | 'company' | 'phone' | 'channels' | 'hours' | 'voice' | 'dnc' | 'dnc_reason' | 'note' | 'level' | 'form';
type Errors = Partial<Record<ErrKey, string>>;
type PhoneMode = 'masked' | 'revealed' | 'edit';
type Confirm = null | 'number' | 'clear' | 'level';
type Touched = { sms?: boolean; call?: boolean };

const KAKAO_LOCKED = '카카오톡은 채널·문안 승인 뒤 쓸 수 있습니다.';
/** 서버(Task 72 check_voice)와 같은 꼴·같은 글. */
const VOICE_ID = /^[A-Za-z0-9._:-]{1,64}$/;
const VOICE_SHAPE = '음성 id 는 영문·숫자와 . _ : - 로 64자까지입니다.';
const VOICE_NEEDED = '음성을 직접 지정하려면 음성 id 를 넣어 주세요.';
/** 서버(Task 99 고침 1)와 같은 글. 국내 전화번호 꼴(010-0000-0000 · 01000000000 · 070…)만 본다 — 나머지는 서버가 한 번 더. */
const VOICE_PHONE = '음성 id 가 전화번호처럼 보입니다. 공급자의 음성 이름을 넣어 주세요.';
const PHONE_LIKE = /^0\d{1,2}[-. ]?\d{3,4}[-. ]?\d{4}$/;

function voiceProblem(id: string): string | null {
  if (!id) return VOICE_NEEDED;
  if (PHONE_LIKE.test(id)) return VOICE_PHONE;
  return VOICE_ID.test(id) ? null : VOICE_SHAPE;
}
const MOBILE_ONLY = '문자·카카오톡은 휴대전화 번호로만 보낼 수 있습니다.';

/** 서버 오류를 칸으로. 모르는 코드는 서버의 한국어 글을 양식 아래에. 보낸 값은 싣지 않는다(서버 글에도 없음). */
function fieldOf(e: unknown): Errors {
  if (!(e instanceof ApiError)) return { form: '저장할 수 없습니다.' };
  const text = e.message;
  switch (e.code) {
    case 'invalid_phone':
      return { phone: text };
    case 'channel_not_possible':
      return { channels: text };
    case 'invalid_hours':
      return { hours: text };
    case 'invalid_voice':
      return { voice: text };
    case 'admin_only_level':
      return { level: text };
    case 'admin_only':
      return { dnc: text.startsWith('수신 거부는 관리자만 풀 수 있습니다') ? text : `수신 거부는 관리자만 풀 수 있습니다. ${text}` };
    case 'invalid_text': {
      const f = (e.detail as { field?: string } | null)?.field;
      return f === 'name' || f === 'role_title' || f === 'note' || f === 'dnc_reason' ? { [f]: text } : { form: text };
    }
    default:
      return { form: text };
  }
}

function Err({ text }: { text?: string }) {
  return text ? (
    <p className="ct-error" role="alert">
      {text}
    </p>
  ) : null;
}

function Fld({ label, error, children, wide }: { label: string; error?: string; children: ReactNode; wide?: boolean }) {
  return (
    <div className={`ct-field${wide ? ' is-wide' : ''}`}>
      <label className="ct-fld-label">
        <span className="ct-label">{label}</span>
        {children}
      </label>
      <Err text={error} />
    </div>
  );
}

interface Props {
  scheduleId: number;
  /** 고칠 사람 id(없으면 새 사람). */
  personId: number | null;
  companies: Company[];
  /** 새 사람의 협력사(묶음에서 연 경우). */
  companyId?: number | null;
  projectName: string | null;
  isAdmin: boolean;
  kakaoReady: boolean;
  onSaved: (p: PersonDetail) => void;
  onCancel: () => void;
  /** 참여 프로젝트를 등록하거나 뺐다(양식은 열린 채 — 주소록만 다시 읽는다). */
  onLinked?: () => void;
}

/** 고칠 사람의 자세히를 읽은 뒤 양식을 그린다. */
export default function PersonForm(props: Props) {
  const { scheduleId, personId } = props;
  const [loaded, setLoaded] = useState<{ detail: PersonDetail | null; error: string | null }>({ detail: null, error: null });
  useEffect(() => {
    if (personId === null) return;
    let live = true;
    getPerson(scheduleId, personId).then(
      (d) => live && setLoaded({ detail: d, error: null }),
      (e: unknown) => live && setLoaded({ detail: null, error: e instanceof Error ? e.message : '읽을 수 없습니다.' }),
    );
    return () => {
      live = false;
    };
  }, [scheduleId, personId]);
  if (personId === null) return <Form {...props} detail={null} />;
  if (loaded.error)
    return (
      <div className="ct-form-wrap">
        <Err text={loaded.error} />
        <Button onClick={props.onCancel}>닫기</Button>
      </div>
    );
  if (!loaded.detail) return <p className="ct-muted ct-pad">읽는 중…</p>;
  return <Form {...props} detail={loaded.detail} />;
}

interface Values {
  name: string;
  role_title: string;
  company_id: string;
  hours: Hours | null;
  gender: Gender;
  language: Language;
  voice_mode: VoiceMode;
  voice_id: string;
  dnc: boolean;
  dnc_reason: string;
  note: string;
  access_level: AccessLevel;
}

function initialValues(d: PersonDetail | null, companies: Company[], companyId: number | null | undefined): Values {
  return {
    name: d?.name ?? '',
    role_title: d?.role_title ?? '',
    company_id: String(d?.company_id ?? companyId ?? companies.find((c) => !c.hidden)?.id ?? ''),
    hours: d?.hours ?? null,
    gender: d?.gender ?? 'unknown',
    language: (d?.language as Language) ?? 'ko',
    voice_mode: d?.voice_mode ?? 'auto',
    voice_id: d?.voice_id ?? '',
    dnc: d?.do_not_contact ?? false,
    dnc_reason: d?.dnc_reason ?? '',
    note: d?.note ?? '',
    access_level: d?.access_level ?? 'trade',
  };
}

/** 새 사람: 칸 전부(채널은 끈 것만 — 켠 채로 두면 번호 종류를 따른다). 고치기: 바뀐 칸만. */
function buildBody(detail: PersonDetail | null, v: Values, phone: string | null, phoneDirty: boolean, touched: Touched): PersonBody {
  const reason = v.dnc_reason.trim();
  if (!detail) {
    const b: PersonBody = {
      name: v.name.trim(), role_title: v.role_title.trim(), company_id: Number(v.company_id), phone, hours: v.hours,
      gender: v.gender, language: v.language, voice_mode: v.voice_mode, do_not_contact: v.dnc, note: v.note,
    };
    if (v.voice_mode === 'manual') b.voice_id = v.voice_id.trim();
    if (touched.sms === false) b.can_sms = false;
    if (touched.call === false) b.can_call = false;
    if (v.dnc && reason) b.dnc_reason = reason;
    if (v.access_level !== 'trade') b.access_level = v.access_level;
    return b;
  }
  const b: PersonBody = {};
  if (v.name.trim() !== detail.name) b.name = v.name.trim();
  if (v.role_title.trim() !== detail.role_title) b.role_title = v.role_title.trim();
  if (Number(v.company_id) !== detail.company_id) b.company_id = Number(v.company_id);
  if (phoneDirty) b.phone = phone;
  for (const c of ['sms', 'call'] as const) {
    const t = touched[c];
    if (t !== undefined && (phoneDirty ? t === false : t !== detail.channels.includes(c))) b[c === 'sms' ? 'can_sms' : 'can_call'] = t;
  }
  if (JSON.stringify(v.hours) !== JSON.stringify(detail.hours)) b.hours = v.hours;
  if (v.gender !== detail.gender) b.gender = v.gender;
  if (v.language !== detail.language) b.language = v.language;
  if (v.voice_mode !== detail.voice_mode) b.voice_mode = v.voice_mode;
  if (v.voice_mode === 'manual' && v.voice_id.trim() !== (detail.voice_id ?? '')) b.voice_id = v.voice_id.trim();
  if (v.dnc !== detail.do_not_contact) b.do_not_contact = v.dnc;
  if (v.dnc && reason !== (detail.dnc_reason ?? '')) b.dnc_reason = reason || null;
  if (v.note !== detail.note) b.note = v.note;
  if (v.access_level !== detail.access_level) b.access_level = v.access_level;
  return b;
}

type FormProps = Props & { detail: PersonDetail | null };

/** 양식의 상태와 동작. 전체 번호(phone)는 이 훅의 상태에만 있고 양식이 닫히면(언마운트) 사라진다. */
function usePersonForm({ scheduleId, companies, companyId, isAdmin, onSaved, onCancel, detail }: FormProps) {
  const [v, setV] = useState<Values>(() => initialValues(detail, companies, companyId));
  const [phoneMode, setPhoneMode] = useState<PhoneMode>(detail?.has_phone ? 'masked' : 'edit');
  const [phone, setPhone] = useState('');
  const revealed = useRef<string | null>(null);
  const [touched, setTouched] = useState<Touched>({});
  const [errors, setErrors] = useState<Errors>({});
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState<Confirm>(null);
  const set = <K extends keyof Values>(k: K, val: Values[K]) => setV((s) => ({ ...s, [k]: val }));

  const typed = phone.trim();
  const phoneDirty =
    detail === null ? typed !== '' : phoneMode === 'edit' ? detail.has_phone || typed !== '' : phoneMode === 'revealed' && typed !== (revealed.current ?? '');

  const reveal = async () => {
    if (!detail) return;
    setErrors((e) => ({ ...e, phone: undefined }));
    try {
      const r = await revealPhone(scheduleId, detail.id);
      revealed.current = r.phone;
      setPhone(r.phone ?? '');
      setPhoneMode(r.phone ? 'revealed' : 'edit');
    } catch (e) {
      // 429(10분에 30번)도 서버 글 그대로. 다시 부르지 않는다.
      setErrors((x) => ({ ...x, phone: e instanceof ApiError ? e.message : '번호를 볼 수 없습니다.' }));
    }
  };
  const changePhone = () => {
    setPhone('');
    setPhoneMode('edit');
  };

  const body = () => buildBody(detail, v, typed === '' ? null : typed, phoneDirty, touched);
  const save = async (b: PersonBody) => {
    setConfirm(null);
    setErrors({});
    if (detail && Object.keys(b).length === 0) return onCancel();
    setBusy(true);
    try {
      const saved = detail ? await patchPerson(scheduleId, detail.id, b) : await postPerson(scheduleId, b);
      setBusy(false);
      onSaved(saved);
    } catch (e) {
      setBusy(false);
      setErrors(fieldOf(e));
    }
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    check(false);
  };
  /** 저장 전 확인들. levelOk = 관리자 등급으로 올리는 것을 이미 확인함. */
  const check = (levelOk: boolean) => {
    if (!v.name.trim()) return setErrors({ name: '이름을 넣어 주세요.' });
    if (!v.company_id) return setErrors({ company: '먼저 협력사를 추가해 주세요.' });
    const voiceBad = v.voice_mode === 'manual' ? voiceProblem(v.voice_id.trim()) : null;
    if (voiceBad) return setErrors({ voice: voiceBad });
    if (!levelOk && v.access_level === 'manager' && (detail?.access_level ?? 'trade') !== 'manager') return setConfirm('level');
    if (detail?.do_not_contact && !v.dnc && isAdmin) return setConfirm('clear');
    if (detail?.do_not_contact && v.dnc && phoneDirty) return setConfirm('number');
    void save(body());
  };
  /** 수신 거부인 사람의 번호를 바꿀 때: 새 번호도 막을지(do_not_contact: true 를 같이 보냄) 번호만 보낼지. */
  const pick = (dnc: boolean) => void save(dnc ? { ...body(), do_not_contact: true } : body());
  const toggleHidden = () => detail && void save({ hidden: !detail.hidden });

  const confirmLevel = () => {
    setConfirm(null);
    check(true);
  };

  return { v, set, phoneMode, phone, setPhone, phoneDirty, touched, setTouched, errors, busy, confirm, setConfirm, reveal, changePhone, submit, save, body, pick, toggleHidden, confirmLevel };
}

function Form(props: FormProps) {
  const { detail, companies, projectName, kakaoReady, onCancel, isAdmin, scheduleId, onLinked } = props;
  const f = usePersonForm(props);
  const { v, set, errors } = f;
  const [projects, setProjects] = useState(detail?.projects ?? 1);
  const linked = detail?.linked_activities ?? [];
  const linkedText = linked.length === 0 ? '맡은 작업은 아직 없습니다' : `맡은 작업: ${linked[0].name}${linked.length > 1 ? ` 외 ${linked.length - 1}개` : ''}`;
  const title = detail ? '사람 고치기' : '사람 추가';
  return (
    <form className="ct-form" aria-label={title} onSubmit={f.submit} noValidate>
      <div className="ct-form-head">
        <h3 className="ct-title">{title}</h3>
        {detail && <span className="ct-muted ct-ellipsis">{detail.name}</span>}
      </div>
      <div className="ct-grid">
        <Fld label="이름" error={errors.name}>
          <input className="ct-input" value={v.name} maxLength={100} onChange={(e) => set('name', e.target.value)} />
        </Fld>
        <Fld label="담당" error={errors.role_title}>
          <input className="ct-input" value={v.role_title} maxLength={100} placeholder="예: 골조 팀장" onChange={(e) => set('role_title', e.target.value)} />
        </Fld>
        <Fld label="협력사" error={errors.company}>
          <select className="ct-input" value={v.company_id} onChange={(e) => set('company_id', e.target.value)}>
            {companies
              .filter((c) => !c.hidden || c.id === detail?.company_id)
              .map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
          </select>
        </Fld>
        <PhoneField detail={detail} mode={f.phoneMode} phone={f.phone} setPhone={f.setPhone} dirty={f.phoneDirty} error={errors.phone} onReveal={() => void f.reveal()} onChange={f.changePhone} />
        <ChannelsField detail={detail} followsNumber={detail === null || f.phoneDirty} touched={f.touched} setTouched={f.setTouched} kakaoReady={kakaoReady} error={errors.channels} />
        <HoursField value={v.hours} onChange={(h) => set('hours', h)} label={detail?.hours_label} error={errors.hours} />
        <ProfileFields v={v} set={set} voiceError={errors.voice} />
        <DncField v={v} set={set} error={errors.dnc} reasonError={errors.dnc_reason} />
        <LevelField value={v.access_level} onChange={(l) => set('access_level', l)} isAdmin={isAdmin} />
        <Err text={errors.level} />
        <Fld label="메모" error={errors.note} wide>
          <textarea className="ct-input ct-textarea" value={v.note} maxLength={2000} rows={3} onChange={(e) => set('note', e.target.value)} />
        </Fld>
        <ProjectsField scheduleId={scheduleId} detail={detail} onChanged={(d) => (setProjects(d.projects), onLinked?.())} />
      </div>
      <p className="ct-hint">
        {projects > 1
          ? `협력사·담당·근무시간·메모는 이 프로젝트${projectName ? `(${projectName})` : ''}에만, 나머지는 참여 프로젝트 ${projects}곳 모두에 저장됩니다. ${linkedText}`
          : `이 프로젝트${projectName ? `(${projectName})` : ''}에만 저장됩니다. ${linkedText}`}
      </p>
      <Err text={errors.form} />
      {f.confirm && <ConfirmBox kind={f.confirm} onCancel={() => f.setConfirm(null)} onClear={() => void f.save(f.body())} onPick={f.pick} onLevel={f.confirmLevel} />}
      <div className="ct-actions">
        {detail && (
          <Button onClick={f.toggleHidden} disabled={f.busy}>
            {detail.hidden ? '다시 보이기' : '숨기기'}
          </Button>
        )}
        <span className="ct-gap" />
        <Button onClick={onCancel} disabled={f.busy}>
          취소
        </Button>
        <Button variant="primary" type="submit" disabled={f.busy || f.confirm !== null}>
          저장
        </Button>
      </div>
    </form>
  );
}

interface ChannelsProps {
  detail: PersonDetail | null;
  /** 새 사람이거나 번호를 바꾸는 중 — 저장할 때 번호 종류가 정한다. */
  followsNumber: boolean;
  touched: Touched;
  setTouched: (f: (t: Touched) => Touched) => void;
  kakaoReady: boolean;
  error?: string;
}

/** 받을 수 있는 것: 문자·카카오톡은 휴대전화만, 카카오톡은 채널·문안 승인 전에는 잠김(PM 11-23). */
function ChannelsField({ detail, followsNumber, touched, setTouched, kakaoReady, error }: ChannelsProps) {
  const has = (c: 'sms' | 'kakao' | 'call') => followsNumber || (detail?.channels.includes(c) ?? true);
  const smsOk = followsNumber || detail?.phone_kind === 'mobile';
  const callOk = followsNumber || (detail?.has_phone === true && detail.phone_kind !== 'premium');
  const reason = !followsNumber && !detail?.has_phone ? '번호가 없어 연락할 수 없습니다.' : !smsOk ? MOBILE_ONLY : null;
  return (
    <fieldset className="ct-fieldset ct-field is-wide" aria-label="받을 수 있는 것">
      <legend className="ct-label">받을 수 있는 것</legend>
      <div className="ct-checks">
        <label className="ct-check">
          <input type="checkbox" checked={touched.sms ?? (smsOk && has('sms'))} disabled={!smsOk} onChange={(e) => setTouched((t) => ({ ...t, sms: e.target.checked }))} />
          문자
        </label>
        <label className="ct-check">
          <input type="checkbox" checked={kakaoReady && smsOk && has('kakao')} disabled />
          카카오톡
        </label>
        <label className="ct-check">
          <input type="checkbox" checked={touched.call ?? (callOk && has('call'))} disabled={!callOk} onChange={(e) => setTouched((t) => ({ ...t, call: e.target.checked }))} />
          전화
        </label>
      </div>
      {reason && <p className="ct-hint">{reason}</p>}
      {followsNumber && <p className="ct-hint">저장하면 번호 종류에 맞춰 정합니다(문자·카카오톡은 휴대전화만). 받지 않을 것만 끄세요.</p>}
      {!kakaoReady && <p className="ct-hint">{KAKAO_LOCKED}</p>}
      <Err text={error} />
    </fieldset>
  );
}

type SetValue = <K extends keyof Values>(k: K, val: Values[K]) => void;

/** 고른 언어로 무엇이 달라지나(Task 100): 한국어가 아니면 문자는 그 언어 + 한국어 번역, 통화가 준비되지 않은 언어는 한국어로 건다. */
function LanguageHint({ language }: { language: Language }) {
  if (language === 'ko') return null;
  const label = LANGUAGES.find((l) => l.key === language)?.label ?? language;
  return (
    <>
      <p className="ct-hint">{`문자는 ${label}로 쓰고 한국어 번역을 함께 보입니다. 받은 문자도 한국어로 옮겨 보입니다.`}</p>
      {!CALLABLE_LANGUAGES.has(language) && <p className="ct-hint is-warn">{NOT_CALLABLE}</p>}
    </>
  );
}

/** 성별 · 언어 · 음성(자동/직접 지정). 음성 SDK 가 음성 목록을 주지 않아(Task 99 · 진단 P9) 직접 지정은 음성 id 를 손으로 넣는다. */
function ProfileFields({ v, set, voiceError }: { v: Values; set: SetValue; voiceError?: string }) {
  const genders = [
    ['male', '남'],
    ['female', '여'],
    ['unknown', '모름'],
  ] as const;
  return (
    <div className="ct-field ct-stack">
      <fieldset className="ct-fieldset" aria-label="성별">
        <legend className="ct-label">성별</legend>
        <div className="ct-checks">
          {genders.map(([key, label]) => (
            <label key={key} className="ct-check">
              <input type="radio" name="ct-gender" checked={v.gender === key} onChange={() => set('gender', key)} />
              {label}
            </label>
          ))}
        </div>
      </fieldset>
      <label className="ct-fld-label">
        <span className="ct-label">언어</span>
        <select className="ct-input" value={v.language} onChange={(e) => set('language', e.target.value as Language)}>
          {LANGUAGES.map((l) => (
            <option key={l.key} value={l.key}>
              {l.label}
            </option>
          ))}
        </select>
      </label>
      <LanguageHint language={v.language} />
      <fieldset className="ct-fieldset" aria-label="음성">
        <legend className="ct-label">음성(AI 전화)</legend>
        <div className="ct-checks">
          <label className="ct-check">
            <input type="radio" name="ct-voice" checked={v.voice_mode === 'auto'} onChange={() => set('voice_mode', 'auto')} />
            자동
          </label>
          <label className="ct-check">
            <input type="radio" name="ct-voice" checked={v.voice_mode === 'manual'} onChange={() => set('voice_mode', 'manual')} />
            직접 지정
          </label>
        </div>
        {v.voice_mode === 'manual' ? (
          <label className="ct-fld-label">
            <span className="ct-label">음성 id</span>
            <input className="ct-input" value={v.voice_id} maxLength={64} placeholder="공급자의 음성 이름" autoComplete="off" spellCheck={false} onChange={(e) => set('voice_id', e.target.value)} />
          </label>
        ) : null}
        <p className="ct-hint">
          {v.voice_mode === 'manual'
            ? '음성 SDK 가 음성 목록을 주지 않아 음성 id 를 직접 넣습니다 — 영문·숫자와 . _ : - 로 64자까지.'
            : '자동은 설정의 「AI 전화」에서 고른 음성(연락처 성별·언어에 맞춰)입니다.'}
        </p>
        {v.voice_mode === 'manual' && (
          <p className="ct-hint is-warn">공급자에 없는 이름이면 이 사람에게 거는 전화는 상대가 받은 뒤 끊깁니다. 설정의 「AI 전화」 음성 칸에 같은 이름을 넣고 [음성 진단]으로 먼저 확인하세요.</p>
        )}
        <Err text={voiceError} />
      </fieldset>
    </div>
  );
}

/** 수신 거부: 켜기는 누구나, 풀기는 관리자만. 번호에 붙어 모든 프로젝트에서 막힌다. */
function DncField({ v, set, error, reasonError }: { v: Values; set: SetValue; error?: string; reasonError?: string }) {
  return (
    <div className="ct-field is-wide ct-dnc">
      <label className="ct-check">
        <input type="checkbox" checked={v.dnc} onChange={(e) => set('dnc', e.target.checked)} />
        수신 거부
      </label>
      <p className="ct-hint">켜기는 누구나, 풀기는 관리자만 — 번호에 붙어 이 번호가 있는 모든 프로젝트에서 막힙니다.</p>
      {v.dnc && (
        <Fld label="까닭" error={reasonError}>
          <input className="ct-input" value={v.dnc_reason} maxLength={200} placeholder="예: 본인 요청" onChange={(e) => set('dnc_reason', e.target.value)} />
        </Fld>
      )}
      <Err text={error} />
    </div>
  );
}

interface PhoneProps {
  detail: PersonDetail | null;
  mode: PhoneMode;
  phone: string;
  setPhone: (s: string) => void;
  dirty: boolean;
  error?: string;
  onReveal: () => void;
  onChange: () => void;
}

/** 전화번호: 가린 꼴 + [눌러서 보기][번호 바꾸기], 또는 입력칸. 수신 거부인 사람이면 번호를 바꿔도 옛 번호는 막힌다는 한 줄. */
function PhoneField({ detail, mode, phone, setPhone, dirty, error, onReveal, onChange }: PhoneProps) {
  const kind = detail?.phone_kind && !dirty ? KIND_LABEL[detail.phone_kind] : null;
  return (
    <div className="ct-field">
      {mode === 'masked' && detail ? (
        <>
          <span className="ct-label">전화번호</span>
          <div className="ct-phone">
            <span className="ct-num">{detail.phone_masked}</span>
            {kind && <span className="ct-tag">{kind}</span>}
            <span className="ct-phone-acts">
              <button type="button" className="ct-link" onClick={onReveal}>
                눌러서 보기
              </button>
              <button type="button" className="ct-link" onClick={onChange}>
                번호 바꾸기
              </button>
            </span>
          </div>
        </>
      ) : (
        <label className="ct-fld-label">
          <span className="ct-label">
            전화번호
            {kind && <span className="ct-tag">{kind}</span>}
          </span>
          <input
            className="ct-input ct-num"
            value={phone}
            maxLength={40}
            inputMode="tel"
            autoComplete="off"
            placeholder={detail?.has_phone ? '비우면 번호를 뺍니다' : '010-0000-0000'}
            onChange={(e) => setPhone(e.target.value)}
          />
        </label>
      )}
      {detail?.do_not_contact && <p className="ct-hint is-warn">번호를 바꿔도 옛 번호는 계속 막힙니다(수신 거부는 새 번호로 따라가지 않습니다).</p>}
      <Err text={error} />
    </div>
  );
}

interface ConfirmProps {
  kind: 'number' | 'clear' | 'level';
  onCancel: () => void;
  onClear: () => void;
  onPick: (dnc: boolean) => void;
  onLevel: () => void;
}

const CONFIRM_LABEL = { number: '새 번호와 수신 거부', clear: '수신 거부 풀기', level: '관리자 등급' } as const;
const CONFIRM_TEXT = {
  number: '예전 번호는 계속 수신 거부로 남습니다. 새 번호도 수신 거부로 둘까요?',
  clear: '이 번호가 있는 모든 프로젝트에서 수신 거부가 풀립니다. 풀까요?',
  level: LEVEL_CONFIRM,
} as const;

function ConfirmBox({ kind, onCancel, onClear, onPick, onLevel }: ConfirmProps) {
  const first = useRef<HTMLButtonElement>(null);
  const box = useRef<HTMLDivElement>(null);
  // 양식 아래에 열리므로 상자 전체가 보이게 굴린 뒤 첫 단추에 초점(jsdom 에는 scrollIntoView 가 없다).
  useEffect(() => {
    box.current?.scrollIntoView?.({ block: 'nearest' });
    first.current?.focus({ preventScroll: true });
  }, []);
  return (
    <div ref={box} className="ct-confirm" role="alertdialog" aria-label={CONFIRM_LABEL[kind]} aria-describedby="ct-confirm-text">
      <p id="ct-confirm-text" className="ct-confirm-text">
        {CONFIRM_TEXT[kind]}
      </p>
      <div className="ct-actions">
        {kind === 'level' ? (
          <button ref={first} type="button" className="ui-btn ui-btn-primary" onClick={onLevel}>
            계속
          </button>
        ) : kind === 'number' ? (
          <>
            <button ref={first} type="button" className="ui-btn ui-btn-primary" onClick={() => onPick(true)}>
              새 번호도 수신 거부
            </button>
            <Button onClick={() => onPick(false)}>새 번호는 연락 가능</Button>
          </>
        ) : (
          <button ref={first} type="button" className="ui-btn ui-btn-danger" onClick={onClear}>
            수신 거부 풀기
          </button>
        )}
        <Button onClick={onCancel}>취소</Button>
      </div>
    </div>
  );
}
