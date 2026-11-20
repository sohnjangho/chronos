import type { ProgramProps } from '../../os/registry';
import ScheduleFrame from '../../shared/schedule/ScheduleFrame';
import DataDateField, { WeightMissing } from './DataDateField';
import TableTab from './TableTab';
import './table.css';

/** 「스케줄」: 일정 표(도구줄 · 표 · 관계 패널). 같은 일정을 보는 다른 도구 창과 저장소·고른 줄을 함께 쓴다. */
export default function ScheduleTable({ windowId, params }: ProgramProps) {
  return (
    <ScheduleFrame
      windowId={windowId}
      params={params}
      programId="schedule-table"
      name="스케줄"
      dataDate={<DataDateField />}
      headExtra={<WeightMissing />}
    >
      <TableTab />
    </ScheduleFrame>
  );
}
