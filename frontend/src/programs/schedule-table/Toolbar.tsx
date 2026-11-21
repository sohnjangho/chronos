import Badge from '../../shared/ui/Badge';
import Button from '../../shared/ui/Button';
import { percent } from '../../shared/schedule/format';
import History from '../../shared/schedule/History';
import { useScheduleStore } from '../../shared/schedule/scope';
import type { ColKey } from '../../shared/schedule/columns';
import { ColumnPanel, FilterPanel } from '../../shared/schedule/FilterPanel';
import Popover from '../../shared/schedule/Popover';
import { filterCount, type RowFilter } from '../../shared/schedule/rows';
import type { Activity, Wbs, WeightMode } from '../../shared/schedule/scheduleApi';

interface ToolbarProps {
  query: string;
  onQuery(q: string): void;
  filter: RowFilter;
  onFilter(f: RowFilter): void;
  visible: ColKey[];
  onVisible(keys: ColKey[]): void;
  wbs: Wbs[];
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

/** 위 도구줄: 행 추가·삭제 · 검색 · 필터 · 열 · 되돌리기·다시 하기 · 가중치 · 진척 · CSV 내보내기. 좁으면 줄을 바꾼다. */
export default function Toolbar(p: ToolbarProps) {
  const n = filterCount(p.filter);
  return (
    <div role="toolbar" aria-label="스케줄표 도구" className="sch-toolbar">
      <Button variant="primary" disabled={!p.canAdd} onClick={p.onAdd}>
        + 행 추가
      </Button>
      <Button variant="danger" data-act="delete" disabled={!p.canDelete} onClick={p.onDelete}>
        삭제
      </Button>
      <input
        type="search"
        className="sch-search"
        aria-label="코드·이름 검색"
        placeholder="코드·이름 검색"
        value={p.query}
        onChange={(e) => p.onQuery(e.target.value)}
      />
      <Popover button={n ? `필터 ${n}` : '필터'} label="필터">
        {() => <FilterPanel filter={p.filter} onFilter={p.onFilter} wbs={p.wbs} />}
      </Popover>
      <Popover button="열" label="열">
        {() => <ColumnPanel visible={p.visible} onVisible={p.onVisible} />}
      </Popover>
      <span className="sch-sep" aria-hidden="true" />
      <History />
      <label className="sch-weight">
        가중치
        <select aria-label="가중치" value={p.weightMode} onChange={(e) => p.onWeightMode(e.target.value as WeightMode)}>
          <option value="duration">기간 비례</option>
          <option value="manual">직접 입력</option>
        </select>
      </label>
      <span className="sch-gap" />
      {p.progress !== null && <Badge tone="info">{`전체 가중 진척도 ${percent(p.progress)}%`}</Badge>}
      <Button onClick={p.onExport}>CSV 내보내기</Button>
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
