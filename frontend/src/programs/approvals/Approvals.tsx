// 승인함(시안 「승인함 (2판)」): 왼쪽 묶음·목록, 오른쪽 고른 건과 결정 상자. params.id 면 그 건을 연다.
import type { ProgramProps } from '../../os/registry';
import ApprovalDetail from './ApprovalDetail';
import ApprovalList from './ApprovalList';
import DecisionBox from './DecisionBox';
import { useApprovalData } from './useApprovalData';
import './approvals.css';

export default function Approvals({ params }: ProgramProps) {
  const d = useApprovalData(params?.id);
  const scheduleName = d.detail?.schedule_id == null ? null : (d.schedules?.get(d.detail.schedule_id)?.name ?? null);
  return (
    <div className="apv-root">
      <ApprovalList
        tab={d.tab}
        onTab={d.changeTab}
        counts={{ pending: d.lists.pending?.length ?? null, auto: d.lists.auto?.length ?? null }}
        mode={d.mode}
        items={d.lists[d.tab]}
        selected={d.selected}
        onSelect={d.select}
        revertOf={d.revertOf}
        onRevert={(it) => void d.revert(it)}
      />
      <main className="apv-main">
        {d.loadError && (
          <p className="apv-notice is-error" role="alert">
            {d.loadError}
          </p>
        )}
        {d.notice && (
          <p className={`apv-notice is-${d.notice.tone}`} role={d.notice.tone === 'error' ? 'alert' : 'status'}>
            {d.notice.text}
          </p>
        )}
        {d.detail ? (
          <>
            <ApprovalDetail item={d.detail} scheduleName={scheduleName} />
            {d.detail.status === 'pending' && <DecisionBox key={d.detail.id} item={d.detail} onDecide={d.decide} />}
          </>
        ) : (
          <p className="apv-empty">왼쪽에서 승인 건을 고르세요.</p>
        )}
      </main>
    </div>
  );
}
