// 「AI 전화」 음성 진단: 세 단추(연결 확인 · 시험 전화 · 받는 통화)와 P5~P14 걸음 줄, 실제 통화 확인 창, 도는 중 표시.
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { ApiError } from '../../shared/api';
import Badge from '../../shared/ui/Badge';
import Button from '../../shared/ui/Button';
import { checkedText, type LlmError } from './model';
import type { NotifyConnection } from './notifyApi';
import { ConfirmPanel } from './NotifyPolicy';
import { ErrorLine, StepLine, toProblem, uncertain } from './parts';
import {
  voiceApi,
  type CallRecord,
  type VoiceDiagnoseIn,
  type VoiceDiagnosis,
  type VoicePart,
  type VoiceSettings,
  type VoiceStep,
  type VoiceStepId,
} from './voiceApi';

export const SDK_BAND = '음성 SDK 가 설치돼 있지 않습니다 — 설치는 PM 승인 뒤에 합니다';
const EXTRA_BAND = '고른 음성 모델에 필요한 묶음이 설치돼 있지 않습니다 — 설치는 PM 승인 뒤에 합니다';
const CALL_UNSURE = '전화가 걸렸는지 확인 필요 — 요청이 끝나지 않았습니다. 휴대전화를 확인해 주세요. 다시 누르면 또 걸릴 수 있습니다.';
const CALL_UNKNOWN = '확인 필요 — 시험 전화가 걸렸는지·끊겼는지 모릅니다. 휴대전화를 확인해 주세요. 다시 누르면 또 걸릴 수 있습니다.';

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

const OUTCOME: Record<CallRecord['outcome'], string> = {
  calling: '거는 중',
  placed: '걸림 · 끝남',
  unknown: '확인 필요',
  not_placed: '걸리지 않음',
};

const clock = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
const stepOf = (d: VoiceDiagnosis, id: VoiceStepId) => d.steps.find((s) => s.id === id);

/**
 * 서버의 덩어리(한 번의 연결)마다 시간 상한(초) — backend/app/programs/notify_settings/voice.py:121 `_ceiling` 을 그대로 옮긴 값.
 * 받는 통화는 여기에 기다림(wait)을 더한다. 서버 쪽 시험(test_chunk_ceilings_match_what_the_screen_mirrors)이 같은 값을 고정한다 — 바뀌면 함께 고친다.
 */
const SERVER_CHUNK_S = { connection: 189, call: 146, answer: 121, reject: 89 }; // connection = 63 + P9 음성 확인 126(Task 99)
/** 상한에 걸린 뒤에도 덩어리마다 끝까지 기다리는 닫기(살아 있는 통화 끊기·연결 끊기, shield) — 서버 6e8fb04. */
const CLOSE_S = 28;
const MARGIN_S = 30;

/** 요청 시간 제한 = 이 요청이 도는 덩어리마다 (서버 상한 + 닫기) 의 합 + 여유. */
export function limitMs(part: VoicePart, body: VoiceDiagnoseIn, wait: number): number {
  const ids = body.steps ?? DEFAULT_IDS[part];
  const has = (...want: VoiceStepId[]) => want.some((id) => ids.includes(id));
  let chunks: number[];
  if (part === 'connection') chunks = [SERVER_CHUNK_S.connection];
  else if (part === 'call') chunks = [has('P6', 'P7', 'P8') || !has('P10') ? 1 : 0, has('P10') ? 1 : 0].filter(Boolean).map(() => SERVER_CHUNK_S.call);
  else chunks = [...(has('P12', 'P13') ? [SERVER_CHUNK_S.answer + wait] : []), ...(has('P14') ? [SERVER_CHUNK_S.reject + wait] : [])];
  return (chunks.reduce((sum, s) => sum + s + CLOSE_S, 0) + MARGIN_S) * 1000;
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
  if (!v.agent_number_effective_masked) return 'AI 전화 번호를 먼저 넣어 주세요.';
  return '첫 허용 번호가 전화를 걸 수 없는 번호입니다.';
}

/** SDK 나 공급자 묶음이 없을 때의 띠. */
function bandOf(v: VoiceSettings, d: VoiceDiagnosis | null): string | null {
  if (!v.sdk_installed) return SDK_BAND;
  if (d?.state === 'done' && d.steps.find((s) => s.id === 'P5')?.code === 'sdk_extra_missing') return EXTRA_BAND;
  return null;
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
export function useVoiceDiagnosis(id: number, wait: number, onRunning: (on: boolean) => void, afterRun: () => void) {
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
export function useRealCall(conn: NotifyConnection, voice: VoiceSettings | null, d: Diag, reload: () => void) {
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
        text={`${pending.target} 휴대전화로 AI 전화 번호 ${voice.agent_number_effective_masked ?? ''}에 두 번 걸어 주세요 — 첫 통화는 받고, 다음 통화는 받지 않고 거절합니다. 이쪽에서 거는 전화는 없고, 한 번에 ${lim.inbound_wait_default}초씩 기다립니다. 시작할까요?`}
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
function PartGroup({ title, part, ids, diag, children }: { title: string; part: VoicePart; ids: VoiceStepId[]; diag: VoiceDiagnosis | null; children?: ReactNode }) {
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

/**
 * 단추 줄([음성 진단][시험 전화] + 카드의 extra) · below(카드의 고치기 폼·지우기 확인) · 띠 · 「실제 통화 포함」 · 확인 창 · 도는 중 · 경고 ·
 * 세 묶음(걸음 줄, 받는 통화는 그 단추와 함께) · 시험 전화 기록.
 */
export function VoiceDiagnostics({ conn, voice, d, r, hold, extra, below, callsBlocked }: {
  conn: NotifyConnection;
  voice: VoiceSettings;
  d: Diag;
  r: Real;
  hold: boolean;
  extra?: ReactNode;
  below?: ReactNode;
  /** 실제 통화를 막는 카드의 까닭(구글이 키를 거절함 등). */
  callsBlocked?: string | null;
}) {
  const busy = hold || r.pending !== null;
  const why = diagWhy(voice);
  const band = bandOf(voice, d.diag);
  const callBlock = why ?? callsBlocked ?? (band ? '음성 SDK 가 설치되면 시험 전화와 받는 통화를 확인할 수 있습니다.' : callWhy(conn, voice));
  const callUnknown = d.unsure || (d.diag?.state === 'done' && d.diag.call_unknown);
  const callOff = busy || !!callBlock || !r.real;
  const serverRunning = !d.running && d.diag?.state === 'running' ? d.diag : null;
  return (
    <>
      <div className="st-actions">
        <Button disabled={busy || !!why} onClick={() => void d.run('connection', [{ phase: null, body: {} }])}>
          음성 진단
        </Button>
        <Button disabled={callOff || callUnknown} onClick={() => r.ask('call')}>
          시험 전화
        </Button>
        {extra}
      </div>
      {below}
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
        <label className="st-nt-switch st-vc-p10">
          <input type="checkbox" checked={r.p10} disabled={callOff} onChange={(e) => r.setP10(e.target.checked)} />
          <span>영어 첫마디(P10)도 — 한 통 더</span>
        </label>
        <span className="st-muted st-nt-real-why">
          {callBlock ?? '켜면 [시험 전화]·[받는 통화 확인]을 쓸 수 있습니다. 첫 허용 번호로만 걸고, 그 번호에서 걸려 온 전화만 받습니다.'}
        </span>
      </div>
      {r.pending && <CallConfirm pending={r.pending} voice={voice} hold={hold} onGo={() => void r.go()} onCancel={r.cancel} />}
      {d.running && <RunningLine running={d.running} agent={voice.agent_number_effective_masked ?? 'AI 전화 번호'} wait={voice.call_limits.inbound_wait_default} />}
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
        <PartGroup title="연결 확인" part={GROUPS[0].part} ids={GROUPS[0].ids} diag={d.diag} />
        <PartGroup title="시험 전화" part={GROUPS[1].part} ids={GROUPS[1].ids} diag={d.diag}>
          {d.diag?.state === 'done' && d.diag.part === 'call' && d.diag.called_real && <Badge tone="info">실제 전화 걸림</Badge>}
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
