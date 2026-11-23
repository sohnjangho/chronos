// 「AI 전화」 넣기·고치기 폼: 공급자 · 모델(구글은 이 키로 쓸 수 있는 목록에서, 「직접 입력」도) · 키(바꿀 때만) · AI 전화 번호(비우면 한국AI통신 연결의 번호).
import { useEffect, useState } from 'react';
import { ApiError } from '../../shared/api';
import Button from '../../shared/ui/Button';
import Field from '../../shared/ui/Field';
import type { LlmError } from './model';
import type { NotifyConnection, PhoneKind } from './notifyApi';
import { KIND_LABEL } from './NotifyPolicy';
import { ErrorLine, toProblem } from './parts';
import { voiceApi, type VoiceModels, type VoicePatch, type VoiceProvider, type VoiceSettings } from './voiceApi';

const KEY_AGAIN = '공급자를 바꾸면 음성 모델 키를 다시 넣어 주세요.';
const CUSTOM = '__custom__';
/** 서버에 묻지 못했을 때도 고를 수 있게 — 서버의 고정 목록 맨 앞과 같다. */
const DEFAULT_MODEL = 'gemini-3.8-live';

export const PROVIDERS: { value: VoiceProvider; label: string }[] = [
  { value: 'google', label: '구글 Gemini Live' },
  { value: 'openai', label: 'OpenAI Realtime' },
  { value: 'dashboard', label: '대시보드 에이전트' },
];

/** 칸 이름이 detail 에 없을 때 코드로 칸을 고른다. */
const FIELD_BY_CODE: Record<string, string> = {
  invalid_secret: 'secret',
  secret_required: 'secret',
  invalid_model: 'model',
  invalid_number: 'agent_number',
};

function fieldOf(e: unknown): string | null {
  if (!(e instanceof ApiError)) return null;
  const detail = e.detail as { field?: unknown } | null;
  if (detail && typeof detail === 'object' && typeof detail.field === 'string') return detail.field;
  return FIELD_BY_CODE[e.code] ?? null;
}

/** 이 키로 쓸 수 있는 구글 Live 모델(구글일 때만 묻는다, tick 이 바뀌면 — 새 키 — 다시 읽는다). 묻지 못하면 기본 모델 하나와 까닭. */
export function useLiveModels(id: number, on: boolean, tick: string) {
  const [found, setFound] = useState<VoiceModels | null>(null);
  useEffect(() => {
    if (!on) return;
    let live = true;
    voiceApi
      .models(id)
      .then((m) => live && setFound(m))
      .catch(() => live && setFound({ models: [DEFAULT_MODEL], default: DEFAULT_MODEL, fallback: true, refused: false, no_live: false, reason: '모델 목록을 읽지 못해 기본 모델만 보여 줍니다.' }));
    return () => {
      live = false;
    };
  }, [id, on, tick]);
  return found;
}

/** 모델 고르기: 구글은 목록 + 「직접 입력」, 다른 공급자는 지금처럼 글 칸(비우면 SDK 기본). */
function ModelPicker({ google, list, choice, custom, text, off, error, onChoice, onCustom, onText }: {
  google: boolean;
  list: VoiceModels | null;
  choice: string;
  custom: string;
  text: string;
  off: boolean;
  error?: string;
  onChoice(v: string): void;
  onCustom(v: string): void;
  onText(v: string): void;
}) {
  if (!google) {
    return (
      <Field label="모델" hint="영문·숫자·. - _ 만" error={error}>
        <input value={text} placeholder="비우면 SDK 기본 모델" autoComplete="off" spellCheck={false} disabled={off} onChange={(e) => onText(e.target.value)} />
      </Field>
    );
  }
  // 구글이 키를 거절했으면 가짜 목록을 보이지 않는다 — 지금 고른 것과 「직접 입력」만
  const blocked = !!(list?.refused || list?.no_live); // 이 키로는 어떤 Live 모델도 못 쓴다 — 가짜 목록을 보이지 않는다
  const options = blocked ? [] : list?.models.length ? list.models : [DEFAULT_MODEL];
  const shown = choice !== CUSTOM && !options.includes(choice) ? [...options, choice] : options;
  const label = (m: string) =>
    blocked ? m : m === (list?.default ?? DEFAULT_MODEL) ? `${m} (기본)` : list && !list.fallback && !list.models.includes(m) ? `${m} — 이 키로 쓸 수 없음` : m;
  const hint = !list ? '모델 목록을 읽는 중…' : list.refused ? '키가 거절돼 목록을 읽지 못했습니다' : list.no_live ? '이 키로 쓸 수 있는 실시간 음성 모델이 없습니다' : list.fallback ? (list.reason ?? '') : `이 키로 쓸 수 있는 실시간 음성 모델 ${list.models.length}개`;
  return (
    <div className="st-vc-key">
      <Field label="모델" hint={hint} error={choice === CUSTOM ? undefined : error}>
        <select aria-label="모델" value={choice} disabled={off} onChange={(e) => onChoice(e.target.value)}>
          {shown.map((m) => (
            <option key={m} value={m}>
              {label(m)}
            </option>
          ))}
          <option value={CUSTOM}>직접 입력</option>
        </select>
      </Field>
      {choice === CUSTOM && (
        <Field label="모델 이름" hint="영문·숫자·. - _ 만" error={error}>
          <input value={custom} autoComplete="off" spellCheck={false} disabled={off} autoFocus onChange={(e) => onCustom(e.target.value)} />
        </Field>
      )}
    </div>
  );
}

/**
 * AI 전화 번호: 따로 넣은 번호가 없으면 「한국AI통신 연결의 번호(…)를 씁니다」 + [다른 번호 쓰기](칸을 연다).
 * 따로 넣은 번호가 있으면 칸과 [연결의 번호로 되돌리기].
 */
function NumberLine({ conn, voice, open, clear, number, off, error, onOpen, onClear, onNumber }: {
  conn: NotifyConnection;
  voice: VoiceSettings;
  open: boolean;
  clear: boolean;
  number: string;
  off: boolean;
  error?: string;
  onOpen(on: boolean): void;
  onClear(on: boolean): void;
  onNumber(v: string): void;
}) {
  const sender = conn.sender_number_masked;
  const own = voice.agent_number_source === 'voice';
  const kind = voice.agent_number_kind ? (KIND_LABEL[voice.agent_number_kind as PhoneKind] ?? voice.agent_number_kind) : '';
  if (sender && (clear || (!own && !open))) {
    return (
      <div className="ui-field st-vc-number" role="group" aria-label="AI 전화 번호">
        <span className="ui-field-label">AI 전화 번호</span>
        <div className="st-vc-number-line">
          <span className="st-vc-number-text">{`한국AI통신 연결의 번호(${sender})를 씁니다${clear ? ' — 저장하면 바뀝니다' : ''}`}</span>
          <Button disabled={off} onClick={() => (clear ? onClear(false) : onOpen(true))}>
            {clear ? '되돌리지 않기' : '다른 번호 쓰기'}
          </Button>
        </div>
        {error && <span className="ui-field-error">{error}</span>}
      </div>
    );
  }
  const hint = own ? `지금 ${voice.agent_number_masked}${kind ? ` · ${kind}` : ''}` : '플랫폼에서 받은 070 번호를 넣어 주세요.';
  return (
    <div className="st-vc-key">
      <Field label="AI 전화 번호" hint={hint} error={error}>
        <input type="tel" value={number} placeholder="070-0000-0000" autoComplete="off" disabled={off} autoFocus={open && !own} onChange={(e) => onNumber(e.target.value)} />
      </Field>
      {sender && (
        <div className="st-actions">
          <Button disabled={off} onClick={() => (own ? onClear(true) : (onOpen(false), onNumber('')))}>
            {`연결의 번호(${sender}) 쓰기`}
          </Button>
        </div>
      )}
    </div>
  );
}

/** 넣기(저장 전) · 고치기([변경]) 폼. 바꾼 칸만 보내고, 키 칸은 끝나면 비운다. 고치기에서는 [취소]가 있다. */
export default function VoiceForm({ conn, voice, disabled, onSaved, onCancel }: {
  conn: NotifyConnection;
  voice: VoiceSettings;
  disabled: boolean;
  onSaved(v: VoiceSettings): void;
  onCancel?(): void;
}) {
  // 구글 칸의 처음 값: 저장된 구글 모델(비었으면 실제로 쓰는 기본 모델). 다른 공급자에서 바꿔 오면 기본 모델.
  const current = voice.provider === 'google' ? voice.model || voice.model_effective || DEFAULT_MODEL : DEFAULT_MODEL;
  const [provider, setProvider] = useState<VoiceProvider>(voice.provider);
  const [secret, setSecret] = useState('');
  const [choice, setChoice] = useState(current);
  const [custom, setCustom] = useState('');
  const [text, setText] = useState(voice.provider === 'google' ? '' : voice.model);
  const [number, setNumber] = useState('');
  const [open, setOpen] = useState(false);
  const [clear, setClear] = useState(false);
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<{ field: string | null; error: LlmError } | null>(null);
  const google = provider === 'google';
  const list = useLiveModels(conn.id, google, `${voice.provider}-${voice.secret_last4}`);
  const needsKey = provider !== voice.provider && provider !== 'dashboard';
  // 견줄 값: 같은 공급자의 저장된 값. 구글로 바꿔 오면(was null) 고른 모델을 늘 보낸다.
  const was = google ? (voice.provider === 'google' ? current : null) : voice.model;
  const model = google ? (choice === CUSTOM ? custom.trim() : choice) : text.trim();
  const body: VoicePatch = {
    ...(provider !== voice.provider ? { provider } : {}),
    ...(secret ? { secret } : {}),
    ...(model !== was && !(google && choice === CUSTOM && !model) ? { model } : {}),
    ...(clear ? { agent_number: null } : number.trim() ? { agent_number: number.trim() } : {}),
  };
  const off = disabled || saving;
  const err = (f: string) => (problem?.field === f ? problem.error.message : undefined);
  const save = async () => {
    setSaving(true);
    setProblem(null);
    try {
      const saved = await voiceApi.save(conn.id, body);
      setNumber('');
      setClear(false);
      setOpen(false);
      onSaved(saved);
    } catch (e) {
      setProblem({ field: fieldOf(e), error: toProblem(e) });
    } finally {
      setSecret('');
      setSaving(false);
    }
  };
  const first = !voice.saved;
  const canSave = !off && Object.keys(body).length > 0 && !(needsKey && !secret) && !(first && provider !== 'dashboard' && !secret);
  return (
    <div className="st-vc-form st-edit" role="group" aria-label={first ? 'AI 전화 설정 넣기' : 'AI 전화 설정 고치기'}>
      <div className="st-vc-grid">
        <Field label="음성 모델 공급자">
          <select aria-label="음성 모델 공급자" value={provider} disabled={off} onChange={(e) => setProvider(e.target.value as VoiceProvider)}>
            {PROVIDERS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
        </Field>
        <ModelPicker google={google} list={list} choice={choice} custom={custom} text={text} off={off} error={err('model')} onChoice={setChoice} onCustom={setCustom} onText={setText} />
        <div className="st-vc-key">
          <Field label="음성 모델 키" hint={needsKey ? KEY_AGAIN : first ? '저장하면 칸을 비우고 끝 4자리만 남깁니다.' : '바꿀 때만 넣습니다. 저장하면 칸을 비웁니다.'} error={err('secret')}>
            <input type="password" autoComplete="off" spellCheck={false} value={secret} disabled={off} placeholder={needsKey ? '새 공급자의 키' : ''} onChange={(e) => setSecret(e.target.value)} />
          </Field>
          <span className="st-muted">
            저장된 키 <span className="st-nt-num">{voice.has_secret ? `끝 4자리 ••••${voice.secret_last4}` : '없음'}</span>
          </span>
          {/* 저장된 뒤에는 카드가 늘 보인다 — 폼에서는 처음 넣을 때와 구글로 바꿀 때만 */}
          {voice.key_notice && google && (first || voice.provider !== 'google') && <p className="st-warn st-vc-notice">{voice.key_notice.message}</p>}
        </div>
        <NumberLine conn={conn} voice={voice} open={open} clear={clear} number={number} off={off} error={err('agent_number')} onOpen={setOpen} onClear={setClear} onNumber={setNumber} />
      </div>
      <div className="st-actions">
        <span className="st-gap" />
        {onCancel && (
          <Button disabled={saving} onClick={onCancel}>
            취소
          </Button>
        )}
        <Button variant="primary" disabled={!canSave} onClick={() => void save()}>
          저장
        </Button>
      </div>
      <ErrorLine error={problem && !problem.field ? problem.error : null} />
    </div>
  );
}
