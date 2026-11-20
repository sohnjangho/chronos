import { useEffect, useState } from 'react';
import { api } from '../shared/api';
import { useApprovals } from './approvals';
import { useWindows } from './windowStore';

interface PendingItem {
  id: number;
  title: string;
  created_at: string;
}

/** 예: "방금", "5분 전", "2시간 전", "3일 전" */
export function ageText(iso: string, now = Date.now()): string {
  const min = Math.max(0, Math.floor((now - Date.parse(iso)) / 60_000));
  if (min < 1) return '방금';
  if (min < 60) return `${min}분 전`;
  const h = Math.floor(min / 60);
  return h < 24 ? `${h}시간 전` : `${Math.floor(h / 24)}일 전`;
}

/**
 * 바탕화면 「승인 대기」 위젯. 대기가 없으면 숨는다. 누르면 승인함에서 그 건을 연다.
 * 승인 수를 다시 읽을 때마다 목록도 다시 읽고, 늦게 온 앞 응답은 버린다.
 */
export default function ApprovalWidget() {
  const pending = useApprovals((s) => s.pending);
  const ticks = useApprovals((s) => s.ticks);
  const open = useWindows((s) => s.open);
  const [items, setItems] = useState<PendingItem[]>([]);

  useEffect(() => {
    if (pending === 0) return;
    let latest = true;
    api<{ items: PendingItem[] }>('/api/approvals?status=pending')
      .then((r) => latest && setItems(r.items.slice(0, 3)))
      .catch(() => {});
    return () => {
      latest = false;
    };
  }, [pending, ticks]);

  if (pending === 0) return null;
  return (
    <section className="os-widget" aria-label="승인 대기">
      <div className="os-widget-title">승인 대기</div>
      <div className="os-widget-count">{pending}</div>
      <ul className="os-widget-list">
        {items.map((a) => (
          <li key={a.id}>
            <button type="button" className="os-widget-item" onClick={() => open('approvals', { id: String(a.id) })}>
              <span className="os-widget-name">{a.title}</span>
              <span className="os-widget-age">{ageText(a.created_at)}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
