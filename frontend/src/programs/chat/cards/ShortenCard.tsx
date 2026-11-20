import { useWindows } from '../../../os/windowStore';
import Badge from '../../../shared/ui/Badge';
import Button from '../../../shared/ui/Button';
import { dotDate } from '../labels';
import { asList, asNum, asObj, asText, Card, signedDays, type CardProps } from './Card';
import './cards2.css';

const baseLabel = (base: string) => (base.startsWith('s:') ? '지연 반영안 기준' : '지금 일정 기준');

function Option({ o, scheduleId, base }: { o: Record<string, unknown>; scheduleId: number | null; base: string }) {
  const key = asText(o.key);
  const name = asText(o.name);
  const id = asNum(o.scenario_id);
  const gain = asNum(o.gain);
  const violations = asNum(o.violations) ?? 0;
  const uncheckable = asNum(o.uncheckable) ?? 0;
  const moves = asList(o.moves).map(asText).filter(Boolean);
  const picked = o.recommended === true;
  return (
    <div role="group" aria-label={`안 ${key} ${name}`.trim()} className={`ch-option${picked ? ' is-pick' : ''}`}>
      <div className="ch-option-h">
        {picked && <Badge tone="info">추천</Badge>}
        <b className="ch-wrap">{[key, name].filter(Boolean).join(' · ')}</b>
      </div>
      <div className="ch-facts">
        {dotDate(o.finish) && <span>{`준공 ${dotDate(o.finish)}`}</span>}
        {gain !== null && (
          <span>
            이득 <b>{signedDays(-gain)}</b>
          </span>
        )}
        {typeof o.reached === 'boolean' && <span className={o.reached ? 'is-good' : 'is-bad'}>{o.reached ? '목표 도달' : '목표에 못 미침'}</span>}
        <span className={violations ? 'is-bad' : undefined}>{`위반 ${violations}`}</span>
        {uncheckable > 0 && <span>{`자동 점검 안 됨 ${uncheckable}`}</span>}
      </div>
      {moves.length > 0 && (
        <details>
          <summary>{`바꾸는 것 ${moves.length}개`}</summary>
          <ul>
            {moves.map((m, i) => (
              <li key={i} className="ch-wrap">{m}</li>
            ))}
          </ul>
        </details>
      )}
      {asText(o.note) && <p className="ch-wrap">{asText(o.note)}</p>}
      {scheduleId !== null && id !== null && (
        <div className="ch-actions">
          <Button onClick={() => useWindows.getState().open('compare', { id: String(scheduleId), base, other: `s:${id}` })}>비교판에서 보기</Button>
        </div>
      )}
    </div>
  );
}

/**
 * 만회·단축안(shorten.make 의 shorten_options 카드, Task 34): 안마다 추천 배지·이름·준공·이득·목표 도달·위반,
 * 접힌 「바꾸는 것」, 설명 글, [비교판에서 보기](기준 base 와 그 복사본). 날짜·이득·위반은 서버 값 그대로다.
 */
export default function ShortenCard({ data }: CardProps) {
  const sid = asNum(data.schedule_id);
  const base = asText(data.base) || 'current';
  const target = asNum(data.target);
  const options = asList(data.options).map(asObj);
  const head = [dotDate(data.base_finish) && `기준 준공 ${dotDate(data.base_finish)}`, target !== null && `목표 ${target}일 당기기`].filter(Boolean).join(' · ');
  return (
    <Card title="만회안" extra={baseLabel(base)}>
      {head && <p className="ch-wrap">{head}</p>}
      {options.length === 0 ? (
        <p className="ch-note">만든 안이 없습니다.</p>
      ) : (
        <div className="ch-shorten-list">
          {options.map((o, i) => (
            <Option key={asText(o.key) || i} o={o} scheduleId={sid} base={base} />
          ))}
        </div>
      )}
    </Card>
  );
}
