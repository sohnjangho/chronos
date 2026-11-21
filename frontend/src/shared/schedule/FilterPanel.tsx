// 스케줄표·간트차트 공용 필터 패널과 열 표시 체크박스 패널.
import Button from '../ui/Button';
import { COLUMNS, FIXED, type ColKey } from './columns';
import { STATUS_KEYS, type StatusKey } from './format';
import { NO_FILTER, wbsLabel, type RowFilter } from './rows';
import type { Wbs } from './scheduleApi';

export function FilterPanel({ filter, onFilter, wbs }: { filter: RowFilter; onFilter(f: RowFilter): void; wbs: Wbs[] }) {
  const flip = (k: StatusKey) =>
    onFilter({ ...filter, statuses: filter.statuses.includes(k) ? filter.statuses.filter((s) => s !== k) : [...filter.statuses, k] });
  return (
    <div className="sch-pop-body">
      <fieldset className="sch-fieldset">
        <legend>상태</legend>
        {STATUS_KEYS.map((s) => (
          <label key={s.key} className="sch-check">
            <input type="checkbox" checked={filter.statuses.includes(s.key)} onChange={() => flip(s.key)} />
            {s.label}
          </label>
        ))}
      </fieldset>
      <label className="sch-check">
        <input type="checkbox" checked={filter.criticalOnly} onChange={(e) => onFilter({ ...filter, criticalOnly: e.target.checked })} />
        크리티컬만
      </label>
      <label className="sch-field">
        WBS
        <select value={filter.wbs ?? ''} onChange={(e) => onFilter({ ...filter, wbs: e.target.value || null })}>
          <option value="">전체</option>
          {wbs.map((w) => (
            <option key={w.code} value={w.code}>
              {wbsLabel(w)}
            </option>
          ))}
        </select>
      </label>
      <Button onClick={() => onFilter({ ...NO_FILTER, query: filter.query })}>필터 지우기</Button>
    </div>
  );
}

export function ColumnPanel({ visible, onVisible }: { visible: ColKey[]; onVisible(keys: ColKey[]): void }) {
  const flip = (k: ColKey) => onVisible(visible.includes(k) ? visible.filter((v) => v !== k) : [...visible, k]);
  const group = (optional: boolean) =>
    COLUMNS.filter((c) => !FIXED.includes(c.key) && !!c.optional === optional).map((c) => (
      <label key={c.key} className="sch-check">
        <input type="checkbox" checked={visible.includes(c.key)} onChange={() => flip(c.key)} />
        {c.header}
      </label>
    ));
  return (
    <div className="sch-pop-body sch-cols">
      <fieldset className="sch-fieldset">
        <legend>기본 칸</legend>
        {group(false)}
      </fieldset>
      <fieldset className="sch-fieldset">
        <legend>켜는 칸</legend>
        {group(true)}
      </fieldset>
    </div>
  );
}
