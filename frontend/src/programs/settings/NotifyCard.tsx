import { useEffect, useState } from 'react';
import { ApiError } from '../../shared/api';
import Badge, { type Tone } from '../../shared/ui/Badge';
import Button from '../../shared/ui/Button';
import KakaoBlock from './KakaoBlock';
import { checkedText, type LlmError } from './model';
import { NotifyKeyForm, NotifyUrlForm } from './NotifyAdd';
import {
  notifyApi,
  type DiagnoseIn,
  type Diagnosis,
  type NotifyConnection,
  type NotifyProbe,
  type NotifySaved,
  type SendRecord,
} from './notifyApi';
import NotifyPolicy, { ConfirmPanel } from './NotifyPolicy';
import { ErrorLine, savedButFailed, StepLine, toProblem, uncertain } from './parts';
import VoiceBlock from './VoiceBlock';

type Mode = 'idle' | 'url' | 'key' | 'delete';
type SendKind = 'diagnose' | 'test';

interface Outcome {
  note?: string;
  probe?: NotifyProbe;
  error?: LlmError | null;
}

/** 확인 창을 열 때 본 것(받을 번호·목록 판)에 묶인 보내기 하나. */
interface PendingSend {
  kind: SendKind;
  resend: boolean;
  version: string;
  target: string;
}

const STATUS: Record<NotifyConnection['status'], { tone: Tone; text: string }> = {
  ok: { tone: 'success', text: '연결됨' },
  failed: { tone: 'danger', text: '연결 실패' },
  unknown: { tone: 'neutral', text: '미확인' },
};

const OUTCOME: Record<SendRecord['outcome'], string> = {
  sending: '보내는 중',
  accepted: '접수됨',
  unknown: '확인 필요',
  not_sent: '보내지 않음',
};

export const UNSURE = '보냈는지 확인 필요 — 휴대전화에 문자가 왔는지 먼저 확인해 주세요';

/** 끝 4자리만(시안 ④ 「키 …a1B2」). 키가 짧아 서버가 끝자리를 주지 않으면 점만. */
const maskedKey = (last4: string) => (last4 ? `…${last4}` : '••••');

/** 시험 문자(첫 허용 번호로만)를 보낼 수 없는 까닭. 보낼 수 있으면 null. */
export function smsBlockedReason(c: NotifyConnection): string | null {
  if (c.test_sms_index !== null && c.allow_numbers.some((a) => a.index === c.test_sms_index)) return null;
  if (c.allow_numbers.length === 0) return '허용 번호를 먼저 넣어 주세요 — 시험 문자는 첫 허용 번호로만 갑니다.';
  if (!c.allow_numbers[0].can_test_sms) return '첫 허용 번호가 휴대전화가 아니라 시험 문자를 받을 수 없습니다.';
  if (!c.sender_number_masked) return '발신번호를 먼저 골라 주세요.';
  return '지금은 시험 문자를 보낼 수 없습니다.';
}

function CardHead({ conn }: { conn: NotifyConnection }) {
  const status = STATUS[conn.status];
  return (
    <div className="st-card-head">
      <b className="st-card-name">{conn.name}</b>
      {conn.name !== '한국AI통신' && <Badge tone="info">한국AI통신</Badge>}
      {conn.is_default && <Badge className="st-badge-default">기본 연결</Badge>}
      <span className="st-gap" />
      <Badge tone={conn.test_mode ? 'info' : 'warning'}>{conn.test_mode ? `시험 모드 · 허용 번호 ${conn.allow_numbers.length}개` : '시험 모드 꺼짐'}</Badge>
      <Badge tone={status.tone}>{status.text}</Badge>
    </div>
  );
}

/** 카드 아래 한 줄(시안 ④): 주소(https:// 없이) · 키 끝 4자리 · Account ID(가린 꼴) · 확인 시각. 발신번호는 아래 「발신번호」 묶음에. */
function Facts({ conn }: { conn: NotifyConnection }) {
  const at = conn.checked_at ? `${checkedText(conn.checked_at, null)} 확인` : checkedText(null, null);
  const parts = [conn.base_url.replace(/^https:\/\//, ''), `키 ${maskedKey(conn.secret_last4)}`, `Account ID ${conn.account_id_masked}`, at];
  return <p className="st-muted st-nt-facts">{parts.join(' · ')}</p>;
}

/** 연결 테스트 결과 한 줄(시안 ④) — 서버가 저장된 확인 결과·오늘 사용량으로 만든 글 그대로. */
function CheckSummary({ conn }: { conn: NotifyConnection }) {
  if (!conn.check_summary) return null;
  const tone = conn.status === 'failed' ? 'st-warn' : 'st-muted';
  return <p className={`${tone} st-nt-check`}>{`연결 테스트 결과: ${conn.check_summary}`}</p>;
}

function ProbeLine({ probe }: { probe: NotifyProbe }) {
  const ms = probe.latency_ms === null ? '' : ` · ${probe.latency_ms}ms`;
  return (
    <div className={`st-probe ${probe.ok ? 'st-probe-ok' : 'st-probe-fail'}`} role="status" aria-label="연결 테스트 결과">
      {probe.ok ? `연결됨 · 승인된 발신번호 ${probe.senders.length}개${ms}` : <ErrorLine error={probe.error} />}
    </div>
  );
}

/** 실제 시험 문자 기록(번호 없음): 최근 5건, 새것부터, 접어서. */
function SendRecords({ sends }: { sends: SendRecord[] }) {
  if (sends.length === 0) return null;
  const recent = sends.slice(-5).reverse();
  return (
    <details className="st-nt-notes st-nt-sends">
      <summary>{`시험 문자 기록 ${sends.length}건`}</summary>
      {recent.map((r, i) => (
        <div key={`${r.at}-${i}`}>{`${checkedText(r.at, null)} · ${r.by ?? '누군지 모름'} · ${OUTCOME[r.outcome] ?? r.outcome}`}</div>
      ))}
    </details>
  );
}

/** 걸음마다 한 줄(id · 판정 · 이름 — 서버 글 · 응답 시간), notes 는 접어서, 보내는 중·보냈는지 모름은 「확인 필요」. */
function DiagnosisView({ diag }: { diag: Diagnosis }) {
  return (
    <section className="st-nt-diag" aria-label="연결 진단 결과">
      <div className="st-nt-diag-head">
        <b>연결 진단</b>
        <span className="st-muted">{`돌린 시각 ${checkedText(diag.ran_at, null)}${diag.by ? ` · ${diag.by}` : ''}`}</span>
        {diag.sent_real && <Badge tone="info">실제 문자 1건 접수됨</Badge>}
      </div>
      {diag.state === 'sending' && (
        <p className="st-warn">{`확인 필요 — 시험 문자를 보내는 중이거나 결과가 아직 없습니다${diag.by ? `(${diag.by})` : ''}. 휴대전화를 먼저 확인해 주세요.`}</p>
      )}
      {diag.state !== 'sending' && diag.sent_unknown && (
        <p className="st-warn">보냈는지 확인 필요 — 문자가 갔을 수도 안 갔을 수도 있습니다. 휴대전화를 먼저 확인해 주세요. 다시 누르면 두 번째 문자가 갈 수 있습니다.</p>
      )}
      <ul className="st-nt-steps">
        {diag.steps.map((s) => (
          <StepLine key={s.id} s={s} />
        ))}
      </ul>
      <SendRecords sends={diag.sends ?? []} />
    </section>
  );
}

/** 마지막 진단(다시 열어도 보임)과 새로 돌리기. 보내기가 200 으로 끝나지 않고 거절도 아니면 「확인 필요」 + 마지막 진단 다시 읽기. */
function useDiagnosis(conn: NotifyConnection, onChanged: () => void) {
  const [diag, setDiag] = useState<Diagnosis | null>(null);
  const [error, setError] = useState<LlmError | null>(null);
  const [unsure, setUnsure] = useState(false);
  const [busy, setBusy] = useState(false);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    notifyApi
      .lastDiagnosis(conn.id)
      .then((d) => live && setDiag(d ?? null))
      .catch((e) => live && setError(toProblem(e)));
    return () => {
      live = false;
    };
  }, [conn.id, tick]);
  /** 돌려준 값: 실패한 오류 코드(없으면 null). */
  async function run(body: DiagnoseIn): Promise<string | null> {
    setBusy(true);
    setError(null);
    setUnsure(false);
    try {
      setDiag(await notifyApi.diagnose(conn.id, body));
      return null;
    } catch (e) {
      if (body.send && uncertain(e)) {
        setUnsure(true);
        setTick((t) => t + 1);
        return 'unsure';
      }
      setError(toProblem(e));
      return e instanceof ApiError ? e.code : 'unknown';
    } finally {
      setBusy(false);
      onChanged();
    }
  }
  return { diag, error, unsure, busy, run };
}

/** 「실제 문자 1건 보내기」 켬과 [시험 문자]. 보낼 수 없으면 둘 다 잠그고 까닭을 보인다. */
function RealSms({ target, blocked, real, locked, onReal, onTest }: {
  target: string | undefined;
  blocked: string | null;
  real: boolean;
  locked: boolean;
  onReal(on: boolean): void;
  onTest(): void;
}) {
  return (
    <div className="st-nt-real">
      <label className="st-nt-switch">
        <input type="checkbox" role="switch" checked={real && !blocked} disabled={!!blocked || locked} onChange={(e) => onReal(e.target.checked)} />
        <span>{`실제 문자 1건 보내기${target ? ` — ${target}(으)로` : ''}`}</span>
      </label>
      <Button disabled={!!blocked || !real || locked} onClick={onTest}>
        시험 문자
      </Button>
      <span className="st-muted st-nt-real-why">{blocked ?? '켜면 [연결 진단]·[시험 문자]가 첫 허용 번호로 실제 문자 1건을 보냅니다(요금이 듭니다).'}</span>
    </div>
  );
}

function SendConfirm({ pending, busy, onSend, onCancel }: { pending: PendingSend; busy: boolean; onSend(): void; onCancel(): void }) {
  return pending.resend ? (
    <ConfirmPanel
      label="다시 보내기 확인"
      text={`앞서 보낸 시험 문자가 갔는지 모르는 채로 ${pending.target}(으)로 한 건 더 보냅니다. 두 번째 문자가 갈 수 있고 요금이 듭니다. 보낼까요?`}
      action="다시 보내기"
      disabled={busy}
      onConfirm={onSend}
      onCancel={onCancel}
    />
  ) : (
    <ConfirmPanel
      label="실제 문자 확인"
      text={`실제 문자 1건을 ${pending.target}(으)로 보냅니다. 요금이 들고 되돌릴 수 없습니다. 보낼까요?`}
      action="보내기"
      disabled={busy}
      onConfirm={onSend}
      onCancel={onCancel}
    />
  );
}

/** 실제 문자 보내기: 켬 → 확인 창(그때의 받을 번호·목록 판에 묶임) → 한 번. 409 sent_unknown_pending 이면 따로 [그래도 다시 보내기]. */
function useRealSend(conn: NotifyConnection, d: ReturnType<typeof useDiagnosis>) {
  const [real, setReal] = useState(false);
  const [pending, setPending] = useState<PendingSend | null>(null);
  const [resendKind, setResendKind] = useState<SendKind | null>(null);
  const target = conn.allow_numbers.find((a) => a.index === conn.test_sms_index)?.number_masked;
  const ask = (kind: SendKind, resend = false) => {
    if (!resend) setResendKind(null);
    setPending({ kind, resend, version: conn.allow_numbers_version, target: target ?? '첫 허용 번호' });
  };
  const send = async () => {
    const p = pending;
    if (!p) return;
    setPending(null);
    setReal(false);
    setResendKind(null);
    const body: DiagnoseIn = {
      ...(p.kind === 'test' ? { steps: ['P2', 'P3'] } : {}),
      send: true,
      allow_numbers_version: p.version,
      ...(p.resend ? { confirm_resend: true as const } : {}),
    };
    if ((await d.run(body)) === 'sent_unknown_pending') setResendKind(p.kind);
  };
  const reset = () => {
    setPending(null);
    setResendKind(null);
  };
  /** 확인 창만 닫는다(서버가 막은 다시 보내기 단추는 남긴다). */
  const cancel = () => setPending(null);
  return { real, setReal, pending, resendKind, target, ask, send, cancel, reset };
}

/** 알림 연결 카드: 이름·공급자·상태·주소·키 끝 4자리·Account ID·발신번호(가린 꼴)·확인 시각, 단추, 진단 결과, 아래 칸. */
export default function NotifyCard({ conn, onChanged }: { conn: NotifyConnection; onChanged(): void }) {
  const [mode, setMode] = useState<Mode>('idle');
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [busy, setBusy] = useState(false);
  const [voiceBusy, setVoiceBusy] = useState(false);
  const [voiceHolding, setVoiceHolding] = useState(false);
  const [kakaoBusy, setKakaoBusy] = useState(false);
  const d = useDiagnosis(conn, onChanged);
  const r = useRealSend(conn, d);
  const blocked = smsBlockedReason(conn);
  // 이 카드가 하는 일(진단·연결 테스트·열린 확인 창·고치기 창)이 있으면 「AI 전화」 쪽을 잠근다. 거꾸로도 같다.
  const own = busy || d.busy || mode !== 'idle' || r.pending !== null || kakaoBusy;
  const locked = own || voiceBusy || voiceHolding;

  async function run(task: () => Promise<Outcome>) {
    setMode('idle');
    setBusy(true);
    setOutcome(null);
    try {
      setOutcome(await task());
    } catch (e) {
      setOutcome({ error: toProblem(e) });
    } finally {
      setBusy(false);
    }
    onChanged();
  }
  const saved = (s: NotifySaved) => {
    setMode('idle');
    setOutcome(s.error ? { error: savedButFailed(s.error) } : { note: '저장했습니다.' });
    onChanged();
  };
  const edit = (m: Mode) => {
    setOutcome(null);
    r.reset();
    setMode(m);
  };
  const diagnose = () => (r.real ? r.ask('diagnose') : (r.reset(), void d.run({ send: false })));

  return (
    <article className="st-card" aria-label={conn.name}>
      <CardHead conn={conn} />
      <Facts conn={conn} />
      <div className="st-actions">
        <Button disabled={locked} onClick={() => run(async () => ({ probe: await notifyApi.test(conn.id) }))}>
          연결 테스트
        </Button>
        <Button disabled={locked} onClick={diagnose}>
          연결 진단
        </Button>
        <Button disabled={locked} onClick={() => edit('url')}>
          URL 수정
        </Button>
        <Button disabled={locked} onClick={() => edit('key')}>
          키 교체
        </Button>
        <span className="st-gap" />
        <Button className="st-danger-text" disabled={locked} onClick={() => edit('delete')}>
          삭제
        </Button>
      </div>
      <CheckSummary conn={conn} />
      <RealSms target={r.target} blocked={blocked} real={r.real} locked={locked} onReal={r.setReal} onTest={() => r.ask('test')} />
      {r.pending && <SendConfirm pending={r.pending} busy={d.busy || voiceBusy} onSend={() => void r.send()} onCancel={r.cancel} />}
      {mode === 'url' && <NotifyUrlForm conn={conn} onSaved={saved} onCancel={() => setMode('idle')} />}
      {mode === 'key' && <NotifyKeyForm conn={conn} onSaved={saved} onCancel={() => setMode('idle')} />}
      {mode === 'delete' && (
        <ConfirmPanel
          label="연결 삭제 확인"
          text={`「${conn.name}」 연결을 지울까요? 이 연결의 키·허용 번호·상한·마지막 진단도 함께 지워집니다.`}
          action="삭제"
          disabled={busy || d.busy || voiceBusy}
          onConfirm={() => run(async () => (await notifyApi.remove(conn.id), {}))}
          onCancel={() => setMode('idle')}
        />
      )}
      {outcome?.note && <p className="st-note">{outcome.note}</p>}
      {outcome?.probe && <ProbeLine probe={outcome.probe} />}
      <ErrorLine error={outcome?.error} />
      {d.busy && <p className="st-note">연결 진단을 돌리는 중… 끝날 때까지 아래 설정도 잠급니다.</p>}
      {d.unsure && (
        <p className="st-warn" role="alert">
          {UNSURE}
        </p>
      )}
      <ErrorLine error={d.error} />
      {r.resendKind && !locked && (
        <div className="st-actions">
          <Button onClick={() => r.ask(r.resendKind ?? 'test', true)}>그래도 다시 보내기</Button>
        </div>
      )}
      {d.diag && <DiagnosisView diag={d.diag} />}
      <NotifyPolicy
        conn={conn}
        locked={d.busy || voiceBusy}
        onChanged={onChanged}
        voice={<VoiceBlock conn={conn} locked={own} onRunning={setVoiceBusy} onHolding={setVoiceHolding} onChanged={onChanged} />}
        kakao={<KakaoBlock conn={conn} locked={locked} onBusy={setKakaoBusy} />}
      />
    </article>
  );
}
