import { useWindows } from '../../../os/windowStore';
import Button from '../../../shared/ui/Button';
import { asList, asNum, asObj, asText, Card, signedDays, type CardProps } from './Card';
import './cards2.css';

const percent = (p: number) => `${Math.round(p * 1000) / 10}%`;

/**
 * 실적 입력(schedule.record_actual 의 actual_recorded 카드, Task 30): 자동 적용된 진도·버전, 코드가 채운 가정 줄,
 * Plan 보다 늦어졌으면 위험색 줄과 [지연 기록 열기]. 일수는 서버 delay 값 그대로다.
 * [지연 기록 열기] 는 카드에 before_version 이 있으면 before 로 넘긴다(지연 기록이 source "actual" 로 적게).
 */
export default function ActualCard({ data }: CardProps) {
  const aid = asText(data.activity_id);
  const name = asText(data.name);
  const progress = asNum(data.progress);
  const version = asNum(data.version);
  const assumed = asList(data.assumed).map(asText).filter(Boolean);
  const delay = asObj(data.delay);
  const late = asNum(delay.late_days) ?? 0;
  const finishDelta = asNum(delay.finish_delta);
  const before = asNum(data.before_version);
  const sid = asNum(data.schedule_id);
  const what = [aid, name].filter(Boolean).join(' ') || '실적';
  const done = progress === null ? '실적을 넣었습니다' : `진도 ${percent(progress)}로 넣었습니다`;
  const how = ['자동 적용', version !== null && `버전 ${version}`].filter(Boolean).join(' · ');
  const finish = finishDelta === null ? '' : ` · 준공 ${finishDelta === 0 ? '변동 없음' : signedDays(finishDelta)}`;
  const openDelays = () =>
    useWindows.getState().open('delays', {
      id: String(sid),
      activity: asText(delay.activity_id) || aid,
      days: String(late),
      ...(before !== null && { before: String(before) }),
    });
  return (
    <Card title="실적">
      <p className="ch-wrap">{`${what} ${done}(${how})`}</p>
      {assumed.length > 0 && (
        <ul className="ch-plain">
          {assumed.map((a, i) => (
            <li key={i} className="ch-note ch-wrap">{`가정: ${a}`}</li>
          ))}
        </ul>
      )}
      {late > 0 && (
        <div className="ch-late">
          <span className="ch-wrap">{`Plan보다 ${late}일 늦어졌습니다${finish}`}</span>
          {sid !== null && <Button onClick={openDelays}>지연 기록 열기</Button>}
        </div>
      )}
    </Card>
  );
}
