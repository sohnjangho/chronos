// 접속 기록(2026-11-25 PM 결정): 왼쪽 계정 목록, 오른쪽 그 계정의 대화(세션별) · 만든 프로젝트 · 기능 사용(요약 칩 + 시간순, 거르기·찾기).
// 기록은 서버가 요청마다 적는다(app.store.activity). 질문 줄의 「실행 추적 →」은 그 턴을 실행 추적 탭에서 연다.
import { useEffect, useState } from 'react';
import { ApiError } from '../../shared/api';
import { devApi, type AccountActivity, type ActivityAccounts } from './devApi';

const TZ = 'Asia/Seoul';
const when = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString('ko-KR', { timeZone: TZ, month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '접속 없음';
const ROLE: Record<string, string> = { admin: '관리자', user: '사용자', field: '현장' };
type Sub = 'chats' | 'projects' | 'features';

function Chats({ data, onOpenTurn }: { data: AccountActivity; onOpenTurn: (id: number) => void }) {
  const [open, setOpen] = useState<number | null>(data.chats[0]?.id ?? null);
  if (data.chats.length === 0) return <p className="dc-empty">아직 에이전트와 나눈 대화가 없습니다.</p>;
  return (
    <ul className="dc-act-list">
      {data.chats.map((c) => (
        <li key={c.id} className="dc-act-chat">
          <button type="button" className="dc-act-chat-head" aria-expanded={open === c.id} onClick={() => setOpen(open === c.id ? null : c.id)}>
            <span aria-hidden="true">{open === c.id ? '▾' : '▸'}</span>
            <b>{c.title}</b>
            <span className="dc-muted">
              {when(c.created_at)} · 글 {c.messages.length}
              {c.schedule ? ` · ${c.schedule}` : ''}
            </span>
          </button>
          {open === c.id && (
            <ol className="dc-act-msgs">
              {c.messages.map((m, i) => (
                <li key={i} className={`dc-act-msg is-${m.role}`}>
                  <span className="dc-act-who">{m.role === 'user' ? '사용자' : '에이전트'} {when(m.at)}</span>
                  <p>{m.text}</p>
                  {m.turn_id !== null && (
                    <button type="button" className="dc-link" onClick={() => onOpenTurn(m.turn_id!)}>
                      실행 추적 →
                    </button>
                  )}
                </li>
              ))}
            </ol>
          )}
        </li>
      ))}
    </ul>
  );
}

function Projects({ data }: { data: AccountActivity }) {
  if (data.projects.length === 0) return <p className="dc-empty">이 계정이 만든 프로젝트가 없습니다.</p>;
  return (
    <table className="dc-act-table" aria-label="만든 프로젝트">
      <thead>
        <tr><th>만든 때</th><th>프로젝트</th><th>분야</th></tr>
      </thead>
      <tbody>
        {data.projects.map((p) => (
          <tr key={p.id}><td>{when(p.created_at)}</td><td>{p.name}</td><td>{p.domain}</td></tr>
        ))}
      </tbody>
    </table>
  );
}

function Features({ data }: { data: AccountActivity }) {
  const [pick, setPick] = useState<string | null>(null);
  const [q, setQ] = useState('');
  const needle = q.trim().toLowerCase();
  const rows = data.features.filter(
    (f) => (pick === null || f.feature === pick) && (!needle || `${f.feature} ${f.schedule ?? ''} ${f.route}`.toLowerCase().includes(needle)),
  );
  if (data.features.length === 0) return <p className="dc-empty">아직 기록된 기능 사용이 없습니다.</p>;
  return (
    <>
      <div className="dc-act-chips" role="group" aria-label="많이 쓴 기능">
        <button type="button" className={`dc-act-chip${pick === null ? ' is-on' : ''}`} onClick={() => setPick(null)}>
          전체 {data.features.length}
        </button>
        {data.summary.map((s) => (
          <button key={s.feature} type="button" className={`dc-act-chip${pick === s.feature ? ' is-on' : ''}`} onClick={() => setPick(pick === s.feature ? null : s.feature)}>
            {s.feature} {s.count}
          </button>
        ))}
      </div>
      <input className="dc-act-search" type="search" placeholder="기능·일정 찾기" aria-label="기능 찾기" value={q} onChange={(e) => setQ(e.target.value)} />
      <table className="dc-act-table" aria-label="기능 사용 기록">
        <thead>
          <tr><th>때</th><th>기능</th><th>일정</th><th>기기</th><th>결과</th></tr>
        </thead>
        <tbody>
          {rows.map((f, i) => (
            <tr key={i}>
              <td>{when(f.at)}</td>
              <td title={`${f.method} ${f.route}`}>{f.feature}</td>
              <td>{f.schedule ?? '—'}</td>
              <td>{f.device ?? '—'}</td>
              <td className={f.status >= 400 ? 'is-danger' : ''}>{f.status >= 400 ? `실패 ${f.status}` : 'OK'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

export default function ActivityTab({ onOpenTurn }: { onOpenTurn: (turnId: number) => void }) {
  const [list, setList] = useState<ActivityAccounts | null>(null);
  const [userId, setUserId] = useState<number | null>(null);
  const [data, setData] = useState<AccountActivity | null>(null);
  const [sub, setSub] = useState<Sub>('chats');
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    devApi
      .activityAccounts()
      .then((l) => {
        if (!live) return;
        setList(l);
        setUserId((cur) => cur ?? l.accounts[0]?.user_id ?? null);
      })
      .catch((e) => live && setError(e instanceof ApiError ? e.message : '접속 기록을 불러오지 못했습니다.'));
    return () => {
      live = false;
    };
  }, []);
  useEffect(() => {
    if (userId === null) return;
    let live = true;
    setData(null);
    devApi
      .activityAccount(userId)
      .then((a) => live && setData(a))
      .catch((e) => live && setError(e instanceof ApiError ? e.message : '접속 기록을 불러오지 못했습니다.'));
    return () => {
      live = false;
    };
  }, [userId]);
  if (error) return <p className="dc-error dc-pad" role="alert">{error}</p>;
  if (!list) return <p className="dc-empty">불러오는 중…</p>;
  const subs: { id: Sub; label: string }[] = [
    { id: 'chats', label: `대화 ${data?.chats.length ?? ''}` },
    { id: 'projects', label: `프로젝트 ${data?.projects.length ?? ''}` },
    { id: 'features', label: `기능 사용 ${data?.features.length ?? ''}` },
  ];
  return (
    <div className="dc-act">
      <nav className="dc-act-accounts" aria-label="계정">
        <ul>
          {list.accounts.map((a) => (
            <li key={a.user_id}>
              <button type="button" className={`dc-act-acc${a.user_id === userId ? ' is-on' : ''}`} aria-current={a.user_id === userId} onClick={() => setUserId(a.user_id)}>
                <b>{a.name}</b>
                <span className="dc-muted">{a.login_id} · {ROLE[a.role] ?? a.role}</span>
                <span className="dc-muted">
                  {when(a.last_at)} · 로그인 {a.logins}
                  {a.failed_logins > 0 && <span className="is-danger"> · 실패 {a.failed_logins}</span>}
                </span>
              </button>
            </li>
          ))}
        </ul>
        {list.unknown_failed.length > 0 && (
          <p className="dc-muted dc-act-unknown">
            없는 아이디로 로그인 시도 {list.unknown_failed.length}건 (최근: {list.unknown_failed[0].login_id}, {when(list.unknown_failed[0].at)})
          </p>
        )}
      </nav>
      <section className="dc-act-main dc-scroll" aria-label="계정 기록">
        {!data ? (
          <p className="dc-empty">불러오는 중…</p>
        ) : (
          <>
            <h3 className="dc-act-title">
              {data.account.name} <span className="dc-muted">({data.account.login_id} · {ROLE[data.account.role] ?? data.account.role}) 마지막 접속 {when(data.account.last_at)}</span>
            </h3>
            <div className="dc-act-subs" role="tablist" aria-label="기록 종류">
              {subs.map((s) => (
                <button key={s.id} type="button" role="tab" aria-selected={sub === s.id} className={`dc-act-sub${sub === s.id ? ' is-on' : ''}`} onClick={() => setSub(s.id)}>
                  {s.label}
                </button>
              ))}
            </div>
            {sub === 'chats' && <Chats key={data.account.user_id} data={data} onOpenTurn={onOpenTurn} />}
            {sub === 'projects' && <Projects data={data} />}
            {sub === 'features' && <Features key={data.account.user_id} data={data} />}
          </>
        )}
      </section>
    </div>
  );
}
