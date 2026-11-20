import { useState } from 'react';
import { useSession } from '../../os/session';
import Badge from '../../shared/ui/Badge';
import Button from '../../shared/ui/Button';
import type { SessionItem } from './chatApi';
import { useChat } from './chatStore';

/** 목록·제목 줄에 보일 대화 이름. 대화가 없으면 빈 글. */
export function sessionTitle(sessions: SessionItem[], id: number | null): string {
  if (id === null) return '';
  return sessions.find((s) => s.id === id)?.title || '제목 없는 대화';
}

const DAY = 86_400_000;
const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();

/** 만든 날로 묶는다: 오늘 · 어제 · 지난 7일 · 이전. */
function groupOf(createdAt: string, today: number): string {
  const t = Date.parse(createdAt);
  if (Number.isNaN(t)) return '이전';
  const days = Math.round((today - startOfDay(new Date(t))) / DAY);
  if (days <= 0) return '오늘';
  if (days === 1) return '어제';
  return days <= 7 ? '지난 7일' : '이전';
}

function grouped(sessions: SessionItem[]): [string, SessionItem[]][] {
  const today = startOfDay(new Date());
  const groups = new Map<string, SessionItem[]>();
  for (const s of sessions) {
    const g = groupOf(s.created_at, today);
    groups.set(g, [...(groups.get(g) ?? []), s]);
  }
  return [...groups];
}

function ThreadButton({ s, current, onPick }: { s: SessionItem; current: boolean; onPick(): void }) {
  const retries = s.pending_retries ?? 0;
  return (
    <button type="button" className="ch-th" aria-current={current ? 'true' : undefined} onClick={onPick}>
      <span className="ch-ellipsis">{s.title || '제목 없는 대화'}</span>
      {retries > 0 && (
        <Badge tone="warning" className="ch-th-badge">
          다시 짜기 {retries}
        </Badge>
      )}
    </button>
  );
}

/**
 * 대화 목록: [새 대화] · 찾기 · 날짜 묶음. 큰 화면의 왼쪽(268px), 작은 화면에서는 위쪽 [대화 고르기]의 펼침.
 * '다시 짜기 요청'이 기다리는 대화에는 배지가 붙는다.
 */
export default function ThreadList({ popover = false, onPicked }: { popover?: boolean; onPicked?(): void }) {
  const sessions = useChat((s) => s.sessions);
  const currentId = useChat((s) => s.currentId);
  const listNotice = useChat((s) => s.listNotice);
  const user = useSession((s) => s.session?.user);
  const [query, setQuery] = useState('');
  const shown = sessions.filter((s) => s.title.toLowerCase().includes(query.trim().toLowerCase()));
  const Wrap = popover ? 'div' : 'aside';
  const pick = (id: number) => {
    void useChat.getState().openSession(id);
    onPicked?.();
  };
  return (
    <Wrap className={popover ? 'ch-side is-popover' : 'ch-side'} aria-label={popover ? undefined : '대화 목록'}>
      <Button
        variant="primary"
        className="ch-new"
        onClick={() => {
          useChat.getState().newChat();
          onPicked?.();
        }}
      >
        <span aria-hidden="true">+</span> 새 대화
      </Button>
      <input type="search" className="ch-search" aria-label="대화 검색" placeholder="대화 검색" value={query} onChange={(e) => setQuery(e.target.value)} />
      <div className="ch-threads">
        {listNotice && <p className="ch-muted">{listNotice}</p>}
        {!listNotice && shown.length === 0 && <p className="ch-muted">{query ? '찾는 대화가 없습니다.' : '아직 대화가 없습니다.'}</p>}
        {grouped(shown).map(([group, items]) => (
          <div key={group} role="group" aria-label={group}>
            <div className="ch-grp">{group}</div>
            {items.map((s) => (
              <ThreadButton key={s.id} s={s} current={s.id === currentId} onPick={() => pick(s.id)} />
            ))}
          </div>
        ))}
      </div>
      {!popover && user && (
        <div className="ch-user">
          {user.name} · {user.role === 'admin' ? '관리자' : '사용자'}
        </div>
      )}
    </Wrap>
  );
}
