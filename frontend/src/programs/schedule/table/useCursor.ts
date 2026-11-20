// 스케줄표의 커서: 키보드 초점 줄(roving tabindex), 지금 칸, 고치는 칸. 콜백은 모두 안정적이다(줄을 다시 그리지 않게).
import { useCallback, useState, type RefObject } from 'react';
import type { Activity } from '../scheduleApi';
import { useSchedule } from '../scheduleStore';
import { COLUMNS, type ColKey, type ColumnDef } from './columns';
import { toRequest } from './edits';

export interface Editing {
  aid: string;
  col: ColKey;
}

/** 적은 글을 요청으로 바꿔 보낸다. 틀린 글은 보내지 않고 알림. */
export async function commitCell(a: Activity, col: ColumnDef, text: string): Promise<unknown> {
  const store = useSchedule.getState();
  const req = toRequest(col.key, text);
  if ('error' in req) return store.setNotice({ tone: 'error', text: req.error });
  return 'preds' in req ? store.setPredecessors(a.id, req.preds) : store.patchActivity(a.id, req.patch);
}

export function useCursor(bodyRef: RefObject<HTMLTableSectionElement | null>) {
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
    useSchedule.getState().select(aid);
    setActiveCol(col);
    setFocusKey(aid);
  }, []);
  const onEdit = useCallback(
    (aid: string, col: ColKey) => {
      if (!COLUMNS.find((c) => c.key === col)?.edit) return;
      onPick(aid, col);
      setEditing({ aid, col });
    },
    [onPick],
  );
  const onEditEnd = useCallback(
    (aid: string, refocus: boolean) => {
      setEditing(null);
      if (refocus) focusRow(aid);
    },
    [focusRow],
  );
  const onFocusRow = useCallback(
    (key: string) => {
      if (!key.startsWith('wbs:')) useSchedule.getState().select(key);
      focusRow(key);
    },
    [focusRow],
  );
  return { activeCol, setActiveCol, focusKey, editing, setEditing, onPick, onEdit, onEditEnd, onFocusRow };
}
