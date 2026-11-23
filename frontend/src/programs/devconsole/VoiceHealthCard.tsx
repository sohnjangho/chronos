// 시스템 진단의 AI 전화 묶음(Task 110): 음성 모델(공급자·실제로 쓰는 모델·마지막 음성 진단의 판정) · SDK 설치 · 통화 일꾼
// (돌고 있음 · 음성 서버 준비 · 받는 통화 듣기 · 지금 통화 수 · 마지막 통화 시각 · 마지막 오류 종류) · 저장된 마지막 음성 진단 줄.
// 콘솔은 진단을 다시 돌리지 않고 통화를 걸지 않는다. 키·끝 4자리·AI 전화 번호는 서버가 보내지 않는다.
import Badge, { type Tone } from '../../shared/ui/Badge';
import type { VoiceHealth } from './devApi';
import { Diagnosis, Row, when } from './NotifyHealthCard';

const STATUS: Record<string, [string, Tone]> = { ok: ['연결됨', 'success'], failed: ['실패', 'danger'], unknown: ['아직 진단 안 함', 'neutral'] };
const PROVIDER: Record<string, string> = { google: '구글(Gemini Live)', openai: 'OpenAI', dashboard: '대시보드' };
const BACKEND: Record<string, string> = { ok: '준비됨', not_ready: '준비 안 됨', sdk_missing: 'SDK 없음' };
const OFF: Record<string, string> = { disabled: '꺼 둔 설정', sandbox: '시험 격리' };

function Worker({ w }: { w: Record<string, unknown> | null }) {
  if (!w) return <p className="dc-muted">통화 일꾼 상태를 읽을 수 없습니다.</p>;
  const off = typeof w.off_reason === 'string' ? ` (${OFF[w.off_reason] ?? w.off_reason})` : '';
  return (
    <dl className="dc-health-kv" role="group" aria-label="통화 일꾼">
      <Row k="통화 일꾼" v={w.running ? '돌고 있음' : `멈춤${off}`} />
      <Row k="음성 서버" v={BACKEND[String(w.backend)] ?? String(w.backend ?? '—')} />
      <Row k="받는 통화 듣기" v={w.listening ? '붙어 있음' : '붙어 있지 않음'} />
      <Row k="지금 통화" v={`${typeof w.live === 'number' ? w.live : 0}통`} />
      <Row k="마지막 통화" v={when(w.last_call_at)} />
      <Row k="마지막 오류" v={typeof w.last_error_kind === 'string' ? w.last_error_kind : '없음'} />
    </dl>
  );
}

export default function VoiceHealthCard({ v }: { v: VoiceHealth }) {
  const [label, tone] = STATUS[v.status] ?? [v.status, 'neutral'];
  return (
    <article className="dc-health-card dc-o-wide" aria-label="AI 전화">
      <div className="dc-health-head">
        <h3>AI 전화</h3>
        <Badge tone={tone}>{label}</Badge>
      </div>
      <p className="dc-muted">{`마지막 음성 진단 판정 ${when(v.checked_at)}`}</p>
      <div className="dc-o-cols">
        <dl className="dc-health-kv">
          <Row k="공급자" v={PROVIDER[v.provider] ?? v.provider} />
          <Row k="음성 모델" v={v.model ?? 'SDK 기본'} />
          <Row k="음성 SDK" v={v.sdk_installed ? '설치됨' : '설치되지 않음'} />
        </dl>
        <Worker w={v.worker} />
      </div>
      {v.last_diagnosis ? (
        <Diagnosis diag={v.last_diagnosis} title="마지막 음성 진단" />
      ) : (
        <p className="dc-muted">저장된 음성 진단이 없습니다(설정 → 알림 연결 → AI 전화 → 음성 진단).</p>
      )}
    </article>
  );
}
