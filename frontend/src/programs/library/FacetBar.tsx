// 자료함 왼쪽 다섯 축 체크 필터 레일(시안 A).
import { AXES, type AxesData, type AxisFilters, type AxisName } from './libraryApi';

interface Props {
  axes: AxesData;
  filters: AxisFilters;
  onToggle(axis: AxisName, value: string): void;
  onClear(): void;
}

export default function FacetBar({ axes, filters, onToggle, onClear }: Props) {
  const activeCount = AXES.reduce((sum, a) => sum + (filters[a]?.length ?? 0), 0);

  return (
    <aside className="lib-facets" aria-label="분류 필터">
      <div className="lib-facets-head">
        <h3>분류</h3>
        {activeCount > 0 && (
          <button type="button" className="lib-link-btn" onClick={onClear}>
            초기화 ({activeCount})
          </button>
        )}
      </div>
      <div className="lib-facets-body">
        {AXES.map((axis) => {
          const items = axes[axis] ?? [];
          const picked = filters[axis] ?? [];
          return (
            <fieldset key={axis} className="lib-axis-group">
              <legend>{axis}</legend>
              {items.length === 0 ? (
                <p className="lib-muted">값 없음</p>
              ) : (
                <ul className="lib-axis-list">
                  {items.map((item) => {
                    const checked = picked.includes(item.value);
                    return (
                      <li key={item.value}>
                        <label className={`lib-facet-row ${checked ? 'is-checked' : ''}`}>
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => onToggle(axis, item.value)}
                          />
                          <span className="lib-facet-name">{item.value}</span>
                          {item.is_new && <span className="lib-new-badge">새</span>}
                          <span className="lib-facet-count">{item.count}</span>
                        </label>
                      </li>
                    );
                  })}
                </ul>
              )}
            </fieldset>
          );
        })}
      </div>
    </aside>
  );
}
