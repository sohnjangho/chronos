import { useEffect, useRef, useState, type ReactNode } from 'react';
import { ApiError } from '../../shared/api';
import Badge, { type Tone } from '../../shared/ui/Badge';
import Button from '../../shared/ui/Button';
import Field from '../../shared/ui/Field';
import { checkedText, type LlmError } from './model';
import { StepLine, uncertain } from './NotifyCard';
import {
  voiceApi,
  type CallRecord,
  type NotifyConnection,
  type PhoneKind,
  type VoiceDiagnoseIn,
  type VoiceDiagnosis,
  type VoicePart,
  type VoicePatch,
  type VoiceProvider,
  type VoiceSettings,
  type VoiceStep,
  type VoiceStepId,
} from './notifyApi';
import { ConfirmPanel, KIND_LABEL } from './NotifyPolicy';
import { ErrorLine, toProblem } from './parts';

export const SDK_BAND = '음성 SDK 가 설치돼 있지 않습니다 — 설치는 PM 승인 뒤에 합니다';
const EXTRA_BAND = '고른 음성 모델에 필요한 묶음이 설치돼 있지 않습니다 — 설치는 PM 승인 뒤에 합니다';
const KEY_AGAIN = '공급자를 바꾸면 음성 모델 키를 다시 넣어 주세요.';
const CALL_UNSURE = '전화가 걸렸는지 확인 필요 — 요청이 끝나지 않았습니다. 휴대전화를 확인해 주세요. 다시 누르면 또 걸릴 수 있습니다.';
const CALL_UNKNOWN = '확인 필요 — 시험 전화가 걸렸는지·끊겼는지 모릅니다. 휴대전화를 확인해 주세요. 다시 누르면 또 걸릴 수 있습니다.';

const PROVIDERS: { value: VoiceProvider; label: string }[] = [
  { value: 'google', label: '구글 Gemini Live' },
  { value: 'openai', label: 'OpenAI Realtime' },
  { value: 'dashboard', label: '대시보드 에이전트' },
];

/** 아직 돌리지 않은 줄의 이름(진단 모듈의 이름과 같다). 돌린 줄은 서버 글을 쓴다. */
const LABELS: Record<VoiceStepId, string> = {
  P5: '음성 SDK · 플랫폼 연결',
  P6: '한국어 시험 통화',
  P7: '통화 중 받아쓰기',
  P8: '통화 중 도구 호출',
  P9: '음성 목록 · 샘플',
  P10: '둘째 언어 통화',
  P11: 'AI 전화 번호를 에이전트에 묶기',
  P12: '걸려 온 통화 받기',
  P13: '건 번호 읽기',
  P14: '받지 않고 거절하기',
};

/** 단추 셋 아래에 그 단추가 돌리는 걸음(열 줄이 늘 다 보인다). */
const GROUPS: { part: VoicePart; title: string; ids: VoiceStepId[] }[] = [
  { part: 'connection', title: '연결 확인', ids: ['P5', 'P9', 'P11'] },
  { part: 'call', title: '시험 전화', ids: ['P6', 'P7', 'P8', 'P10'] },
  { part: 'inbound', title: '받는 통화', ids: ['P12', 'P13', 'P14'] },
];

const STATUS: Record<VoiceSettings['status'], { tone: Tone; text: string }> = {
  ok: { tone: 'success', text: '연결됨' },
  failed: { tone: 'danger', text: '연결 실패' },
  unknown: { tone: 'neutral', text: '미확인' },
};

const OUTCOME: Record<CallRecord['outcome'], string> = {
  calling: '거는 중',
  placed: '걸림 · 끝남',
  unknown: '확인 필요',
  not_placed: '걸리지 않음',
};

/** 칸 이름이 detail 에 없을 때 코드로 칸을 고른다. */
const FIELD_BY_CODE: Record<string, string> = {
  invalid_secret: 'secret',
  secret_required: 'secret',
  invalid_model: 'model',
  invalid_number: 'agent_number',
};

const clock = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
const stepOf = (d: VoiceDiagnosis, id: VoiceStepId) => d.steps.find((s) => s.id === id);

/** 요청 시간 제한 — 계약 표의 가장 긴 시간 + 30초. */
function limitMs(part: VoicePart, body: VoiceDiagnoseIn, wait: number): number {
  if (part === 'connection') return 80_000;
  if (part === 'call') return ((body.steps ?? []).includes('P10') ? 240 : 120) * 1000 + 30_000;
  return (wait + ((body.steps ?? []).includes('P12') ? 95 : 63)) * 1000 + 30_000;
}

const DEFAULT_IDS: Record<VoicePart, VoiceStepId[]> = { connection: ['P5', 'P9', 'P11'], call: ['P6', 'P7', 'P8'], inbound: ['P12', 'P13', 'P14'] };

/** 진단을 돌릴 수 없는 까닭(세 단추 모두). */
function diagWhy(v: VoiceSettings): string | null {
  if (v.provider === 'dashboard') return '대시보드 에이전트 방식은 음성 진단을 하지 않습니다.';
  if (!v.has_secret) return '음성 모델 키를 먼저 넣어 주세요.';
  return null;
}

/** 실제 전화(시험 전화·받는 통화)를 쓸 수 없는 까닭. */
function callWhy(conn: NotifyConnection, v: VoiceSettings): string | null {
  if (v.test_call_index !== null && conn.allow_numbers.some((a) => a.index === v.test_call_index)) return null;
  if (conn.allow_numbers.length === 0) return '허용 번호를 먼저 넣어 주세요 — 시험 전화는 첫 허용 번호로만 겁니다.';
  if (!v.agent_number_masked) return 'AI 전화 번호를 먼저 넣어 주세요.';
  return '첫 허용 번호가 전화를 걸 수 없는 번호입니다.';
}

/** SDK 나 공급자 묶음이 없을 때의 띠. */
function bandOf(v: VoiceSettings, d: VoiceDiagnosis | null): string | null {
  if (!v.sdk_installed) return SDK_BAND;
  if (d?.state === 'done' && d.steps.find((s) => s.id === 'P5')?.code === 'sdk_extra_missing') return EXTRA_BAND;
  return null;
}

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

interface Running {
  part: VoicePart;
  /** 받는 통화: answer = 받을 통화(P12·P13), reject = 거절할 통화(P14). */
  phase: 'answer' | 'reject' | null;
  ids: VoiceStepId[];
  since: number;
}

interface Phase {
  phase: Running['phase'];
  body: VoiceDiagnoseIn;
}

/** 마지막 진단(다시 열어도 보임)과 돌리기. 한 번에 하나, 도는 동안 onRunning(true). */
function useVoiceDiagnosis(id: number, wait: number, onRunning: (on: boolean) => void, afterRun: () => void) {
  const [diag, setDiag] = useState<VoiceDiagnosis | null>(null);
  const [running, setRunning] = useState<Running | null>(null);
  const [error, setError] = useState<LlmError | null>(null);
  const [unsure, setUnsure] = useState(false);
  const [tick, setTick] = useState(0);
  const busy = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    let live = true;
    voiceApi
      .lastDiagnosis(id)
      .then((d) => live && setDiag(d ?? null))
      .catch((e) => live && setError(toProblem(e)));
    return () => {
      live = false;
    };
  }, [id, tick]);
  const reread = () => setTick((t) => t + 1);

  async function once(part: VoicePart, p: Phase): Promise<VoiceDiagnosis> {
    setRunning({ part, phase: p.phase, ids: p.body.steps ?? DEFAULT_IDS[part], since: Date.now() });
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), limitMs(part, p.body, wait));
    try {
      return await voiceApi.diagnose(id, p.body, ctl.signal);
    } finally {
      clearTimeout(timer);
    }
  }

  /** 걸음 묶음을 차례로. next 가 거짓이면 멈춘다. 돌려준 값: 멈춘 오류 코드(없으면 null). */
  async function run(part: VoicePart, phases: Phase[], next: (d: VoiceDiagnosis) => boolean = () => true): Promise<string | null> {
    if (busy.current) return 'busy';
    busy.current = true;
    onRunning(true);
    setError(null);
    setUnsure(false);
    try {
      for (const p of phases) {
        const d = await once(part, p);
        if (!mounted.current) return null;
        setDiag(d);
        if (!next(d)) break;
      }
      return null;
    } catch (e) {
      if (!mounted.current) return null;
      if (uncertain(e)) {
        // 끝을 모른다(끊김·5xx·시간 제한): 다시 걸지 않고 서버에 남은 마지막 진단을 읽는다.
        if (part === 'call') setUnsure(true);
        else setError({ code: 'unknown', message: '결과를 받지 못했습니다 — 서버에 남은 마지막 결과를 다시 읽었습니다.' });
        reread();
        return 'unsure';
      }
      setError(toProblem(e));
      return e instanceof ApiError ? e.code : 'unknown';
    } finally {
      busy.current = false;
      if (mounted.current) setRunning(null);
      onRunning(false);
      afterRun();
    }
  }
  return { diag, running, error, unsure, run, reread };
}

type Diag = ReturnType<typeof useVoiceDiagnosis>;

/** 확인 창을 열 때 본 것(첫 허용 번호의 가린 꼴·목록 판)에 묶인 실제 통화 하나. */
interface Pending {
  kind: 'call' | 'inbound';
  recall: boolean;
  p10: boolean;
  version: string;
  target: string;
}

/** 실제 통화: 「실제 통화 포함」 켬 → 단추 → 확인 창 → 한 번. 409 판 바뀜이면 새 번호로 확인 창을 다시 연다. */
function useRealCall(conn: NotifyConnection, voice: VoiceSettings | null, d: Diag, reload: () => void) {
  const [real, setReal] = useState(false);
  const [p10, setP10] = useState(false);
  const [pending, setPending] = useState<Pending | null>(null);
  const [recall, setRecall] = useState(false);
  const [reask, setReask] = useState<Omit<Pending, 'target'> | null>(null);
  const target = voice ? conn.allow_numbers.find((a) => a.index === voice.test_call_index)?.number_masked : undefined;
  useEffect(() => {
    if (reask && conn.allow_numbers_version !== reask.version) {
      setPending({ ...reask, version: conn.allow_numbers_version, target: target ?? '첫 허용 번호' });
      setReask(null);
    }
  }, [reask, conn.allow_numbers_version, target]);
  const ask = (kind: Pending['kind'], again = false) =>
    setPending({ kind, recall: again, p10, version: conn.allow_numbers_version, target: target ?? '첫 허용 번호' });
  const go = async () => {
    const p = pending;
    if (!p) return;
    setPending(null);
    setReal(false);
    setRecall(false);
    const base = { allow_numbers_version: p.version };
    const code =
      p.kind === 'call'
        ? await d.run('call', [
            { phase: null, body: { ...(p.p10 ? { steps: ['P6', 'P7', 'P8', 'P10'] } : {}), call: true, ...base, ...(p.recall ? { confirm_recall: true } : {}) } },
          ])
        : await d.run(
            'inbound',
            [
              { phase: 'answer', body: { steps: ['P12', 'P13'], inbound: true, ...base } },
              { phase: 'reject', body: { steps: ['P14'], inbound: true, ...base } },
            ],
            (r) => stepOf(r, 'P12')?.ok === true,
          );
    if (code === 'allow_list_changed') {
      setReask({ kind: p.kind, recall: p.recall, p10: p.p10, version: p.version });
      reload();
    }
    if (code === 'call_unknown_pending') setRecall(true);
  };
  return { real, setReal, p10, setP10, pending, recall, target, ask, go, cancel: () => setPending(null) };
}

type Real = ReturnType<typeof useRealCall>;

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

function useNow() {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  return now;
}

/** 도는 걸음과 지난 시간. 받는 통화는 어디로 걸지와 남은 시간. */
function RunningLine({ running, agent, wait }: { running: Running; agent: string; wait: number }) {
  const s = Math.max(0, Math.floor((useNow() - running.since) / 1000));
  const ids = running.ids.join(' · ');
  let text: string;
  if (running.part === 'inbound') {
    const left = `남은 시간 ${clock(Math.max(0, wait - s))}`;
    text =
      running.phase === 'reject'
        ? `한 번 더 걸어 주세요 — 이번에는 받지 않습니다 · ${left} · ${ids}`
        : `지금 휴대전화로 ${agent}에 걸어 주세요 · ${left} · ${ids}`;
  } else if (running.part === 'call') {
    text = `시험 전화 도는 중 — ${ids} · ${clock(s)} · 휴대전화가 울리면 받아 주세요`;
  } else {
    text = `음성 진단 도는 중 — ${ids} · ${clock(s)}`;
  }
  return (
    <p className="st-vc-running" role="status" aria-label="음성 진단 진행">
      {text}
    </p>
  );
}

function CallConfirm({ pending, voice, hold, onGo, onCancel }: { pending: Pending; voice: VoiceSettings; hold: boolean; onGo(): void; onCancel(): void }) {
  const lim = voice.call_limits;
  const n = Math.min(pending.p10 ? 2 : 1, lim.calls_per_request);
  if (pending.kind === 'inbound') {
    return (
      <ConfirmPanel
        label="받는 통화 확인 시작"
        text={`${pending.target} 휴대전화로 AI 전화 번호 ${voice.agent_number_masked ?? ''}에 두 번 걸어 주세요 — 첫 통화는 받고, 다음 통화는 받지 않고 거절합니다. 이쪽에서 거는 전화는 없고, 한 번에 ${lim.inbound_wait_default}초씩 기다립니다. 시작할까요?`}
        action="시작"
        disabled={hold}
      onConfirm={onGo}
        onCancel={onCancel}
      />
    );
  }
  return pending.recall ? (
    <ConfirmPanel
      label="다시 걸기 확인"
      text={`앞서 건 시험 전화가 걸렸는지 모르는 채로 ${pending.target}(으)로 다시 겁니다. 본인 번호로 전화가 최대 ${n}통 더 걸려 옵니다. 걸까요?`}
      action="다시 걸기"
      disabled={hold}
      onConfirm={onGo}
      onCancel={onCancel}
    />
  ) : (
    <ConfirmPanel
      label="실제 통화 확인"
      text={`시험 전화를 ${pending.target}(으)로 겁니다. 본인 번호로 전화가 최대 ${n}통 걸려 옵니다(한 통에 ${lim.call_seconds}초까지, 진단이 끊습니다). 걸까요?`}
      action="전화 걸기"
      disabled={hold}
      onConfirm={onGo}
      onCancel={onCancel}
    />
  );
}

/** 접어 둘 기계 세부: code · data · ran_at(서버 값 그대로). */
function machine(s: VoiceStep): string[] {
  return [
    `code ${s.code || '—'}`,
    ...(Object.keys(s.data ?? {}).length > 0 ? [`data ${JSON.stringify(s.data)}`] : []),
    ...(s.ran_at ? [`ran_at ${s.ran_at}`] : []),
  ];
}

const NOT_RUN = { tone: 'neutral' as const, text: '안 돌림' };
const RUNNING = { tone: 'warning' as const, text: '도는 중' };
const WAITING = { tone: 'neutral' as const, text: '대기' };
const P14_NOT_ASKED = '받는 통화가 확인되지 않아 돌리지 않았습니다.';

function placeholder(id: VoiceStepId, detail = '아직 돌리지 않았습니다.') {
  return { id, label: LABELS[id], ok: false, skipped: true, detail, latency_ms: null, notes: [], code: '', maybe_sent: false, pending: false };
}

/** 받는 통화에서 P12 가 확인되지 않아 P14 를 부르지 않았는가(이번 진단의 P12 줄로 안다). */
function p14NotAsked(d: VoiceDiagnosis): boolean {
  const p12 = stepOf(d, 'P12');
  const p14 = stepOf(d, 'P14');
  return d.part === 'inbound' && !!p12 && p12.ran_at === d.ran_at && !p12.ok && p14?.ran_at !== d.ran_at;
}

/** 줄 하나: 도는 중 · 대기(다른 묶음이 도는 중) · 안 돌림 · 까닭 있는 건너뜀(P14) · 서버 결과. */
function Row({ id, part, diag }: { id: VoiceStepId; part: VoicePart; diag: VoiceDiagnosis | null }) {
  if (diag?.state === 'running') {
    const mine = diag.part === null || diag.part === part;
    return mine ? (
      <StepLine s={placeholder(id, '진단이 도는 중입니다.')} badge={RUNNING} />
    ) : (
      <StepLine s={placeholder(id, '진단이 끝나면 마지막 결과가 보입니다.')} badge={WAITING} />
    );
  }
  const s = diag ? stepOf(diag, id) : undefined;
  if (id === 'P14' && diag && p14NotAsked(diag)) return <StepLine s={{ ...placeholder(id, P14_NOT_ASKED), label: s?.label ?? LABELS[id] }} />;
  // 한 번도 돌리지 않은 줄(ran_at 없음)은 「안 돌림」 — 건너뜀과 가르고, 접을 세부도 없다.
  return s?.ran_at ? <StepLine s={s} more={machine(s)} /> : <StepLine s={s ?? placeholder(id)} badge={NOT_RUN} />;
}

/** 묶음 머리의 시각 글: 도는 중이면 누른 사람·시각, 아니면 이 묶음 줄의 가장 늦은 ran_at. */
function headText(part: VoicePart, ids: VoiceStepId[], diag: VoiceDiagnosis | null): string {
  if (diag?.state === 'running') {
    return diag.part === null || diag.part === part
      ? `도는 중 — ${diag.by ?? '누군지 모름'} · ${checkedText(diag.ran_at, null)}`
      : '진단이 끝난 뒤 보입니다';
  }
  const last = ids.map((id) => (diag ? stepOf(diag, id)?.ran_at : null) ?? '').sort().pop();
  if (!last) return '아직 돌리지 않음';
  return `돌린 시각 ${checkedText(last, null)}${diag?.by && last === diag.ran_at ? ` · ${diag.by}` : ''}`;
}

/** 단추 하나와 그 걸음 줄. 줄에는 판정과 서버 글만, 코드는 접어서. */
function PartGroup({ title, part, ids, diag, children }: { title: string; part: VoicePart; ids: VoiceStepId[]; diag: VoiceDiagnosis | null; children: ReactNode }) {
  return (
    <div className="st-vc-part" role="group" aria-label={title}>
      <div className="st-vc-part-head">
        <b>{title}</b>
        <span className="st-muted">{headText(part, ids, diag)}</span>
        <span className="st-gap" />
        {children}
      </div>
      <ul className="st-nt-steps">
        {ids.map((id) => (
          <Row key={id} id={id} part={part} diag={diag} />
        ))}
      </ul>
    </div>
  );
}

/** 실제 시험 전화 기록(번호 없음): 최근 5건, 새것부터, 접어서. */
function CallRecords({ calls }: { calls: CallRecord[] }) {
  if (calls.length === 0) return null;
  return (
    <details className="st-nt-notes st-nt-sends">
      <summary>{`시험 전화 기록 ${calls.length}건`}</summary>
      {calls
        .slice(-5)
        .reverse()
        .map((c, i) => (
          <div key={`${c.at}-${i}`}>{`${checkedText(c.at, null)} · ${c.by || '누군지 모름'} · ${OUTCOME[c.outcome] ?? c.outcome}`}</div>
        ))}
    </details>
  );
}

/** 띠 · 「실제 통화 포함」 · 확인 창 · 도는 중 · 경고 · 세 묶음(단추 + 걸음 줄) · 시험 전화 기록. */
function VoiceDiagnostics({ conn, voice, d, r, hold }: { conn: NotifyConnection; voice: VoiceSettings; d: Diag; r: Real; hold: boolean }) {
  const busy = hold || r.pending !== null;
  const why = diagWhy(voice);
  const band = bandOf(voice, d.diag);
  const callBlock = why ?? (band ? '음성 SDK 가 설치되면 시험 전화와 받는 통화를 확인할 수 있습니다.' : callWhy(conn, voice));
  const callUnknown = d.unsure || (d.diag?.state === 'done' && d.diag.call_unknown);
  const callOff = busy || !!callBlock || !r.real;
  const serverRunning = !d.running && d.diag?.state === 'running' ? d.diag : null;
  return (
    <>
      {band && (
        <div className="st-vc-band" role="note">
          {band}
        </div>
      )}
      <div className="st-nt-real">
        <label className="st-nt-switch">
          <input type="checkbox" role="switch" checked={r.real && !callBlock} disabled={!!callBlock || busy} onChange={(e) => r.setReal(e.target.checked)} />
          <span>{`실제 통화 포함${r.target ? ` — ${r.target}` : ''}`}</span>
        </label>
        <span className="st-muted st-nt-real-why">
          {callBlock ?? '켜면 [시험 전화]·[받는 통화 확인]을 쓸 수 있습니다. 첫 허용 번호로만 걸고, 그 번호에서 걸려 온 전화만 받습니다.'}
        </span>
      </div>
      {r.pending && <CallConfirm pending={r.pending} voice={voice} hold={hold} onGo={() => void r.go()} onCancel={r.cancel} />}
      {d.running && <RunningLine running={d.running} agent={voice.agent_number_masked ?? 'AI 전화 번호'} wait={voice.call_limits.inbound_wait_default} />}
      {serverRunning && (
        <div className="st-actions">
          <p className="st-warn">{`음성 진단이 도는 중입니다(${serverRunning.by ?? '누군지 모름'} · ${checkedText(serverRunning.ran_at, null)}). 끝난 뒤 다시 읽어 주세요.`}</p>
          <Button onClick={d.reread}>다시 읽기</Button>
        </div>
      )}
      {d.unsure && (
        <p className="st-warn" role="alert">
          {CALL_UNSURE}
        </p>
      )}
      {!d.unsure && callUnknown && <p className="st-warn">{CALL_UNKNOWN}</p>}
      <ErrorLine error={d.error} />
      {(r.recall || callUnknown) && !busy && !callBlock && !r.pending && (
        <div className="st-actions">
          <Button onClick={() => r.ask('call', true)}>그래도 다시 걸기</Button>
        </div>
      )}
      <section className="st-vc-diag" aria-label="음성 진단 결과">
        <PartGroup title="연결 확인" part={GROUPS[0].part} ids={GROUPS[0].ids} diag={d.diag}>
          <Button disabled={busy || !!why} onClick={() => void d.run('connection', [{ phase: null, body: {} }])}>
            음성 진단
          </Button>
        </PartGroup>
        <PartGroup title="시험 전화" part={GROUPS[1].part} ids={GROUPS[1].ids} diag={d.diag}>
          {d.diag?.state === 'done' && d.diag.part === 'call' && d.diag.called_real && <Badge tone="info">실제 전화 걸림</Badge>}
          <label className="st-nt-switch st-vc-p10">
            <input type="checkbox" checked={r.p10} disabled={callOff} onChange={(e) => r.setP10(e.target.checked)} />
            <span>영어 첫마디(P10)도 — 한 통 더</span>
          </label>
          <Button disabled={callOff || callUnknown} onClick={() => r.ask('call')}>
            시험 전화
          </Button>
        </PartGroup>
        <PartGroup title="받는 통화" part={GROUPS[2].part} ids={GROUPS[2].ids} diag={d.diag}>
          <Button disabled={callOff} onClick={() => r.ask('inbound')}>
            받는 통화 확인
          </Button>
        </PartGroup>
        <CallRecords calls={d.diag?.calls ?? []} />
      </section>
    </>
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
