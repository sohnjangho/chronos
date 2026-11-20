// 관리자용 분류 값 합치기 제안 띠(시안 A — 표 위 노란 띠).
import { useState } from 'react';
import Button from '../../shared/ui/Button';
import type { MergeSuggestion } from './libraryApi';

interface Props {
  items: MergeSuggestion[];
  busyKey: string | null;
  error: string | null;
  onMerge(item: MergeSuggestion): void;
}

export default function MergeSuggestions({ items, busyKey, error, onMerge }: Props) {
  const [open, setOpen] = useState(false);
  if (items.length === 0) return null;

  return (
    <section className="lib-merge" aria-label="분류 값 합치기 제안">
      <div className="lib-merge-bar">
        <span>
          비슷한 분류 값 합치기 제안 <strong>{items.length}건</strong>이 있습니다.
        </span>
        <button
          type="button"
          className="lib-link-btn"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
        >
          {open ? '접기' : '제안 보기'}
        </button>
      </div>
      {error && (
        <p className="lib-error" role="alert">
          {error}
        </p>
      )}
      {open && (
        <ul className="lib-merge-list">
          {items.map((item) => {
            const key = `${item.axis}:${item.from.join(',')}:${item.to}`;
            const busy = busyKey === key;
            return (
              <li key={key} className="lib-merge-item">
                <div className="lib-merge-desc">
                  <span className="lib-merge-axis">{item.axis}</span>
                  <span>
                    <strong>{item.from.join(', ')}</strong> → <strong>{item.to}</strong>
                  </span>
                  <span className="lib-muted">{item.why}</span>
                </div>
                <Button disabled={busy} onClick={() => onMerge(item)}>
                  {busy ? '합치는 중…' : '합치기'}
                </Button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
