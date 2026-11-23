// 시스템 진단의 11-23 칸: 정보 API 연결 · 근거 다시 쓰기 · 공휴일 표 · 그림 읽기 배정. 예전 서버는 칸이 없다 — 그리지 않는다.
// 정보 API 는 이름·종류·마지막 시험만(주소·키 없음).
import type { ReactNode } from 'react';
import Badge from '../../shared/ui/Badge';
import type { HealthOut, InfoApiHealth } from './devApi';

const KIND: Record<string, string> = { generic: '범용', kma: '기상청 전용' };
const TEST: Record<string, { label: string; tone: 'success' | 'danger' | 'neutral' }> = {
  ok: { label: '정상', tone: 'success' },
  failed: { label: '실패', tone: 'danger' },
  unknown: { label: '모름', tone: 'neutral' },
};

function when(iso: string | null): string {
  if (!iso) return '시험 안 함';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString('ko-KR', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function Card({ title, badge, message, children }: { title: string; badge: ReactNode; message: string; children: ReactNode }) {
  return (
    <article className="dc-health-card" aria-label={title}>
      <div className="dc-health-head">
        <h3>{title}</h3>
        {badge}
      </div>
      <p className="dc-muted">{message}</p>
      {children}
    </article>
  );
}

function InfoCard({ info, badge }: { info: InfoApiHealth; badge: ReactNode }) {
  return (
    <Card title="정보 API 연결" badge={badge} message={info.message}>
      {info.connections.length > 0 && (
        <ul className="dc-health-list">
          {info.connections.map((c) => (
            <li key={c.id}>
              <span className="dc-ellipsis" title={c.name}>{c.name}</span>
              <span className="dc-tag">{KIND[c.kind] ?? c.kind}</span>
              <Badge tone={TEST[c.status]?.tone ?? 'neutral'}>{TEST[c.status]?.label ?? c.status}</Badge>
              <span className="dc-muted">{when(c.checked_at)}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export default function HealthTodayCards({ data, badge }: { data: HealthOut; badge(status: string): ReactNode }) {
  const { info_api: info, evidence_reuse: reuse, holidays, vision } = data;
  return (
    <>
      {info && <InfoCard info={info} badge={badge(info.status)} />}
      {reuse && (
        <Card title="근거 다시 쓰기" badge={<Badge tone="info">{`${reuse.days}일`}</Badge>} message={`붙은 곳이 있고 ${reuse.days}일 안이며 「다시 쓰지 않기」가 아닌 근거만 다시 씁니다.`}>
          <dl className="dc-health-kv">
            <div><dt>지금 다시 쓸 수 있는 근거</dt><dd>{`${reuse.reusable.toLocaleString()}건`}</dd></div>
            <div><dt>최근 7일 다시 씀 / Liner 검색</dt><dd>{`${reuse.reused_7d.toLocaleString()}회 / ${reuse.searches_7d.toLocaleString()}회`}</dd></div>
          </dl>
        </Card>
      )}
      {holidays && (
        <Card title="공휴일 표" badge={badge(holidays.status)} message={holidays.message}>
          <dl className="dc-health-kv">
            <div><dt>있는 해</dt><dd>{holidays.years.join(' · ')}</dd></div>
            {holidays.years.map((y) => (
              <div key={y}><dt>{`${y}년`}</dt><dd>{`${holidays.counts[String(y)] ?? 0}일`}</dd></div>
            ))}
          </dl>
        </Card>
      )}
      {vision && (
        <Card title="그림 읽기 배정" badge={badge(vision.status)} message={vision.message}>
          <dl className="dc-health-kv">
            <div><dt>모델</dt><dd>{vision.model}</dd></div>
            <div><dt>연결</dt><dd>{vision.connection_name ?? '없음'}</dd></div>
            <div><dt>배정</dt><dd>{vision.stored ? '설정에 저장' : '기본값'}</dd></div>
          </dl>
        </Card>
      )}
    </>
  );
}
