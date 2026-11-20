// 지연 상위 액티비티(서버가 고른 최대 5개) + [지연 기록 열기] [만회 계획 요청].
// 다른 프로그램은 import 하지 않고 창 저장소의 open 으로만 연다.
import { useWindows } from '../../os/windowStore';
import Badge from '../../shared/ui/Badge';
import Button from '../../shared/ui/Button';
import Table from '../../shared/ui/Table';
import { days } from './format';
import type { ProgressData } from './progressApi';

type Delay = ProgressData['top_delays'][number];

export const RECOVERY_ASK = '지연을 만회할 계획을 만들어 줘';

export default function DelayTop({ data, scheduleId }: { data: ProgressData; scheduleId: number }) {
  const open = (program: string, params: Record<string, string>) => useWindows.getState().open(program, params);
  return (
    <section className="pg-card pg-low-card" aria-label="지연 상위">
      <div className="pg-card-head">
        <h3 className="pg-card-title">지연 상위 액티비티</h3>
      </div>
      <div className="pg-card-body">
        <Table<Delay>
          label="지연 상위 액티비티"
          rows={data.top_delays}
          rowKey={(d) => d.id}
          empty="지연된 액티비티가 없습니다."
          columns={[
            { key: 'name', header: '액티비티', render: (d) => <span title={`${d.id} ${d.name}`}>{`${d.id} ${d.name}`}</span> },
            { key: 'delay', header: '지연', width: 48, align: 'right', render: (d) => <span className="is-danger">{days(d.delay)}</span> },
            { key: 'tf', header: 'TF', width: 36, align: 'right', render: (d) => String(d.tf) },
            {
              key: 'impact',
              header: '준공 영향',
              width: 64,
              align: 'right',
              render: (d) => (d.finish_impact > 0 ? <Badge tone="danger">{days(d.finish_impact)}</Badge> : <span className="pg-muted">없음</span>),
            },
          ]}
        />
      </div>
      <div className="pg-card-foot">
        <Button onClick={() => open('delays', { id: String(scheduleId) })}>지연 기록 열기</Button>
        <Button onClick={() => open('chat', { ask: RECOVERY_ASK })}>만회 계획 요청</Button>
      </div>
    </section>
  );
}
