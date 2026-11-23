import { useEffect, useState } from 'react';
import Badge, { type Tone } from '../../shared/ui/Badge';
import Button from '../../shared/ui/Button';
import { checkedText, type LlmError } from './model';
import type { NotifyConnection } from './notifyApi';
import { ConfirmPanel } from './NotifyPolicy';
import { ErrorLine, toProblem } from './parts';
import { useRealCall, useVoiceDiagnosis, VoiceDiagnostics } from './VoiceDiagnosis';
import { voiceApi, type VoiceDiagnosis, type VoiceSettings } from './voiceApi';
import VoiceForm, { PROVIDERS } from './VoiceForm';

type Mode = 'idle' | 'edit' | 'delete';

/** 끝 4자리만. 키가 없으면 「없음」. */
const maskedKey = (v: VoiceSettings) => (v.has_secret ? '•'.repeat(v.secret_last4 ? 12 : 8) + v.secret_last4 : '없음');
const providerName = (v: VoiceSettings) => PROVIDERS.find((p) => p.value === v.provider)?.label ?? v.provider;
const JUDGED = ['P5', 'P6', 'P11'];

/**
 * 카드의 상태: 서버의 status 와 마지막 진단 그대로. 결과를 모르는 것(call_unknown · pending · maybe_sent)은 「확인 필요」 — 실패로 그리지 않는다.
 * 모름 → 확인 필요 · failed → 실패 · ok → 연결됨 · 돌린 줄이 있는데 unknown → 확인 필요 · 그 밖 → 아직 진단 안 함.
 */
export function voiceStatus(v: VoiceSettings, d: VoiceDiagnosis | null): { tone: Tone; text: string } {
  const done = d?.state === 'done' ? d : null;
  const unsure = !!done && (done.call_unknown || done.steps.some((s) => JUDGED.includes(s.id) && s.ran_at && (s.pending || s.maybe_sent)));
  if (unsure) return { tone: 'warning', text: '확인 필요' }; // 결과 모름이 먼저 — 다른 곳의 실패가 있어도 실패로 그리지 않는다
  if (v.status === 'failed') return { tone: 'danger', text: '실패' };
  if (v.status === 'ok') return { tone: 'success', text: '연결됨' };
  if (done?.steps.some((s) => s.ran_at)) return { tone: 'warning', text: '확인 필요' };
  return { tone: 'neutral', text: '아직 진단 안 함' };
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

function numberText(v: VoiceSettings): string {
  if (!v.agent_number_effective_masked) return '없음 — [변경]에서 넣어 주세요';
  return `${v.agent_number_effective_masked} · ${v.agent_number_source === 'voice' ? '따로 넣은 번호' : '한국AI통신 연결의 번호'}`;
}

/** 카드의 사실: 모델 · 번호(가린 꼴과 출처) · 키 끝 4자리 · 마지막 진단(때·누가) · 최대 통화 시간. */
function Facts({ conn, voice, diag }: { conn: NotifyConnection; voice: VoiceSettings; diag: VoiceDiagnosis | null }) {
  const model = voice.model_effective || 'SDK 기본 모델';
  const ran = diag?.state === 'done' && diag.steps.some((s) => s.ran_at);
  return (
    <dl className="st-facts st-vc-facts">
      <dt>모델</dt>
      <dd>{voice.model ? model : `${model} · 기본값`}</dd>
      <dt>AI 전화 번호</dt>
      <dd>{numberText(voice)}</dd>
      <dt>음성 모델 키</dt>
      <dd>{maskedKey(voice)}</dd>
      <dt>마지막 진단</dt>
      <dd>{diag && (ran || diag.state === 'running') ? `${checkedText(diag.ran_at, null)}${diag.by ? ` · ${diag.by}` : ''}` : '아직 진단 안 함'}</dd>
      <dt>최대 통화 시간</dt>
      <dd>{`${conn.limits.max_call_seconds ?? '—'}초 — 「상한」 묶음에서 고칩니다`}</dd>
      <dt>음성</dt>
      <dd className="st-muted">준비 중 — 남성·여성·모르는 연락처에게 쓸 음성은 다음 단계에서 고릅니다.</dd>
    </dl>
  );
}

function CardHead({ voice, diag }: { voice: VoiceSettings; diag: VoiceDiagnosis | null }) {
  const status = voiceStatus(voice, diag);
  return (
    <div className="st-card-head">
      <b className="st-card-name">AI 전화</b>
      <Badge tone="info">{providerName(voice)}</Badge>
      <span className="st-gap" />
      <Badge tone={status.tone}>{status.text}</Badge>
    </div>
  );
}

/**
 * 설정 → 알림 연결 카드 안 「AI 전화」(Task 93, Task 90 계약 · 11-24 손보기).
 * 저장 전에는 넣기 폼. 저장하면 LLM 연결처럼 카드: 공급자 · 상태 / 모델 · 번호(출처) · 키 끝 4자리 · 마지막 진단 /
 * [음성 진단][시험 전화][변경] … [삭제], 그 아래 「실제 통화 포함」과 P5~P14 열 줄. [변경]은 같은 폼(키는 바꿀 때만).
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
  const [mode, setMode] = useState<Mode>('idle');
  const [outcome, setOutcome] = useState<{ note?: string; error?: LlmError | null } | null>(null);
  const [busy, setBusy] = useState(false);
  // hold = 이 카드에서 진단이 도는 중(내 것·연결 진단·다른 곳에서 돌린 것). 확인 창이 열려 있어도 다른 단추는 잠근다.
  const running = locked || d.running !== null || d.diag?.state === 'running';
  const hold = running || mode !== 'idle' || busy;
  const holding = r.pending !== null || d.diag?.state === 'running' || mode === 'delete' || busy;
  useEffect(() => onHolding(holding), [holding, onHolding]);
  const open = (m: Mode) => {
    setOutcome(null);
    r.cancel();
    setMode(m);
  };
  const saved = (s: VoiceSettings) => {
    v.setVoice(s);
    setMode('idle');
    setOutcome({ note: '저장했습니다.' });
    d.reread();
  };
  const remove = async () => {
    setBusy(true);
    try {
      await voiceApi.remove(conn.id);
      setMode('idle');
      setOutcome({ note: '「AI 전화」 설정을 지웠습니다.' });
      v.reload();
      d.reread();
    } catch (e) {
      setOutcome({ error: toProblem(e) });
    } finally {
      setBusy(false);
    }
  };
  const voice = v.voice;
  if (!voice) {
    return (
      <section className="st-nt-group st-vc" aria-label="AI 전화">
        <h4>AI 전화</h4>
        {v.error ? <ErrorLine error={v.error} /> : <p className="st-muted">불러오는 중…</p>}
      </section>
    );
  }
  if (!voice.saved) {
    return (
      <section className="st-nt-group st-vc" aria-label="AI 전화">
        <h4>AI 전화</h4>
        <p className="st-muted">협력사에게 AI 가 전화를 거는 연결입니다. 음성 모델 키를 넣고 저장하면 카드로 남아 음성 진단과 시험 전화를 할 수 있습니다.</p>
        {outcome?.note && <p className="st-note">{outcome.note}</p>}
        <VoiceForm conn={conn} voice={voice} disabled={running} onSaved={saved} />
      </section>
    );
  }
  const extra = (
    <>
      <Button disabled={hold} onClick={() => open('edit')}>
        변경
      </Button>
      <span className="st-gap" />
      <Button className="st-danger-text" disabled={hold} onClick={() => open('delete')}>
        삭제
      </Button>
    </>
  );
  const below =
    mode === 'edit' ? (
      <VoiceForm conn={conn} voice={voice} disabled={running} onSaved={saved} onCancel={() => setMode('idle')} />
    ) : mode === 'delete' ? (
      <ConfirmPanel
        label="AI 전화 삭제 확인"
        text="「AI 전화」 설정을 지울까요? 음성 모델 키·AI 전화 번호·모델과 마지막 진단 결과가 함께 지워집니다. 한국AI통신 연결은 그대로입니다."
        action="삭제"
        disabled={busy || running}
        onConfirm={() => void remove()}
        onCancel={() => setMode('idle')}
      />
    ) : null;
  return (
    <section className="st-card st-vc" aria-label="AI 전화">
      <CardHead voice={voice} diag={d.diag} />
      <Facts conn={conn} voice={voice} diag={d.diag} />
      {voice.key_notice && <p className="st-warn st-vc-notice">{voice.key_notice.message}</p>}
      <VoiceDiagnostics conn={conn} voice={voice} d={d} r={r} hold={hold} extra={extra} below={below} />
      {outcome?.note && <p className="st-note">{outcome.note}</p>}
      <ErrorLine error={outcome?.error} />
    </section>
  );
}
