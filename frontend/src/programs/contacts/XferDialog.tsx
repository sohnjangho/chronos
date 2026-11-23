// 연락처 창 안의 겹화면 틀(CSV 가져오기·다른 프로젝트에서 복사). 열리면 첫 입력에 초점, Tab 은 안에서만, Esc 는 닫기(일하는 중이 아니면),
// 닫히면 연 단추로 초점이 돌아간다. 틀은 세로로 세 층 — 머리(위)·본문(가운데만 스크롤)·발(아래 단추) — 이라 긴 목록에도 머리와 단추가 보인다.
import { useEffect, useRef, type ReactNode } from 'react';
import { useModalFocus } from '../../os/modalFocus';
import './transfer.css';

interface Props {
  title: string;
  wide?: boolean;
  /** 서버에 쓰는 중이면 Esc 로 닫지 않는다. */
  busy: boolean;
  onClose(): void;
  children: ReactNode;
  foot: ReactNode;
}

const FIRST = 'input:not([disabled]), select:not([disabled]), button:not([disabled])';

export default function XferDialog({ title, wide = false, busy, onClose, children, foot }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const trap = useModalFocus(ref);
  useEffect(() => {
    ref.current?.querySelector<HTMLElement>(FIRST)?.focus({ preventScroll: true });
  }, []);
  return (
    <div className="ct-scrim">
      <div
        ref={ref}
        className={`ct-xfer${wide ? ' is-wide' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            e.stopPropagation();
            if (!busy) onClose();
          }
          trap(e);
        }}
      >
        <h2 className="ct-xfer-title">{title}</h2>
        {children}
        <div className="ct-xfer-foot">{foot}</div>
      </div>
    </div>
  );
}
