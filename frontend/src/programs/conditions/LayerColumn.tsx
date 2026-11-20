import { useId, type ReactNode } from 'react';
import { isAdd, type AnyChange, type Cond, type CondView, type Layer } from './condApi';
import type { EditPatch } from './condStore';
import ConditionItem from './ConditionItem';
import { grouped } from './labels';

/** 조건이 이보다 많으면 칸 안에서 종류별로 묶어 보인다. */
const GROUP_FROM = 7;

interface ColumnProps {
  layer: Layer;
  title: string;
  lock?: string;
  note: string;
  /** 거른 뒤 보일 조건(보이는 상태). */
  items: Cond[];
  /** 이 겹의 조건 수(거르기 전). */
  total: number;
  saved: Map<string, Cond>;
  edits: Record<string, AnyChange>;
  resources: CondView['resources'];
  /** 입력 칸 열쇠(바뀌면 칸을 저장값으로 새로 그린다). */
  fieldsKey: string;
  onEdit(id: string, patch: EditPatch): void;
  /** 목록 아래에 붙일 것(③ 칸의 저장된 내 규칙). */
  children?: ReactNode;
}

/** 겹 하나의 칸: 머리(이름·잠금·설명·수) + 조건 목록(많으면 종류별 묶음). 칸 안에서 세로로 스크롤한다. */
export default function LayerColumn(props: ColumnProps) {
  const { layer, title, lock, note, items, total } = props;
  const headId = useId();
  const groups = total >= GROUP_FROM ? grouped(items) : [{ label: '', items }];
  const item = (c: Cond) => {
    const change = props.edits[c.id];
    return (
      <ConditionItem
        key={`${c.id}-${props.fieldsKey}`}
        cond={c}
        saved={props.saved.get(c.id) ?? c}
        change={isAdd(change) ? undefined : change}
        resources={props.resources}
        onEdit={props.onEdit}
      />
    );
  };
  return (
    <section className={`cd-col is-${layer}`} aria-labelledby={headId}>
      <header className="cd-head">
        <div className="cd-head-line">
          <h3 id={headId}>{title}</h3>
          {lock && <span className="cd-lock">{lock}</span>}
          <span className="cd-count">{`${total}개`}</span>
        </div>
        <p className="cd-muted">{note}</p>
      </header>
      <div className="cd-list">
        {items.length === 0 && <p className="cd-empty">{total === 0 ? '조건 없음' : '맞는 조건 없음'}</p>}
        {groups.map((g) =>
          g.label ? (
            <div key={g.label} className="cd-group">
              <h4 className="cd-group-head">{`${g.label} ${g.items.length}`}</h4>
              <ul className="cd-items">{g.items.map(item)}</ul>
            </div>
          ) : (
            g.items.length > 0 && (
              <ul key="all" className="cd-items">
                {g.items.map(item)}
              </ul>
            )
          ),
        )}
        {props.children}
      </div>
    </section>
  );
}
