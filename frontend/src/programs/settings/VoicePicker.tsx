// 「AI 전화」 카드의 음성 고르기(Task 99). 음성 SDK 가 음성 목록·샘플을 주지 않아(진단 P9 not_supported) 목록·샘플 듣기 없이
// 음성 이름(id)을 손으로 넣는 칸만 둔다. 칸: 남성 연락처 · 여성 연락처 · 성별 모름, 그리고 언어별(선택 — 비우면 위의 칸).
// 꼴 검사는 서버(Task 90 voice_schemas._voice_id)와 같다. 서버가 거절하면 그 칸 아래에 서버 글 그대로(보낸 값은 싣지 않음).
import { useState } from 'react';
import { ApiError } from '../../shared/api';
import Button from '../../shared/ui/Button';
import Field from '../../shared/ui/Field';
import type { LlmError } from './model';
import { ErrorLine, toProblem } from './parts';
import { voiceApi, type VoicePatch, type VoiceSettings } from './voiceApi';

export type Slot = 'voice_male_contact' | 'voice_female_contact' | 'voice_unknown';
type Slots = Record<Slot, string>;

export const SLOTS: { key: Slot; label: string; short: string }[] = [
  { key: 'voice_male_contact', label: '남성 연락처에게 걸 때', short: '남성 연락처' },
  { key: 'voice_female_contact', label: '여성 연락처에게 걸 때', short: '여성 연락처' },
  { key: 'voice_unknown', label: '성별 모름', short: '성별 모름' },
];
/** 연락처의 언어(한국어 밖). 한국어는 위의 세 칸이 맡는다. 저장된 다른 코드는 코드 그대로 보인다. */
export const LANGUAGES: Record<string, string> = { en: '영어', zh: '중국어', vi: '베트남어' };
/** SDK 의 기본 음성(clawops 0.78 의 GeminiRealtime·OpenAIRealtime 기본값) — 칸을 비우면 이것. */
const SDK_DEFAULT: Record<string, string> = { google: 'Gemini: Kore', openai: 'OpenAI: marin' };
const SHAPE = /^[A-Za-z][A-Za-z0-9._-]{0,99}$/;
export const BAD_SHAPE = '음성 이름은 영문으로 시작하고 영문·숫자·점(.)·줄표(-)·밑줄(_)만 쓸 수 있습니다.';
const EMPTY: Slots = { voice_male_contact: '', voice_female_contact: '', voice_unknown: '' };

export const languageName = (code: string) => LANGUAGES[code] ?? code;
export const defaultVoice = (provider: string) => (SDK_DEFAULT[provider] ? `기본 음성(${SDK_DEFAULT[provider]})` : '기본 음성');

const slotsOf = (v: VoiceSettings): Slots => ({
  voice_male_contact: v.voice_male_contact ?? '',
  voice_female_contact: v.voice_female_contact ?? '',
  voice_unknown: v.voice_unknown ?? '',
});
const badShape = (value: string) => value.trim() !== '' && !SHAPE.test(value.trim());

/** 언어별 칸에서 빈 칸·빈 언어를 뺀 꼴(서버가 저장하는 꼴과 같다). */
function cleaned(byLanguage: Record<string, Slots>): Record<string, Partial<Slots>> {
  const out: Record<string, Partial<Slots>> = {};
  for (const [code, slots] of Object.entries(byLanguage)) {
    const kept = Object.fromEntries(Object.entries(slots).map(([k, v]) => [k, v.trim()]).filter(([, v]) => v));
    if (Object.keys(kept).length) out[code] = kept;
  }
  return out;
}

const sameMap = (a: Record<string, Partial<Slots>>, b: Record<string, Record<string, string>>) => {
  const sort = (m: Record<string, Record<string, string | undefined>>) =>
    JSON.stringify(Object.keys(m).sort().map((k) => [k, Object.keys(m[k]).sort().map((s) => [s, m[k][s]])]));
  return sort(a) === sort(b);
};

/** 세 칸 한 줄. placeholder 는 비웠을 때 쓰이는 것. */
function SlotFields({ values, placeholder, off, errorOf, onChange }: {
  values: Slots;
  placeholder: string;
  off: boolean;
  errorOf(slot: Slot): string | undefined;
  onChange(slot: Slot, value: string): void;
}) {
  return (
    <div className="st-vc-grid">
      {SLOTS.map((s) => (
        <Field key={s.key} label={s.label} error={errorOf(s.key)}>
          <input value={values[s.key]} placeholder={placeholder} autoComplete="off" spellCheck={false} disabled={off} onChange={(e) => onChange(s.key, e.target.value)} />
        </Field>
      ))}
    </div>
  );
}

function fieldOf(e: unknown): string | null {
  if (!(e instanceof ApiError)) return null;
  const detail = e.detail as { field?: unknown } | null;
  return detail && typeof detail.field === 'string' ? detail.field : null;
}

export default function VoicePicker({ voice, disabled, onSaved, onCancel }: {
  voice: VoiceSettings;
  disabled: boolean;
  onSaved(v: VoiceSettings): void;
  onCancel(): void;
}) {
  const [base, setBase] = useState<Slots>(() => slotsOf(voice));
  const [byLanguage, setByLanguage] = useState<Record<string, Slots>>(() =>
    Object.fromEntries(Object.entries(voice.voices_by_language).map(([code, slots]) => [code, { ...EMPTY, ...slots }])),
  );
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<{ field: string | null; error: LlmError } | null>(null);
  const off = disabled || saving;
  const was = slotsOf(voice);
  const languages = cleaned(byLanguage);
  const body: VoicePatch = {
    ...Object.fromEntries(SLOTS.filter((s) => base[s.key].trim() !== was[s.key]).map((s) => [s.key, base[s.key].trim() || null])),
    ...(sameMap(languages, voice.voices_by_language) ? {} : { voices_by_language: languages }),
  };
  const anyBad = [...Object.values(base), ...Object.values(byLanguage).flatMap((s) => Object.values(s))].some(badShape);
  const baseError = (slot: Slot) => (badShape(base[slot]) ? BAD_SHAPE : problem?.field === slot ? problem.error.message : undefined);
  const addable = Object.keys(LANGUAGES).filter((code) => !(code in byLanguage));
  const save = async () => {
    setSaving(true);
    setProblem(null);
    try {
      onSaved(await voiceApi.save(voice.connection_id, body));
    } catch (e) {
      setProblem({ field: fieldOf(e), error: toProblem(e) });
    } finally {
      setSaving(false);
    }
  };
  return (
    <div className="st-vc-form st-edit" role="group" aria-label="음성 고르기">
      <p className="st-muted">음성 SDK 가 음성 목록과 샘플을 주지 않아 음성 이름(id)을 직접 넣습니다. 공급자 안내에 있는 음성 이름을 그대로 씁니다.</p>
      <SlotFields values={base} placeholder={`비우면 ${defaultVoice(voice.provider)}`} off={off} errorOf={baseError} onChange={(slot, value) => setBase((b) => ({ ...b, [slot]: value }))} />
      <p className="st-muted">상대와 반대 성별의 음성을 고르세요</p>
      {Object.entries(byLanguage).map(([code, slots]) => (
        <div key={code} className="st-vc-key" role="group" aria-label={`${languageName(code)} 음성`}>
          <div className="st-vc-number-line">
            <b>{`${languageName(code)} 연락처`}</b>
            <span className="st-gap" />
            <Button disabled={off} aria-label={`${languageName(code)} 빼기`} onClick={() => setByLanguage((m) => Object.fromEntries(Object.entries(m).filter(([k]) => k !== code)))}>
              빼기
            </Button>
          </div>
          <SlotFields
            values={slots}
            placeholder="비우면 위의 칸"
            off={off}
            errorOf={(slot) => (badShape(slots[slot]) ? BAD_SHAPE : undefined)}
            onChange={(slot, value) => setByLanguage((m) => ({ ...m, [code]: { ...m[code], [slot]: value } }))}
          />
        </div>
      ))}
      {addable.length > 0 && (
        <div className="st-vc-grid">
          <Field label="언어별 음성 더하기" hint="선택 — 그 언어로 말하는 연락처에게만 씁니다.">
            <select aria-label="언어별 음성 더하기" value="" disabled={off} onChange={(e) => e.target.value && setByLanguage((m) => ({ ...m, [e.target.value]: { ...EMPTY } }))}>
              <option value="">언어 고르기</option>
              {addable.map((code) => (
                <option key={code} value={code}>
                  {LANGUAGES[code]}
                </option>
              ))}
            </select>
          </Field>
        </div>
      )}
      <div className="st-actions">
        <span className="st-gap" />
        <Button disabled={saving} onClick={onCancel}>
          취소
        </Button>
        <Button variant="primary" disabled={off || anyBad || Object.keys(body).length === 0} onClick={() => void save()}>
          음성 저장
        </Button>
      </div>
      {/* 칸 이름이 없거나 언어별 칸(field = voices_by_language)이면 아래에 — 세 칸의 것은 그 칸 아래에 */}
      <ErrorLine error={problem && (!problem.field || problem.field === 'voices_by_language') ? problem.error : null} />
    </div>
  );
}
