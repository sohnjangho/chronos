// 시스템 진단(Health) 탭: LLM 연결 · Qdrant 벡터 DB · 근거 검색/MCP · SQLite DB 현황 · 실행 중 턴 제어,
// 11-23: 정보 API 연결 · 근거 다시 쓰기 · 공휴일 표 · 그림 읽기 배정(HealthTodayCards).
// Task 108: 알림 연결 묶음(NotifyHealthCard — 저장된 마지막 연결 진단을 보일 뿐, 다시 돌리지 않는다).
// Task 111: 그 아래 카카오톡 칸(KakaoHealthCard — 저장된 채널·문안 상태, 제공사를 부르지 않음).
// Task 110: 그 아래 AI 전화 묶음(VoiceHealthCard — 음성 설정이 있을 때만, 마지막 음성 진단·통화 일꾼 상태).
import { useCallback, useEffect, useState } from 'react';
import { ApiError } from '../../shared/api';
import Badge from '../../shared/ui/Badge';
import { devApi, type HealthOut } from './devApi';
import HealthTodayCards from './HealthTodayCards';
import KakaoHealthCard from './KakaoHealthCard';
import NotifyHealthCard from './NotifyHealthCard';
import VoiceHealthCard from './VoiceHealthCard';

function bytesText(bytes: number): string {
  if (bytes <= 0) return '0 B';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function statusBadge(status: 'ok' | 'warn' | 'error' | 'off') {
  if (status === 'ok') return <Badge tone="success">정상</Badge>;
  if (status === 'warn') return <Badge tone="warning">주의</Badge>;
  if (status === 'off') return <Badge tone="neutral">꺼짐</Badge>;
  return <Badge tone="danger">오류</Badge>;
}

const DB_LABELS: Record<string, string> = {
  users: '사용자',
  schedules: '프로젝트 일정',
  chats: '대화 세션',
  workflow_runs: '워크플로우 실행',
  files: '자료함 파일',
  approvals: '승인 대기',
  reports: '보고서',
  skills: '저장 스킬',
};

/** LLM 연결 · Qdrant · 근거 검색 · SQLite — 예전부터 있던 네 칸. */
function CoreCards({ data }: { data: HealthOut }) {
  return (
    <>
      <article className="dc-health-card">
        <div className="dc-health-head">
          <h3>LLM 연결</h3>
          {statusBadge(data.llm.status)}
        </div>
        <p className="dc-muted">{data.llm.message}</p>
        <dl className="dc-health-kv">
          <div><dt>기본 연결</dt><dd>{data.llm.default_name ?? '—'}</dd></div>
          <div><dt>제공자</dt><dd>{data.llm.default_provider ?? '—'}</dd></div>
          <div><dt>등록 연결 / 배정</dt><dd>{`${data.llm.connections_count}개 / ${data.llm.assignments_count}개`}</dd></div>
        </dl>
      </article>

      <article className="dc-health-card">
        <div className="dc-health-head">
          <h3>Qdrant 벡터 DB</h3>
          {statusBadge(data.qdrant.status)}
        </div>
        <p className="dc-muted">{data.qdrant.message}</p>
        <dl className="dc-health-kv">
          <div><dt>컬렉션</dt><dd>{data.qdrant.collections.length ? data.qdrant.collections.join(', ') : '없음'}</dd></div>
          <div><dt>벡터 점 수</dt><dd>{data.qdrant.points_count.toLocaleString()}</dd></div>
          <div><dt>응답 지연</dt><dd>{data.qdrant.latency_ms !== null ? `${data.qdrant.latency_ms}ms` : '—'}</dd></div>
        </dl>
      </article>

      <article className="dc-health-card">
        <div className="dc-health-head">
          <h3>근거 검색 · MCP</h3>
          {statusBadge(data.search.status)}
        </div>
        <p className="dc-muted">{data.search.message}</p>
        <dl className="dc-health-kv">
          <div><dt>상태</dt><dd>{data.search.ready ? '준비됨' : '미연결'}</dd></div>
          <div><dt>최근 7일 호출</dt><dd>{`${data.search.calls_7d}회`}</dd></div>
          <div><dt>최근 7일 실패</dt><dd>{`${data.search.failed_7d}건`}</dd></div>
        </dl>
      </article>

      <article className="dc-health-card">
        <div className="dc-health-head">
          <h3>SQLite DB 현황</h3>
          {statusBadge(data.db.status)}
        </div>
        <p className="dc-muted">{`파일 크기 ${bytesText(data.db.size_bytes)}`}</p>
        <dl className="dc-health-kv">
          {Object.entries(data.db.counts).map(([k, v]) => (
            <div key={k}>
              <dt>{DB_LABELS[k] ?? k}</dt>
              <dd>{v.toLocaleString()}</dd>
            </div>
          ))}
        </dl>
      </article>
    </>
  );
}

/** 실행 중인 에이전트 턴과 강제 중단. */
function ActiveTurns({ turns, stoppingId, onStop }: { turns: HealthOut['active_turns']; stoppingId: number | null; onStop(id: number): void }) {
  return (
    <section className="dc-health-turns" aria-label="실행 중인 에이전트 턴">
      <div className="dc-cat-header">
        <h3 className="dc-cat-h2">{`실행 중인 에이전트 턴 (${turns.length}건)`}</h3>
        <p className="dc-muted">
          응답이 길게 멈춘 턴이 있으면 여기에서 안전하게 중단 신호를 보낼 수 있습니다.
        </p>
      </div>
      {turns.length === 0 ? (
        <p className="dc-empty">현재 실행 중인 에이전트 턴이 없습니다.</p>
      ) : (
        <table className="dc-cat-table" aria-label="실행 중 턴 목록">
          <thead>
            <tr>
              <th>대화 ID</th>
              <th>제목</th>
              <th>중단 요청 여부</th>
              <th>제어</th>
            </tr>
          </thead>
          <tbody>
            {turns.map((t) => (
              <tr key={t.chat_session_id} className="dc-cat-row">
                <td><code>{`#${t.chat_session_id}`}</code></td>
                <td>{t.title}</td>
                <td>{t.stop_requested ? <Badge tone="warning">중단 신호 전송됨</Badge> : <Badge tone="info">실행 중</Badge>}</td>
                <td>
                  <button
                    type="button"
                    className="dc-btn"
                    disabled={t.stop_requested || stoppingId === t.chat_session_id}
                    onClick={() => onStop(t.chat_session_id)}
                  >
                    {stoppingId === t.chat_session_id ? '중단 중…' : '강제 중단'}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

export default function HealthTab() {
  const [data, setData] = useState<HealthOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [stoppingId, setStoppingId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const next = await devApi.health();
      setData(next);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '시스템 진단 정보를 불러오지 못했습니다.');
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function stopTurn(chatId: number) {
    setStoppingId(chatId);
    try {
      await devApi.stopTurn(chatId);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '실행 중단에 실패했습니다.');
    } finally {
      setStoppingId(null);
    }
  }

  return (
    <div className="dc-scroll dc-cat-wrap">
      <div className="dc-cfg-head">
        <div>
          <h2 className="dc-cat-h2">시스템 진단 (Health)</h2>
          <p className="dc-muted">
            LLM 연결·키 복호화, Qdrant 벡터 검색 서버, Liner Search/MCP, SQLite DB, 정보 API 연결·근거 다시 쓰기·공휴일 표·그림 읽기 배정·알림 연결 및 현재 실행 중인 에이전트 턴 상태를 점검합니다.
          </p>
        </div>
        <div className="dc-cfg-actions">
          <button type="button" className="dc-btn" disabled={busy} onClick={() => void load()}>
            {busy ? '점검 중…' : '진단 새로고침'}
          </button>
        </div>
      </div>

      {error && (
        <p className="dc-error" role="alert">
          {error}
        </p>
      )}
      {!data && !error && <p className="dc-empty">시스템 상태를 점검하는 중…</p>}

      {data && (
        <>
          <div className="dc-health-grid" role="region" aria-label="핵심 인프라 진단">
            <CoreCards data={data} />
            <HealthTodayCards data={data} badge={(st) => statusBadge(st as Parameters<typeof statusBadge>[0])} />
            {data.notify && <NotifyHealthCard n={data.notify} />}
            {data.notify?.kakao && <KakaoHealthCard k={data.notify.kakao} />}
            {data.notify?.voice && <VoiceHealthCard v={data.notify.voice} />}
          </div>
          <ActiveTurns turns={data.active_turns} stoppingId={stoppingId} onStop={(id) => void stopTurn(id)} />
        </>
      )}
    </div>
  );
}
