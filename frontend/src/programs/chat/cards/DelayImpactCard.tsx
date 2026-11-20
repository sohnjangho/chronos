import { useState } from 'react';
import { useWindows } from '../../../os/windowStore';
import { api, ApiError } from '../../../shared/api';
import Badge from '../../../shared/ui/Badge';
import Button from '../../../shared/ui/Button';
import { dotDate } from '../labels';
import { asList, asNum, asObj, asText, Card, signedDays, won, type CardProps } from './Card';
import './cards2.css';

const RECOVERY_ASK = '지연 기록을 반영한 만회 계획을 만들어 줘';
const STATUS: Record<string, [string, 'warning' | 'info']> = { open: ['열림', 'warning'], reflected: ['반영됨', 'info'] };

/** [{id, name}] 또는 id 글 목록 → 이름들. */
const names = (v: unknown) =>
  asList(v)
    .map((x) => (typeof x === 'string' ? x : asText(asObj(x).name) || asText(asObj(x).id)))
    .filter(Boolean)
    .join(', ');

function criticalText(i: Record<string, unknown>): string {
  const added = names(i.critical_added);
  const removed = names(i.critical_removed);
  const parts = [added && `새로 들어옴: ${added}`, removed && `빠짐: ${removed}`].filter(Boolean);
  return parts.length ? parts.join(' · ') : '변화 없음';
}

function clashLines(v: unknown): string[] {
  return asList(v).map((x) => {
    const c = asObj(x);
    const over = asNum(c.over);
    const from = dotDate(c.first);
    return [asText(c.name) || asText(c.resource_id), from && `${from}부터 ${asNum(c.days) ?? 0}일`, over !== null && `한도보다 ${over} 많음`].filter(Boolean).join(' · ');
  });
}

function milestoneLines(v: unknown): string[] {
  return asList(v).map((x) => {
    const m = asObj(x);
    const delta = asNum(m.delta);
    return `${asText(m.name) || asText(m.activity_id)} ${dotDate(m.before)} → ${dotDate(m.after)}${delta === null ? '' : ` (${signedDays(delta)})`}`;
  });
}

/** 영향 숫자(서버 impact 그대로). 칸이 없거나 깨졌으면 그 줄을 뺀다. */
function ImpactLines({ i }: { i: Record<string, unknown> }) {
  const finishDelta = asNum(i.finish_delta);
  const absorbed = asNum(i.absorbed);
  const cost = asNum(i.cost);
  const clashes = clashLines(i.new_clashes);
  const milestones = milestoneLines(i.milestones);
  // 영향이 없거나 깨졌으면(칸이 목록이 아님) 「변화 없음」「없음」이라고 말하지 않고 줄을 뺀다.
  const hasCritical = Array.isArray(i.critical_added) || Array.isArray(i.critical_removed);
  const range = dotDate(i.finish_before) && dotDate(i.finish_after) ? `${dotDate(i.finish_before)} → ${dotDate(i.finish_after)}` : '';
  return (
    <dl className="ch-kv">
      {finishDelta !== null && (
        <div>
          <dt>준공</dt>
          <dd className="ch-wrap">
            <b>{finishDelta === 0 ? '변동 없음' : signedDays(finishDelta)}</b>
            {range && <span className="ch-meta">{` ${range}`}</span>}
          </dd>
        </div>
      )}
      {absorbed !== null && (
        <div>
          <dt>여유로 흡수</dt>
          <dd>{`${absorbed}일`}</dd>
        </div>
      )}
      {hasCritical && (
        <div>
          <dt>크리티컬 변화</dt>
          <dd className="ch-wrap">{criticalText(i)}</dd>
        </div>
      )}
      {Array.isArray(i.new_clashes) && (
        <div>
          <dt>새 자원 겹침</dt>
          <dd>
            {clashes.length ? (
              <ul className="ch-plain">
                {clashes.map((c, n) => (
                  <li key={n} className="ch-wrap">{c}</li>
                ))}
              </ul>
            ) : (
              '없음'
            )}
          </dd>
        </div>
      )}
      {milestones.length > 0 && (
        <div>
          <dt>마일스톤</dt>
          <dd>
            <ul className="ch-plain">
              {milestones.map((m, n) => (
                <li key={n} className="ch-wrap">{m}</li>
              ))}
            </ul>
          </dd>
        </div>
      )}
      {cost !== null && (
        <div>
          <dt>비용</dt>
          <dd>{won(cost)}</dd>
        </div>
      )}
    </dl>
  );
}

/**
 * 지연 영향(delay.record 의 delay_impact 카드, Task 33): 준공 영향·여유로 흡수·크리티컬 변화·새 자원 겹침·비용.
 * 숫자는 서버가 계산한 그대로다. [지연 기록 열기] · [비교판에서 보기](이 사건만 넣은 지연 반영안을 서버가 만든다 —
 * 이미 반영된 사건이면 서버의 거절 글을 카드에 보인다) · 열린 사건이면 [만회 계획 요청](대화에 그 요청을 보낸다, 보내는 동안 꺼짐).
 */
export default function DelayImpactCard({ data, ctx }: CardProps) {
  const [busy, setBusy] = useState(false);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState('');
  const sid = asNum(data.schedule_id);
  const eventId = asNum(data.event_id);
  const status = asText(data.status);
  const i = asObj(data.impact);
  const head = [[asText(data.activity_id), asText(data.name)].filter(Boolean).join(' '), asNum(data.days) !== null && `${asNum(data.days)}일 지연`].filter(Boolean).join(' · ');
  const badge = STATUS[status];
  const open = (program: string, params: Record<string, string>) => useWindows.getState().open(program, params);

  const compare = async () => {
    if (sid === null) return;
    setBusy(true);
    setError('');
    try {
      const r = await api<{ scenario_id: number }>(`/api/schedules/${sid}/delays/scenario`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(eventId === null ? {} : { event_ids: [eventId] }),
      });
      open('compare', { id: String(sid), base: 'current', other: `s:${r.scenario_id}` });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '지연 반영안을 만들지 못했습니다.');
    } finally {
      setBusy(false);
    }
  };

  const ask = async () => {
    setAsking(true);
    try {
      await ctx.sendText(RECOVERY_ASK);
    } finally {
      setAsking(false);
    }
  };

  return (
    <Card title="지연 영향" extra={badge && <Badge tone={badge[1]}>{badge[0]}</Badge>}>
      {head && <p className="ch-card-title ch-wrap">{head}</p>}
      {i.applied === false && asText(i.note) && <p className="ch-note ch-wrap">{asText(i.note)}</p>}
      <ImpactLines i={i} />
      {error && <p className="ch-error ch-wrap" role="alert">{error}</p>}
      {sid !== null && (
        <div className="ch-actions">
          <Button onClick={() => open('delays', { id: String(sid), ...(eventId !== null && { event: String(eventId) }) })}>지연 기록 열기</Button>
          <Button onClick={() => void compare()} disabled={busy}>
            비교판에서 보기
          </Button>
          {status === 'open' && (
            <Button variant="primary" onClick={() => void ask()} disabled={asking}>
              만회 계획 요청
            </Button>
          )}
        </div>
      )}
    </Card>
  );
}
