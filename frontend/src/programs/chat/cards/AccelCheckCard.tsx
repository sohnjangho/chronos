// 「당겨도 소용 있나」 당김 효과 카드(계획 5 Task 6 — points.accel_check 의 card{kind:"accel_check"}, 서버
// backend/app/tools/points/accel_check.py AccelCheckOut). PM 승인 시안 shots/mock-card/accel.html 꼴.
// 숫자·날짜·다음 결정 줄은 서버 계산값 그대로. 「준공 반영 n일 중 m일」(PM 11-24 표기). 반영이 당긴 날보다 많으면(자원이 섞임)
// 숫자를 그대로 보이고 경고 색을 쓰지 않는다. [관리 포인트로 보기] = API 로 관리 포인트를 읽어 이 카드 아래(대화)에 포인트 카드를
// 보인다(바뀜 카드가 없으면 지금 포인트 목록). [만회안 보기] = 대화에 만회 계획 요청.
import { useState } from 'react';
import Badge from '../../../shared/ui/Badge';
import Button from '../../../shared/ui/Button';
import { dotDate } from '../labels';
import { asList, asNum, asObj, asText, Card, signedDays, type CardProps } from './Card';
import PointsChangedCard from './PointsChangedCard';
import { errorText, getLatestPoints, type PointsView } from './pointsApi';
import './pointsCards.css';

const RECOVERY_ASK = '만회 계획을 만들어 줘';

function PointsList({ view }: { view: PointsView }) {
  return (
    <Card title="지금 관리 포인트" extra={<Badge>{`${view.points.length}곳`}</Badge>}>
      <p className="ch-meta ch-wrap">{`관리 포인트는 바뀌지 않았습니다 · 기준: 여유 ${view.basis.tf_days}일 이하, 앞으로 ${view.basis.window_weeks}주`}</p>
      {view.points.length === 0 ? (
        <p className="ch-meta">지금 관리 포인트가 없습니다.</p>
      ) : (
        <ul className="ch-plain">
          {view.points.map((p) => (
            <li key={p.activity_id} className="pc-point-h">
              <b className="ch-wrap">{p.name}</b>
              {p.critical ? <Badge tone="danger">크리티컬</Badge> : <Badge tone="warning">크리티컬 직전</Badge>}
              <span className="pc-float ch-meta">{`여유 ${p.tf}일 · ${dotDate(p.es)}`}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export default function AccelCheckCard({ data, ctx }: CardProps) {
  const [shown, setShown] = useState<PointsView | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const sid = asNum(data.schedule_id);
  const name = asText(data.name) || asText(data.activity_id);
  const pulled = asNum(data.pulled_days) ?? 0;
  const reached = asNum(data.reached_days) ?? 0;
  const over = reached > pulled; // 자원이 섞여 당긴 날보다 많이 반영 — 그대로 보이고 경고 색 없음
  const warn = data.warn === true && !over;
  const left = pulled - reached;
  const chain = asList(data.next_chain).map(asObj);
  const anyPoint = chain.some((c) => c.point === true);
  const range = dotDate(data.finish_before) && dotDate(data.finish_after) ? ` ${dotDate(data.finish_before)} → ${dotDate(data.finish_after)}` : '';
  const odBefore = asNum(data.od_before);
  const odAfter = asNum(data.od_after);

  const showPoints = async () => {
    if (sid === null || busy) return;
    setBusy(true);
    setError('');
    try {
      setShown(await getLatestPoints(sid));
    } catch (e) {
      setError(errorText(e, '관리 포인트를 읽지 못했습니다.'));
      setBusy(false);
    }
  };

  return (
    <>
      <Card title="당김 효과" extra={<Badge tone={warn ? 'warning' : 'info'}>{`준공 반영 ${pulled}일 중 ${reached}일`}</Badge>}>
        <p className="ch-card-title ch-wrap">{`「${name}」 ${pulled}일 당기면`}</p>
        {warn && asText(data.warn_line) && (
          <p className="pc-warnline">
            <span className="ch-wrap">{asText(data.warn_line)}</span>
          </p>
        )}
        <dl className="ch-kv">
          <div>
            <dt>준공</dt>
            <dd className="ch-wrap">
              <b>{reached === 0 ? '변동 없음' : signedDays(-reached)}</b>
              {range && <span className="ch-meta">{range}</span>}
            </dd>
          </div>
          <div>
            <dt>당긴 작업</dt>
            <dd className="ch-wrap">
              {name}
              {odBefore !== null && odAfter !== null && <span className="ch-meta">{` 기간 ${odBefore}일 → ${odAfter}일`}</span>}
            </dd>
          </div>
          {left > 0 && (
            <div>
              <dt>{`남은 ${left}일`}</dt>
              <dd className="ch-wrap">다음 줄이 막아서 준공까지 가지 못합니다</dd>
            </div>
          )}
          {chain.length > 0 && (
            <div>
              <dt>다음 결정 줄</dt>
              <dd>
                <ul className="pc-chain" aria-label="다음 결정 줄">
                  {chain.map((c, i) => (
                    <li key={`${asText(c.activity_id)}-${i}`} className={c.point === true ? 'is-point' : ''}>
                      {c.point === true && <span className="pc-mark" title="관리 포인트" aria-label="관리 포인트" />}
                      <span className="ch-wrap">{asText(c.name) || asText(c.activity_id)}</span>
                    </li>
                  ))}
                </ul>
                {anyPoint && (
                  <p className="ch-meta pc-legend">
                    <span className="pc-mark" aria-hidden="true" /> 관리 포인트
                  </p>
                )}
              </dd>
            </div>
          )}
        </dl>
        {data.same_chain === true ? (
          <p className="ch-note ch-wrap">당긴 뒤에도 같은 줄이 준공을 정합니다.</p>
        ) : (
          warn && <p className="ch-note ch-wrap">더 당겨도 이 줄이 늦으면 준공은 그대로입니다. 이 줄의 포인트부터 보세요.</p>
        )}
        {error && <p className="ch-error ch-wrap" role="alert">{error}</p>}
        <div className="ch-actions">
          {sid !== null && (
            <Button variant="primary" disabled={busy} onClick={() => void showPoints()}>
              관리 포인트로 보기
            </Button>
          )}
          <Button onClick={() => void ctx.sendText(RECOVERY_ASK)}>만회안 보기</Button>
        </div>
      </Card>
      {shown && (shown.card ? <PointsChangedCard data={shown.card} ctx={ctx} /> : <PointsList view={shown} />)}
    </>
  );
}
