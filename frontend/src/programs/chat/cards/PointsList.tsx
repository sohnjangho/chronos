// 「지금 관리 포인트」 목록 카드(계획 5 Task 6): 당김 효과 카드의 [관리 포인트로 보기]·지난 버전 카드의 「지금 포인트 보기」가 쓴다.
// chain(다음 결정 줄)을 주면 그 줄의 포인트(point: true)를 먼저, ◆ 로 표시해 보이고 나머지 포인트를 뒤에. 값은 서버 그대로.
import { useState } from 'react';
import Badge from '../../../shared/ui/Badge';
import { Card } from './Card';
import { STALE_HINT } from './PointRisks';
import { errorText, getLatestPoints, monthDay, type PointsView } from './pointsApi';
import './pointsCards.css';

export interface ChainItem {
  activity_id: string;
  name: string;
  point: boolean;
}

type Row = { activity_id: string; name: string; critical?: boolean; tf?: number; es?: string; inChain: boolean };

function rows(view: PointsView, chain: ChainItem[]): Row[] {
  const byId = new Map(view.points.map((p) => [p.activity_id, p]));
  const first = chain.filter((c) => c.point).map((c) => ({ ...byId.get(c.activity_id), activity_id: c.activity_id, name: byId.get(c.activity_id)?.name ?? c.name, inChain: true }));
  const seen = new Set(first.map((r) => r.activity_id));
  return [...first, ...view.points.filter((p) => !seen.has(p.activity_id)).map((p) => ({ ...p, inChain: false }))];
}

export default function PointsList({ view, chain = [] }: { view: PointsView; chain?: ChainItem[] }) {
  const list = rows(view, chain);
  const inChain = list.filter((r) => r.inChain).length;
  const head = [
    inChain > 0 && `다음 결정 줄의 포인트 ${inChain}곳`,
    view.what_if ? '지연 가정(저장 전)' : `버전 ${view.version}`,
    `기준: 여유 ${view.basis.tf_days}일 이하, 앞으로 ${view.basis.window_weeks}주`,
  ].filter(Boolean).join(' · ');
  return (
    <Card title="지금 관리 포인트" extra={<Badge>{`${view.points.length}곳`}</Badge>}>
      <p className="ch-meta ch-wrap">{head}</p>
      {list.length === 0 ? (
        <p className="ch-meta">지금 관리 포인트가 없습니다.</p>
      ) : (
        <ul className="ch-plain" aria-label="지금 관리 포인트">
          {list.map((p) => (
            <li key={p.activity_id} className={`pc-point-h${p.inChain ? ' pc-in-chain' : ''}`}>
              {p.inChain && <span className="pc-mark" title="다음 결정 줄" aria-label="다음 결정 줄" />}
              <b className="ch-wrap">{p.name}</b>
              {p.critical === true && <Badge tone="danger">크리티컬</Badge>}
              {p.critical === false && <Badge tone="warning">크리티컬 직전</Badge>}
              {p.tf !== undefined && <span className="pc-float ch-meta">{`여유 ${p.tf}일${p.es ? ` · ${monthDay(p.es)}` : ''}`}</span>}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

const FROZEN_NOTE: Record<'old' | 'cap', string> = { old: '지난 버전 카드', cap: '오래 걸려 다시 읽기를 멈췄습니다' };

/** 멈춘 카드의 한 줄: 까닭 — [지금 포인트 보기](지금 포인트 목록을 이 카드 아래에). */
export function FrozenLine({ frozen, sid }: { frozen: 'old' | 'cap'; sid: number | null }) {
  const [view, setView] = useState<PointsView | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const load = async () => {
    if (sid === null || busy) return;
    setBusy(true);
    setError('');
    try {
      setView(await getLatestPoints(sid));
    } catch (e) {
      setError(errorText(e, '지금 포인트를 읽지 못했습니다.'));
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <p className="pc-fail ch-meta ch-wrap" title={frozen === 'old' ? STALE_HINT : undefined}>
        {`${FROZEN_NOTE[frozen]} —`}
        <button type="button" className="pc-link" disabled={busy || sid === null} onClick={() => void load()}>
          지금 포인트 보기
        </button>
        {error && <span className="ch-error" role="alert">{error}</span>}
      </p>
      {view && <PointsList view={view} />}
    </>
  );
}
