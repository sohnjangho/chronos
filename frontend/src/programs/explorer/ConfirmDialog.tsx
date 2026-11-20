// 창 안의 확인 겹화면(window.confirm 을 쓰지 않는다). 처음 포커스는 [취소], Esc 도 취소.
import { useRef, type ReactNode } from 'react';
import { useModalFocus } from '../../os/modalFocus';
import Button from '../../shared/ui/Button';

interface Props {
  title: string;
  confirm: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm(): void;
  onCancel(): void;
  children: ReactNode;
}

export default function ConfirmDialog({ title, confirm, danger = false, busy = false, onConfirm, onCancel, children }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const trap = useModalFocus(ref);
  return (
    <div className="ex-scrim">
      <div
        ref={ref}
        className="ex-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-label={title}
        onKeyDown={(e) => {
          if (e.key === 'Escape') onCancel();
          trap(e);
        }}
      >
        <h3 className="ex-dialog-h">{title}</h3>
        <div className="ex-dialog-b">{children}</div>
        <div className="ex-dialog-row">
          <Button variant={danger ? 'danger' : 'primary'} disabled={busy} onClick={onConfirm}>
            {confirm}
          </Button>
          <Button autoFocus disabled={busy} onClick={onCancel}>
            취소
          </Button>
        </div>
      </div>
    </div>
  );
}
