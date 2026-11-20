// 창 안의 겹화면(제출·만약에·버리기 확인). Esc 는 닫기, Tab 은 안에서만 돈다. 글은 부르는 쪽이 준다.
import { useRef, type ReactNode } from 'react';
import { useModalFocus } from '../../os/modalFocus';

interface Props {
  title: string;
  /** 되돌릴 수 없는 일을 묻는 확인이면 alertdialog. */
  alert?: boolean;
  onClose(): void;
  children: ReactNode;
  /** 아래 단추 줄. */
  actions: ReactNode;
}

export default function Dialog({ title, alert = false, onClose, children, actions }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const trap = useModalFocus(ref);
  return (
    <div className="cmp-scrim">
      <div
        ref={ref}
        className="cmp-dialog"
        role={alert ? 'alertdialog' : 'dialog'}
        aria-modal="true"
        aria-label={title}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            e.stopPropagation();
            onClose();
          }
          trap(e);
        }}
      >
        <h3 className="cmp-dialog-h">{title}</h3>
        <div className="cmp-dialog-b">{children}</div>
        <div className="cmp-dialog-row">{actions}</div>
      </div>
    </div>
  );
}
