// 시스템 진단의 알림 연결 묶음(Task 108): 연결 상태 · 시험 모드 · 허용 번호 수 · 발신번호(가린 꼴) · 받는 범위 · 에이전트 권한 ·
// 확인 필요 수 · 조회 일꾼의 마지막 시각 · 저장된 마지막 연결 진단(콘솔은 진단을 다시 돌리지 않는다). 키·Account ID 는 없다.
// 결과를 모르는 걸음은 「확인 필요」이지 실패가 아니다. 코드는 접힌 기계 출력으로.
import Badge, { type Tone } from '../../shared/ui/Badge';
import type { NotifyDiagnosis, NotifyHealth, NotifyStep } from './devApi';
import RawBlock from './RawBlock';

const STATUS: Record<string, [string, Tone]> = { ok: ['정상', 'success'], failed: ['오류', 'danger'], unknown: ['모름', 'neutral'] };
const OUTCOME: Record<NotifyStep['outcome'], [string, Tone]> = {
  ok: ['정상', 'success'],
  failed: ['실패', 'danger'],
  check: ['확인 필요', 'warning'],
  skipped: ['건너뜀', 'neutral'],
};
const INBOUND: Record<string, string> = { off: '받지 않음', known: '주소록에 있는 번호만', all: '모두' };
const AGENT: Record<string, string> = { approve: '승인', delegate: '위임' };
const WORKER_TIMES: [string, string][] = [
  ['last_tick_at', '마지막 바퀴'],
  ['last_due_at', '예약 발송'],
  ['last_status_poll_at', '상태 조회'],
  ['last_inbound_poll_at', '받은 문자 조회'],
];
const NOT_YET = '아직 없음';

export function when(v: unknown): string {
  if (typeof v !== 'string') return NOT_YET;
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString('ko-KR', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export const Row = ({ k, v }: { k: string; v: string }) => (
  <div>
    <dt>{k}</dt>
    <dd>{v}</dd>
  </div>
);

function Worker({ w }: { w: Record<string, unknown> | null }) {
  if (!w) return <p className="dc-muted">조회 일꾼 상태를 읽을 수 없습니다.</p>;
  return (
    <dl className="dc-health-kv" role="group" aria-label="조회 일꾼">
      <Row k="조회 일꾼" v={w.running ? '돌고 있음' : '멈춤'} />
      {WORKER_TIMES.map(([key, label]) => (
        <Row key={key} k={label} v={when(w[key])} />
      ))}
    </dl>
  );
}

/** 저장된 마지막 진단의 걸음 줄(연결 진단 · 음성 진단이 같이 쓴다 — Task 110). */
export function Diagnosis({ diag, title = '마지막 연결 진단' }: { diag: NotifyDiagnosis; title?: string }) {
  return (
    <section className="dc-o-diag">
      <h4>{`${title} · ${when(diag.ran_at)}${diag.state === 'sending' ? ' · 도는 중이거나 끝나지 않음(확인 필요)' : ''}`}</h4>
      <ul className="dc-health-list" aria-label={title}>
        {diag.steps.map((s) => {
          const [label, tone] = OUTCOME[s.outcome];
          return (
            <li key={s.id}>
              <span className="dc-ellipsis" title={s.label}>
                <b>{s.id}</b> {s.label}
              </span>
              <Badge tone={tone}>{label}</Badge>
              <span className="dc-muted dc-o-detail">{s.detail}</span>
            </li>
          );
        })}
      </ul>
      <RawBlock label="걸음 코드" value={Object.fromEntries(diag.steps.map((s) => [s.id, { code: s.code, maybe_sent: s.maybe_sent, pending: s.pending }]))} />
    </section>
  );
}

export default function NotifyHealthCard({ n }: { n: NotifyHealth }) {
  if (!n.connected) {
    return (
      <article className="dc-health-card" aria-label="알림 연결">
        <div className="dc-health-head">
          <h3>알림 연결</h3>
          <Badge tone="neutral">꺼짐</Badge>
        </div>
        <p className="dc-muted">알림 연결이 없습니다(설정 → 알림 연결). 문자·전화는 나가지 않습니다.</p>
      </article>
    );
  }
  const [label, tone] = STATUS[n.status ?? 'unknown'] ?? [n.status ?? '모름', 'neutral'];
  const agent = n.agent ?? {};
  return (
    <article className="dc-health-card dc-o-wide" aria-label="알림 연결">
      <div className="dc-health-head">
        <h3>알림 연결</h3>
        <Badge tone={tone}>{label}</Badge>
      </div>
      <p className="dc-muted">
        {`마지막 연결 시험 ${when(n.checked_at)}`}
        {n.needs_check > 0 && <span className="dc-tag is-warn" title="보냈는지 알 수 없는 문자입니다. 자동으로 다시 보내지 않습니다.">{`확인 필요 ${n.needs_check}건`}</span>}
      </p>
      <div className="dc-o-cols">
        <dl className="dc-health-kv">
          <Row k="시험 모드" v={n.test_mode ? '켬' : '끔'} />
          <Row k="허용 번호" v={`${n.allow_count}개`} />
          <Row k="발신번호" v={n.sender_masked ?? '없음'} />
          <Row k="받는 범위" v={INBOUND[n.inbound_mode ?? ''] ?? n.inbound_mode ?? '—'} />
          <Row k="에이전트 권한" v={`문자 ${AGENT[agent.sms] ?? '—'} · 카카오톡 ${AGENT[agent.kakao] ?? '—'} · 전화 ${AGENT[agent.call] ?? '—'}`} />
          <Row k="카카오톡" v={NOT_YET} />
          <Row k="AI 전화" v={n.voice ? '설정됨 — 아래 「AI 전화」 칸' : NOT_YET} />
        </dl>
        <Worker w={n.worker} />
      </div>
      {n.last_diagnosis ? <Diagnosis diag={n.last_diagnosis} /> : <p className="dc-muted">저장된 연결 진단이 없습니다(설정 → 알림 연결 → 연결 진단).</p>}
    </article>
  );
}
