// 스케줄표의 커서: 키보드 초점 줄(roving tabindex), 지금 칸, 고치는 칸. 콜백은 모두 안정적이다(줄을 다시 그리지 않게).
import { useCallback, useRef, useState, type RefObject } from 'react';
import type { EditEnd } from '../../shared/schedule/CellEditor';
import { type ColKey, type ColumnDef } from '../../shared/schedule/columns';
import { useSelect } from '../../shared/schedule/scope';

export interface Editing {
  aid: string;
  col: ColKey;
}

/** 보이는 칸 가운데 col 의 다음(step 1)·앞(step -1) 고칠 칸. 없으면 null. */
function besideEditable(columns: ColumnDef[], col: ColKey, step: 1 | -1): ColKey | null {
  const editable = columns.filter((c) => c.edit).map((c) => c.key);
  return editable[editable.indexOf(col) + step] ?? null;
}

/** columns: 지금 보이는 칸(Tab 으로 옮겨 갈 칸을 고른다). 콜백이 바뀌지 않게 ref 로 읽는다. */
export function useCursor(bodyRef: RefObject<HTMLTableSectionElement | null>, columns: ColumnDef[]) {
  const cols = useRef(columns);
  cols.current = columns;
  const select = useSelect();
  const [activeCol, setActiveCol] = useState<ColKey>('name');
  const [focusKey, setFocusKey] = useState<string | null>(null);
  const [editing, setEditing] = useState<Editing | null>(null);

  const focusRow = useCallback(
    (key: string) => {
      setFocusKey(key);
      [...(bodyRef.current?.rows ?? [])].find((r) => r.dataset.key === key)?.focus();
    },
    [bodyRef],
  );
  const onPick = useCallback((aid: string, col: ColKey) => {
    select(aid);
    setActiveCol(col);
    setFocusKey(aid);
  }, [select]);
  const onEdit = useCallback(
    (aid: string, col: ColKey) => {
      if (!cols.current.find((c) => c.key === col)?.edit) return;
      onPick(aid, col);
      setEditing({ aid, col });
    },
    [onPick],
  );
  // Tab/Shift+Tab 은 그 줄의 옆 고칠 칸을 연다(없으면 줄로). Enter·Esc 는 줄로, 칸 밖 누름은 그대로 둔다.
  const onEditEnd = useCallback(
    (aid: string, col: ColKey, how: EditEnd) => {
      const beside = how === 'next' || how === 'prev' ? besideEditable(cols.current, col, how === 'next' ? 1 : -1) : null;
      if (beside) {
        setActiveCol(beside);
        setEditing({ aid, col: beside });
        return;
      }
      setEditing(null);
      if (how !== 'leave') focusRow(aid);
    },
    [focusRow],
  );
  const onFocusRow = useCallback(
    (key: string) => {
      if (!key.startsWith('wbs:')) select(key);
      focusRow(key);
    },
    [focusRow, select],
  );
  return { activeCol, setActiveCol, focusKey, editing, setEditing, onPick, onEdit, onEditEnd, onFocusRow };
}
