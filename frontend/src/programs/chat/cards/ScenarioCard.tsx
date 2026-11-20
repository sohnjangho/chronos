import { useWindows } from '../../../os/windowStore';
import Button from '../../../shared/ui/Button';
import { dotDate } from '../labels';
import { asList, asNum, asObj, asText, Card, signedDays, type CardProps } from './Card';
import './cards2.css';

const delta = (n: number | null) => (n === null ? null : n === 0 ? '같음' : signedDays(n));

/**
 * 만약에 복사본(scenario.create 의 scenario_created 카드, Task 26): 이름·준공·지금 대비·Plan 대비·위반, [비교판에서 보기].
 * 차이는 서버 요약(summary)의 근무일 그대로다.
 */
export default function ScenarioCard({ data }: CardProps) {
  const s = asObj(data.summary);
  const sid = asNum(data.schedule_id);
  const id = asNum(data.scenario_id);
  const uncheckable = asNum(s.uncheckable) ?? 0;
  const rows: [string, string | null][] = [
    ['준공', dotDate(s.finish) || null],
    ['지금 대비', delta(asNum(s.finish_delta))],
    ['Plan 대비', delta(asNum(s.plan_delta))],
    ['조건 점검', Array.isArray(s.violations) ? `위반 ${asList(s.violations).length}${uncheckable ? ` · 자동 점검 안 됨 ${uncheckable}` : ''}` : null],
  ];
  return (
    <Card title="복사본">
      <p className="ch-card-title ch-wrap">{asText(data.name) || '이름 없는 복사본'}</p>
      <dl className="ch-kv">
        {rows
          .filter((r): r is [string, string] => r[1] !== null)
          .map(([k, v]) => (
            <div key={k}>
              <dt>{k}</dt>
              <dd className="ch-wrap">{v}</dd>
            </div>
          ))}
      </dl>
      {sid !== null && id !== null && (
        <div className="ch-actions">
          <Button onClick={() => useWindows.getState().open('compare', { id: String(sid), base: 'current', other: `s:${id}` })}>비교판에서 보기</Button>
        </div>
      )}
    </Card>
  );
}
