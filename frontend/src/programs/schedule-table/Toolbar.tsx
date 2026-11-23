import { useSession } from '../../os/session';
import Badge from '../../shared/ui/Badge';
import Button from '../../shared/ui/Button';
import { percent } from '../../shared/schedule/format';
import History from '../../shared/schedule/History';
import { useScheduleStore } from '../../shared/schedule/scope';
import type { ColKey } from '../../shared/schedule/columns';
import { ColumnPanel } from '../../shared/schedule/FilterPanel';
import Popover from '../../shared/schedule/Popover';
import type { Activity, WeightMode } from '../../shared/schedule/scheduleApi';

interface ToolbarProps {
  visible: ColKey[];
  onVisible(keys: ColKey[]): void;
  canDelete: boolean;
  canAdd: boolean;
  /** 전체 가중 진척(0~1), 가중치가 없으면 null. */
  progress: number | null;
  weightMode: WeightMode;
  onWeightMode(mode: WeightMode): void;
  onAdd(): void;
  onDelete(): void;
  onExport(): void;
}

/** 위 도구줄: 엑셀/PPT 스타일 2줄 리본 구역(편집 · 보기·설정 · 이력 · 진척·내보내기). */
export default function Toolbar(p: ToolbarProps) {
  // 현장 관리자는 일정을 고칠 수 없다(서버도 403) — 편집 묶음을 그리지 않는다(F4).
  const canEdit = useSession((s) => s.session?.user.role !== 'field');
  return (
    <div role="toolbar" aria-label="스케줄표 도구" className="sch-toolbar">
      {canEdit && (
        <div className="sch-rib-group">
          <div className="sch-rib-stack is-stretch">
            <Button variant="primary" disabled={!p.canAdd} onClick={p.onAdd}>+ 행 추가</Button>
            <Button variant="danger" data-act="delete" disabled={!p.canDelete} onClick={p.onDelete}>삭제</Button>
          </div>
          <span className="sch-rib-label">편집</span>
        </div>
      )}
      <div className="sch-rib-group">
        <div className="sch-rib-stack is-stretch">
          <Popover button="열" label="열">
            {() => <ColumnPanel visible={p.visible} onVisible={p.onVisible} />}
          </Popover>
          <label className="sch-weight">
            가중치
            <select aria-label="가중치" value={p.weightMode} onChange={(e) => p.onWeightMode(e.target.value as WeightMode)}>
              <option value="duration">기간 비례</option>
              <option value="manual">직접 입력</option>
            </select>
          </label>
        </div>
        <span className="sch-rib-label">보기·설정</span>
      </div>
      <div className="sch-rib-group">
        <div className="sch-rib-stack is-stretch">
          <History />
        </div>
        <span className="sch-rib-label">이력</span>
      </div>
      <div className="sch-rib-group">
        <div className="sch-rib-stack is-stretch">
          {p.progress !== null && <Badge tone="info">{`전체 가중 진척도 ${percent(p.progress)}%`}</Badge>}
          <Button onClick={p.onExport}>CSV 내보내기</Button>
        </div>
        <span className="sch-rib-label">진척·내보내기</span>
      </div>
    </div>
  );
}

/** 삭제 확인(창 안). 지울 줄을 이름으로 보이고, 관계도 함께 지워지며 되돌리기로 살릴 수 있음을 알린다. */
export function DeleteConfirm({ activity, onDone }: { activity: Activity; onDone(): void }) {
  const store = useScheduleStore();
  const back = () => {
    onDone();
    document.querySelector<HTMLButtonElement>('.sch-toolbar [data-act="delete"]')?.focus();
  };
  return (
    <div role="alertdialog" aria-label="삭제 확인" className="sch-confirm" onKeyDown={(e) => e.key === 'Escape' && back()}>
      <span>{`${activity.id} ${activity.name} 을(를) 지울까요? 이 액티비티에 걸린 관계도 함께 지워집니다. 지운 뒤에도 되돌리기로 살릴 수 있습니다.`}</span>
      <Button
        variant="danger"
        autoFocus
        onClick={() => {
          onDone();
          void store.getState().deleteActivity(activity.id);
        }}
      >
        지우기
      </Button>
      <Button onClick={back}>취소</Button>
    </div>
  );
}
