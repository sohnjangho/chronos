// 시스템 진단의 카카오톡 묶음(Task 111): 연결된 채널 이름 · 문안 상태별 수(승인·검수 중·반려·휴면) · 마지막으로 읽은 때 · 쓸 수 있는가.
// 서버가 저장해 둔 값을 보일 뿐 — 콘솔은 제공사를 부르지 않고 목록을 다시 읽지도 않는다. 채널이 없으면 「쓰지 않음」.
import Badge from '../../shared/ui/Badge';
import type { KakaoHealth } from './devApi';
import { Row, when } from './NotifyHealthCard';

const COUNTS: [keyof KakaoHealth['templates'], string][] = [
  ['approved', '승인'],
  ['reviewing', '검수 중'],
  ['rejected', '반려'],
  ['dormant', '휴면'],
];

export default function KakaoHealthCard({ k }: { k: KakaoHealth }) {
  if (k.channel === null) {
    return (
      <article className="dc-health-card" aria-label="카카오톡">
        <div className="dc-health-head">
          <h3>카카오톡</h3>
          <Badge tone="neutral">쓰지 않음</Badge>
        </div>
        <p className="dc-muted">카카오톡: 연결된 채널 없음 — 쓰지 않음. 알림톡 요청은 문자로 나갑니다.</p>
      </article>
    );
  }
  return (
    <article className="dc-health-card" aria-label="카카오톡">
      <div className="dc-health-head">
        <h3>카카오톡</h3>
        <Badge tone={k.ready ? 'success' : 'neutral'}>{k.ready ? '쓸 수 있음' : '준비 안 됨'}</Badge>
      </div>
      <p className="dc-muted">{`저장된 값입니다 — 마지막으로 읽은 때 ${when(k.synced_at)}${k.available ? '' : ' · 목록 읽는 길을 아직 확인하지 못했습니다'}`}</p>
      <dl className="dc-health-kv">
        <Row k="채널" v={k.channel} />
        {COUNTS.map(([key, label]) => (
          <Row key={key} k={`문안 ${label}`} v={`${k.templates[key]}개`} />
        ))}
      </dl>
    </article>
  );
}
