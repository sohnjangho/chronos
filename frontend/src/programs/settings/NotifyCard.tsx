import { useEffect, useState } from 'react';
import Badge, { type Tone } from '../../shared/ui/Badge';
import Button from '../../shared/ui/Button';
import { checkedText, type LlmError } from './model';
import { NotifyKeyForm, NotifyUrlForm } from './NotifyAdd';
import { notifyApi, type DiagnoseIn, type Diagnosis, type DiagnosisStep, type NotifyConnection, type NotifyProbe, type NotifySaved } from './notifyApi';
import NotifyPolicy, { ConfirmPanel } from './NotifyPolicy';
import { ErrorLine, savedButFailed, toProblem } from './parts';

type Mode = 'idle' | 'url' | 'key' | 'delete';

interface Outcome {
  note?: string;
  probe?: NotifyProbe;
  error?: LlmError | null;
}

const STATUS: Record<NotifyConnection['status'], { tone: Tone; text: string }> = {
  ok: { tone: 'success', text: '연결됨' },
  failed: { tone: 'danger', text: '연결 실패' },
  unknown: { tone: 'neutral', text: '미확인' },
};

/** 끝 4자리만. 키가 짧아 서버가 끝자리를 주지 않으면 점만. */
const maskedKey = (last4: string) => '•'.repeat(last4 ? 12 : 8) + last4;

/** 시험 문자(첫 허용 번호로만)를 보낼 수 없는 까닭. 보낼 수 있으면 null. */
export function smsBlockedReason(c: NotifyConnection): string | null {
  if (c.test_sms_index !== null && c.allow_numbers.some((a) => a.index === c.test_sms_index)) return null;
  if (c.allow_numbers.length === 0) return '허용 번호를 먼저 넣어 주세요 — 시험 문자는 첫 허용 번호로만 갑니다.';
  if (!c.allow_numbers[0].can_test_sms) return '첫 허용 번호가 휴대전화가 아니라 시험 문자를 받을 수 없습니다.';
  if (!c.sender_number_masked) return '발신번호를 먼저 골라 주세요.';
  return '지금은 시험 문자를 보낼 수 없습니다.';
}

function Facts({ conn }: { conn: NotifyConnection }) {
  return (
    <dl className="st-facts st-nt-facts">
      <dt>주소</dt>
      <dd>{conn.base_url}</dd>
      <dt>API 키</dt>
      <dd>{maskedKey(conn.secret_last4)}</dd>
      <dt>Account ID</dt>
      <dd>{conn.account_id_masked}</dd>
      <dt>발신번호</dt>
      <dd>{conn.sender_number_masked ?? '고르지 않음'}</dd>
      <dt>확인</dt>
      <dd>{checkedText(conn.checked_at, conn.latency_ms)}</dd>
    </dl>
  );
}

function ProbeLine({ probe }: { probe: NotifyProbe }) {
  const ms = probe.latency_ms === null ? '' : ` · ${probe.latency_ms}ms`;
  return (
    <div className={`st-probe ${probe.ok ? 'st-probe-ok' : 'st-probe-fail'}`} role="status" aria-label="연결 테스트 결과">
      {probe.ok ? `연결됨 · 승인된 발신번호 ${probe.senders.length}개${ms}` : <ErrorLine error={probe.error} />}
    </div>
  );
}

function verdict(step: DiagnosisStep, unknown: boolean): { tone: Tone; text: string } {
  if (step.skipped) return { tone: 'neutral', text: '건너뜀' };
  if (unknown) return { tone: 'warning', text: '확인 필요' };
  return step.ok ? { tone: 'success', text: 'OK' } : { tone: 'danger', text: 'FAIL' };
}

/** 걸음마다 한 줄(id · 판정 · 이름 — 서버 글 · 응답 시간), notes 는 접어서. 보낸 뒤 결과를 모르는 P2 는 「확인 필요」. */
function DiagnosisView({ diag }: { diag: Diagnosis }) {
  return (
    <section className="st-nt-diag" aria-label="연결 진단 결과">
      <div className="st-nt-diag-head">
        <b>연결 진단</b>
        <span className="st-muted">{`돌린 시각 ${checkedText(diag.ran_at, null)}`}</span>
        {diag.sent_real && <Badge tone="info">실제 문자 1건 접수됨</Badge>}
      </div>
      {diag.sent_unknown && (
        <p className="st-warn">보냈는지 확인 필요 — 문자가 갔을 수도 안 갔을 수도 있습니다. 휴대전화를 먼저 확인해 주세요. 다시 누르면 두 번째 문자가 갈 수 있습니다.</p>
      )}
      <ul className="st-nt-steps">
        {diag.steps.map((s) => {
          const v = verdict(s, diag.sent_unknown && s.id === 'P2' && !s.ok);
          return (
            <li key={s.id}>
              <div className="st-nt-step">
                <b className="st-nt-step-id">{s.id}</b>
                <Badge tone={v.tone}>{v.text}</Badge>
                <span className="st-nt-step-text">
                  <span className="st-muted">{s.label}</span>
                  {` — ${s.detail}`}
                </span>
                {s.latency_ms !== null && <span className="st-count">{`${s.latency_ms}ms`}</span>}
              </div>
              {s.notes.length > 0 && (
                <details className="st-nt-notes">
                  <summary>{`메모 ${s.notes.length}줄`}</summary>
                  {s.notes.map((n, i) => (
                    <div key={i}>{n}</div>
                  ))}
                </details>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** 마지막 진단(다시 열어도 보임)과 새로 돌리기. 실제 문자는 켬 + 확인 창을 거치고, 도는 동안은 다시 못 누른다. */
function useDiagnosis(conn: NotifyConnection, onChanged: () => void) {
  const [diag, setDiag] = useState<Diagnosis | null>(null);
  const [error, setError] = useState<LlmError | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let live = true;
    notifyApi
      .lastDiagnosis(conn.id)
      .then((d) => live && setDiag(d ?? null))
      .catch((e) => live && setError(toProblem(e)));
    return () => {
      live = false;
    };
  }, [conn.id]);
  async function run(body: DiagnoseIn) {
    setBusy(true);
    setError(null);
    try {
      setDiag(await notifyApi.diagnose(conn.id, body));
    } catch (e) {
      setError(toProblem(e));
    } finally {
      setBusy(false);
    }
    onChanged();
  }
  return { diag, error, busy, run };
}

function CardHead({ conn }: { conn: NotifyConnection }) {
  const status = STATUS[conn.status];
  return (
    <div className="st-card-head">
      <b className="st-card-name">{conn.name}</b>
      <Badge tone="info">한국AI통신</Badge>
      {conn.is_default && <Badge className="st-badge-default">기본 연결</Badge>}
      <span className="st-gap" />
      <Badge tone={conn.test_mode ? 'info' : 'warning'}>{conn.test_mode ? `시험 모드 · 허용 번호 ${conn.allow_numbers.length}개` : '시험 모드 꺼짐'}</Badge>
      <Badge tone={status.tone}>{status.text}</Badge>
    </div>
  );
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

/** 알림 연결 카드: 이름·공급자·상태·주소·키 끝 4자리·Account ID·발신번호(가린 꼴)·확인 시각, 단추, 진단 결과, 아래 칸. */
export default function NotifyCard({ conn, onChanged }: { conn: NotifyConnection; onChanged(): void }) {
  const [mode, setMode] = useState<Mode>('idle');
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [busy, setBusy] = useState(false);
  const [real, setReal] = useState(false);
  const [confirm, setConfirm] = useState<'diagnose' | 'test' | null>(null);
  const d = useDiagnosis(conn, onChanged);
  const blocked = smsBlockedReason(conn);
  const target = conn.allow_numbers.find((a) => a.index === conn.test_sms_index)?.number_masked;
  const locked = busy || d.busy || mode !== 'idle' || confirm !== null;

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
    setMode(m);
  };
  const send = () => {
    const kind = confirm;
    setConfirm(null);
    setReal(false);
    void d.run(kind === 'test' ? { steps: ['P2', 'P3'], send: true } : { send: true });
  };

  return (
    <article className="st-card" aria-label={conn.name}>
      <CardHead conn={conn} />
      <Facts conn={conn} />
      <div className="st-actions">
        <Button disabled={locked} onClick={() => run(async () => ({ probe: await notifyApi.test(conn.id) }))}>
          연결 테스트
        </Button>
        <Button disabled={locked} onClick={() => (real ? setConfirm('diagnose') : void d.run({ send: false }))}>
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
      <RealSms target={target} blocked={blocked} real={real} locked={locked} onReal={setReal} onTest={() => setConfirm('test')} />
      {confirm && (
        <ConfirmPanel
          label="실제 문자 확인"
          text={`실제 문자 1건을 ${target ?? '첫 허용 번호'}(으)로 보냅니다. 요금이 들고 되돌릴 수 없습니다. 보낼까요?`}
          action="보내기"
          disabled={d.busy}
          onConfirm={send}
          onCancel={() => setConfirm(null)}
        />
      )}
      {mode === 'url' && <NotifyUrlForm conn={conn} onSaved={saved} onCancel={() => setMode('idle')} />}
      {mode === 'key' && <NotifyKeyForm conn={conn} onSaved={saved} onCancel={() => setMode('idle')} />}
      {mode === 'delete' && (
        <ConfirmPanel
          label="연결 삭제 확인"
          text={`「${conn.name}」 연결을 지울까요? 이 연결의 키·허용 번호·상한·마지막 진단도 함께 지워집니다.`}
          action="삭제"
          onConfirm={() => run(async () => (await notifyApi.remove(conn.id), {}))}
          onCancel={() => setMode('idle')}
        />
      )}
      {outcome?.note && <p className="st-note">{outcome.note}</p>}
      {outcome?.probe && <ProbeLine probe={outcome.probe} />}
      <ErrorLine error={outcome?.error} />
      {d.busy && <p className="st-note">연결 진단을 돌리는 중…</p>}
      <ErrorLine error={d.error} />
      {d.diag && <DiagnosisView diag={d.diag} />}
      <NotifyPolicy conn={conn} onChanged={onChanged} />
    </article>
  );
}
