import { useEffect, useState } from 'react';
import { ApiError } from '../../shared/api';
import Badge, { type Tone } from '../../shared/ui/Badge';
import Button from '../../shared/ui/Button';
import Field from '../../shared/ui/Field';
import { checkedText, type LlmError } from './model';
import { voiceApi, type NotifyConnection, type PhoneKind, type VoicePatch, type VoiceProvider, type VoiceSettings } from './notifyApi';
import { KIND_LABEL } from './NotifyPolicy';
import { ErrorLine, toProblem } from './parts';
import { useRealCall, useVoiceDiagnosis, VoiceDiagnostics } from './VoiceDiagnosis';

const KEY_AGAIN = '공급자를 바꾸면 음성 모델 키를 다시 넣어 주세요.';

const PROVIDERS: { value: VoiceProvider; label: string }[] = [
  { value: 'google', label: '구글 Gemini Live' },
  { value: 'openai', label: 'OpenAI Realtime' },
  { value: 'dashboard', label: '대시보드 에이전트' },
];

const STATUS: Record<VoiceSettings['status'], { tone: Tone; text: string }> = {
  ok: { tone: 'success', text: '연결됨' },
  failed: { tone: 'danger', text: '연결 실패' },
  unknown: { tone: 'neutral', text: '미확인' },
};

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

function useVoiceSettings(id: number) {
  const [voice, setVoice] = useState<VoiceSettings | null>(null);
  const [error, setError] = useState<LlmError | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    voiceApi
      .get(id)
      .then((v) => live && (setVoice(v), setError(null)))
      .catch((e) => live && setError(toProblem(e)));
    return () => {
      live = false;
    };
  }, [id, tick]);
  return { voice, setVoice, error, reload: () => setTick((t) => t + 1) };
}

function VoiceHead({ voice }: { voice: VoiceSettings | null }) {
  const status = voice ? STATUS[voice.status] : null;
  return (
    <div className="st-vc-head">
      <h4>AI 전화</h4>
      {status && <Badge tone={status.tone}>{status.text}</Badge>}
      {voice && <span className="st-muted">{checkedText(voice.checked_at, null)}</span>}
    </div>
  );
}

/** 공급자 · 키(끝 4자리만) · 모델 · AI 전화 번호(가린 꼴만). [저장] 은 바꾼 칸만 보내고, 키 칸은 끝나면 비운다. */
function VoiceForm({ conn, voice, disabled, onSaved }: { conn: NotifyConnection; voice: VoiceSettings; disabled: boolean; onSaved(v: VoiceSettings): void }) {
  const [provider, setProvider] = useState<VoiceProvider>(voice.provider);
  const [secret, setSecret] = useState('');
  const [model, setModel] = useState(voice.model);
  const [number, setNumber] = useState('');
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<{ field: string | null; error: LlmError } | null>(null);
  const [note, setNote] = useState<string | null>(null);
  useEffect(() => {
    setProvider(voice.provider);
    setModel(voice.model);
  }, [voice.provider, voice.model]);
  const needsKey = provider !== voice.provider && provider !== 'dashboard';
  const body: VoicePatch = {
    ...(provider !== voice.provider ? { provider } : {}),
    ...(secret ? { secret } : {}),
    ...(model.trim() !== voice.model ? { model: model.trim() } : {}),
    ...(number.trim() ? { agent_number: number.trim() } : {}),
  };
  const off = disabled || saving;
  const err = (f: string) => (problem?.field === f ? problem.error.message : undefined);
  const save = async () => {
    setSaving(true);
    setProblem(null);
    setNote(null);
    try {
      const saved = await voiceApi.save(conn.id, body);
      setNumber('');
      setNote('저장했습니다.');
      onSaved(saved);
    } catch (e) {
      setProblem({ field: fieldOf(e), error: toProblem(e) });
    } finally {
      setSecret('');
      setSaving(false);
    }
  };
  const kind = voice.agent_number_kind ? (KIND_LABEL[voice.agent_number_kind as PhoneKind] ?? voice.agent_number_kind) : '';
  return (
    <div className="st-vc-form" role="group" aria-label="음성 설정">
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
        <Field label="모델" hint="영문·숫자·. - _ 만" error={err('model')}>
          <input value={model} placeholder="비우면 SDK 기본 모델" autoComplete="off" spellCheck={false} disabled={off} onChange={(e) => setModel(e.target.value)} />
        </Field>
        <div className="st-vc-key">
          <Field label="음성 모델 키" hint={needsKey ? KEY_AGAIN : '바꿀 때만 넣습니다. 저장하면 칸을 비웁니다.'} error={err('secret')}>
            <input type="password" autoComplete="off" spellCheck={false} value={secret} disabled={off} placeholder={needsKey ? '새 공급자의 키' : ''} onChange={(e) => setSecret(e.target.value)} />
          </Field>
          <span className="st-muted">
            저장된 키 <span className="st-nt-num">{voice.has_secret ? `끝 4자리 ••••${voice.secret_last4}` : '없음'}</span>
          </span>
          {voice.key_notice && provider === 'google' && <p className="st-warn st-vc-notice">{voice.key_notice.message}</p>}
        </div>
        <Field
          label="AI 전화 번호"
          hint={voice.agent_number_masked ? `지금 ${voice.agent_number_masked}${kind ? ` · ${kind}` : ''}` : '없음 — 플랫폼에서 받은 070 번호를 넣어 주세요.'}
          error={err('agent_number')}
        >
          <input type="tel" value={number} placeholder="070-0000-0000" autoComplete="off" disabled={off} onChange={(e) => setNumber(e.target.value)} />
        </Field>
      </div>
      <dl className="st-facts st-vc-facts">
        <dt>최대 통화 시간</dt>
        <dd>{`${conn.limits.max_call_seconds ?? '—'}초 — 「상한」 묶음에서 고칩니다`}</dd>
        <dt>음성</dt>
        <dd className="st-muted">준비 중 — 남성·여성·모르는 연락처에게 쓸 음성은 다음 단계에서 고릅니다.</dd>
      </dl>
      <div className="st-actions">
        <Button variant="primary" disabled={off || Object.keys(body).length === 0 || (needsKey && !secret)} onClick={() => void save()}>
          저장
        </Button>
        {note && <span className="st-note">{note}</span>}
      </div>
      <ErrorLine error={problem && !problem.field ? problem.error : null} />
    </div>
  );
}

/**
 * 설정 → 알림 연결 카드 안 「AI 전화」 묶음(Task 93, Task 90 계약).
 * 공급자 · 키(끝 4자리만) · 모델 · AI 전화 번호 · 최대 통화 시간(보기만) · 음성 진단 세 단추와 P5~P14 열 줄.
 * locked = 같은 카드의 연결 진단 등이 도는 중. onRunning = 음성 진단이 도는지(카드가 다른 단추를 잠근다).
 */
export default function VoiceBlock({ conn, locked, onRunning, onHolding, onChanged }: {
  conn: NotifyConnection;
  locked: boolean;
  onRunning(on: boolean): void;
  /** 확인 창이 열려 있거나 서버가 음성 진단을 돌리는 중 — 카드가 다른 단추를 잠근다. */
  onHolding(on: boolean): void;
  onChanged(): void;
}) {
  const v = useVoiceSettings(conn.id);
  const d = useVoiceDiagnosis(conn.id, v.voice?.call_limits.inbound_wait_default ?? 90, onRunning, v.reload);
  const r = useRealCall(conn, v.voice, d, () => (onChanged(), v.reload()));
  // hold = 이 카드에서 진단이 도는 중(내 것·연결 진단·다른 곳에서 돌린 것). 확인 창이 열려 있어도 다른 단추는 잠근다.
  const hold = locked || d.running !== null || d.diag?.state === 'running';
  const holding = r.pending !== null || d.diag?.state === 'running';
  useEffect(() => onHolding(holding), [holding, onHolding]);
  return (
    <section className="st-nt-group st-vc" aria-label="AI 전화">
      <VoiceHead voice={v.voice} />
      {v.voice ? (
        <>
          <VoiceForm
            conn={conn}
            voice={v.voice}
            disabled={hold}
            onSaved={(saved) => (v.setVoice(saved), d.reread())}
          />
          <VoiceDiagnostics conn={conn} voice={v.voice} d={d} r={r} hold={hold} />
        </>
      ) : v.error ? (
        <ErrorLine error={v.error} />
      ) : (
        <p className="st-muted">불러오는 중…</p>
      )}
    </section>
  );
}
