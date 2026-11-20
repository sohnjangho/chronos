import { useRef, type KeyboardEvent } from 'react';
import { KIND_LABEL } from '../format';
import { useSchedule } from '../scheduleStore';
import type { ColumnDef } from './columns';
import { wbsLabel } from './rows';

interface CellEditorProps {
  col: ColumnDef;
  /** 글 칸은 보이는 글, 고르는 칸은 지금 값(유형 코드·WBS 코드). */
  initial: string;
  label: string;
  /** refocus: Enter·Esc 로 끝냈으면 참(행으로 초점을 돌린다), 칸 밖을 눌러 끝냈으면 거짓. */
  onCommit(text: string, refocus: boolean): void;
  onCancel(refocus: boolean): void;
}

/** 저장·취소를 한 번만 하게 하고(언마운트하며 생기는 blur 를 무시), Enter·Esc 를 처리한다. */
function useFinish({ onCommit, onCancel }: Pick<CellEditorProps, 'onCommit' | 'onCancel'>) {
  const done = useRef(false);
  const finish = (fn: () => void) => {
    if (done.current) return;
    done.current = true;
    fn();
  };
  const onKeyDown = (e: KeyboardEvent<HTMLInputElement | HTMLSelectElement>) => {
    e.stopPropagation();
    if (e.key === 'Escape') finish(() => onCancel(true));
    else if (e.key === 'Enter' && e.currentTarget instanceof HTMLInputElement) {
      const value = e.currentTarget.value;
      finish(() => onCommit(value, true));
    } else return;
    e.preventDefault();
  };
  return { finish, onKeyDown };
}

const stop = (e: { stopPropagation(): void }) => e.stopPropagation();

/** 유형·WBS: 목록에서 고르면 바로 저장, 고르지 않고 나가면 취소. */
function SelectEditor({ col, initial, label, onCommit, onCancel }: CellEditorProps) {
  const { finish, onKeyDown } = useFinish({ onCommit, onCancel });
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
      onChange={(e) => {
        const value = e.target.value;
        finish(() => onCommit(value, true));
      }}
      onBlur={() => finish(() => onCancel(false))}
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

/** 칸 안의 입력. Enter·바깥 누름은 저장, Esc 는 취소. */
export default function CellEditor(props: CellEditorProps) {
  const { finish, onKeyDown } = useFinish(props);
  if (props.col.edit === 'kind' || props.col.edit === 'wbs') return <SelectEditor {...props} />;
  return (
    <input
      className="sch-editor"
      aria-label={props.label}
      autoFocus
      defaultValue={props.initial}
      onFocus={(e) => e.currentTarget.select()}
      onBlur={(e) => {
        const value = e.currentTarget.value;
        finish(() => props.onCommit(value, false));
      }}
      onKeyDown={onKeyDown}
      onClick={stop}
      onDoubleClick={stop}
    />
  );
}
