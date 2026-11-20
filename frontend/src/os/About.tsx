import { useEffect, useRef } from 'react';
import { version } from '../../package.json';
import Button from '../shared/ui/Button';

/** ChronOS 메뉴 「정보」. */
export default function About({ onClose }: { onClose(): void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => ref.current?.focus(), []);
  return (
    <div
      ref={ref}
      className="os-about"
      role="dialog"
      aria-label="ChronOS 정보"
      tabIndex={-1}
      onKeyDown={(e) => e.key === 'Escape' && onClose()}
    >
      <div className="os-about-name">ChronOS</div>
      <div>버전 {version}</div>
      <div className="os-about-desc">일정을 만들고, 지키고, 고치는 에이전트 OS</div>
      <Button onClick={onClose}>닫기</Button>
    </div>
  );
}
