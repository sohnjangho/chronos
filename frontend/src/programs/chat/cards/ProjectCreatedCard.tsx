import { useCurrentSchedule } from '../../../os/currentSchedule';
import { useWindows } from '../../../os/windowStore';
import { domainLabel } from '../../../shared/domainLabels';
import Button from '../../../shared/ui/Button';
import { dotDate } from '../labels';
import { asNum, asText, Card, type CardProps } from './Card';

/** 새 프로젝트 생성 카드(schedule.create_project 의 project_created 사건). */
export default function ProjectCreatedCard({ data }: CardProps) {
  const sid = asNum(data.schedule_id);
  const name = asText(data.name) || (sid !== null ? `일정 ${sid}` : '새 프로젝트');
  const domain = asText(data.domain);
  const level = asText(data.level);
  const finish = dotDate(data.finish);

  const openProgram = (program: 'gantt' | 'schedule-table') => {
    if (sid === null) return;
    useCurrentSchedule.getState().setCurrent({ id: sid, name });
    useWindows.getState().open(program, { id: String(sid) });
  };

  return (
    <Card title="새 프로젝트 생성">
      <p className="ch-card-title ch-wrap">{name}</p>
      <ul className="ch-plain ch-lines">
        {(domain || level) && (
          <li>
            {[domain && domainLabel(domain), level].filter(Boolean).join(' · ')}
          </li>
        )}
        {finish && (
          <li>
            완료 <b>{finish}</b>
          </li>
        )}
      </ul>
      {sid !== null && (
        <div className="ch-actions">
          <Button variant="primary" onClick={() => openProgram('gantt')}>
            간트차트 열기
          </Button>
          <Button onClick={() => openProgram('schedule-table')}>
            스케줄 열기
          </Button>
        </div>
      )}
    </Card>
  );
}
