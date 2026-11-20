import { useRef, type KeyboardEvent } from 'react';
import { KIND_LABEL } from '../format';
import { useSchedule } from '../scheduleStore';
import type { ColumnDef } from './columns';
import { wbsLabel } from './rows';

/** 고치기가 끝난 방법: Enter·Esc(줄로 초점) · 칸 밖을 누름 · Tab(다음 고칠 칸) · Shift+Tab(앞 고칠 칸). */
export type EditEnd = 'stay' | 'leave' | 'next' | 'prev';

interface CellEditorProps {
  col: ColumnDef;
  /** 글 칸은 보이는 글, 고르는 칸은 지금 값(유형 코드·WBS 코드). */
  initial: string;
  label: string;
  onCommit(text: string, how: EditEnd): void;
  onCancel(how: EditEnd): void;
}

/**
 * 저장·취소를 한 번만 하게 하고(언마운트하며 생기는 blur 를 무시), 키를 처리한다.
 * Enter 저장 · Esc 취소 · Tab/Shift+Tab 저장하고 옆 고칠 칸 · 칸 밖을 누르면 저장.
 */
function useFinish({ onCommit, onCancel }: Pick<CellEditorProps, 'onCommit' | 'onCancel'>) {
  const done = useRef(false);
  const finish = (fn: () => void) => {
    if (done.current) return;
    done.current = true;
    fn();
  };
  const onKeyDown = (e: KeyboardEvent<HTMLInputElement | HTMLSelectElement>) => {
    e.stopPropagation();
    const value = e.currentTarget.value;
    if (e.key === 'Escape') finish(() => onCancel('stay'));
    else if (e.key === 'Enter') finish(() => onCommit(value, 'stay'));
    else if (e.key === 'Tab') finish(() => onCommit(value, e.shiftKey ? 'prev' : 'next'));
    else return;
    e.preventDefault();
  };
  const onBlur = (value: string) => finish(() => onCommit(value, 'leave'));
  return { onKeyDown, onBlur };
}

const stop = (e: { stopPropagation(): void }) => e.stopPropagation();

/** 유형·WBS: 목록에서 골라도 바로 보내지 않고(화살표로 훑을 때 매번 가지 않게) Enter·Tab·칸을 떠날 때 저장. */
function SelectEditor({ col, initial, label, onCommit, onCancel }: CellEditorProps) {
  const { onKeyDown, onBlur } = useFinish({ onCommit, onCancel });
  const options =
    col.edit === 'kind'
      ? Object.entries(KIND_LABEL).map(([value, text]) => ({ value, text }))
      : (useSchedule.getState().view?.wbs ?? []).map((w) => ({ value: w.code, text: wbsLabel(w) }));
  return (
    <select
      className="sch-editor"
      aria-label={label}
      autoFocus
      defaultValue={initial}
      onBlur={(e) => onBlur(e.currentTarget.value)}
      onKeyDown={onKeyDown}
      onClick={stop}
      onDoubleClick={stop}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.text}
        </option>
      ))}
    </select>
  );
}

/** 칸 안의 입력. */
export default function CellEditor(props: CellEditorProps) {
  const { onKeyDown, onBlur } = useFinish(props);
  if (props.col.edit === 'kind' || props.col.edit === 'wbs') return <SelectEditor {...props} />;
  return (
    <input
      className="sch-editor"
      aria-label={props.label}
      autoFocus
      defaultValue={props.initial}
      onFocus={(e) => e.currentTarget.select()}
      onBlur={(e) => onBlur(e.currentTarget.value)}
      onKeyDown={onKeyDown}
      onClick={stop}
      onDoubleClick={stop}
    />
  );
}
