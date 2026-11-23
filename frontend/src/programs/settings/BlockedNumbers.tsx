// 차단 목록(Task 85) — 설정 → 알림 연결 → 「받는 범위 · 차단」 안. 기존 길 GET·DELETE /api/notify/blocked(관리자만)를 쓴다.
// 번호는 가린 꼴만 온다. 차단은 연락처 창의 「모르는 번호」에서(peer_key) 하고, 여기서는 보고 [풀기]만 한다. 7개부터 끝자리 찾기.
import { useCallback, useEffect, useState } from 'react';
import { api } from '../../shared/api';
import Button from '../../shared/ui/Button';
import type { LlmError } from './model';
import { ErrorLine, toProblem } from './parts';

export interface BlockedNumber {
  id: number;
  number_masked: string;
  reason: string;
  created_by: string;
  created_at: string;
}

const BASE = '/api/notify/blocked';
const SEARCH_FROM = 7;
const day = (iso: string) => {
  const d = new Date(new Date(iso).getTime() + 9 * 3_600_000);
  return `${d.getUTCMonth() + 1}/${d.getUTCDate()}`;
};

export default function BlockedNumbers({ locked = false }: { locked?: boolean }) {
  const [rows, setRows] = useState<BlockedNumber[] | null>(null);
  const [error, setError] = useState<LlmError | null>(null);
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState('');
  const load = useCallback(() => {
    api<BlockedNumber[]>(BASE).then(
      (r) => setRows(Array.isArray(r) ? r : []),
      (e: unknown) => setError(toProblem(e)),
    );
  }, []);
  useEffect(load, [load]);
  const unblock = (id: number) => {
    setBusy(true);
    setError(null);
    api<void>(`${BASE}/${id}`, { method: 'DELETE' })
      .catch((e: unknown) => setError(toProblem(e)))
      .finally(() => {
        setBusy(false);
        load();
      });
  };
  const all = rows ?? [];
  const digits = query.replace(/\D/g, '');
  const shown = all.length >= SEARCH_FROM && digits ? all.filter((r) => r.number_masked.replace(/\D/g, '').endsWith(digits)) : all;
  return (
    <div className="st-nt-blocked">
      <h5 className="st-nt-sub">차단한 번호</h5>
      {all.length >= SEARCH_FROM && (
        <div className="st-filter-row">
          <input type="search" className="st-search st-nt-filter" aria-label="차단 번호 끝자리 찾기" placeholder="끝자리 찾기" value={query} onChange={(e) => setQuery(e.target.value)} />
          <span className="st-count">{`${shown.length} / ${all.length}개`}</span>
        </div>
      )}
      {rows === null && !error ? (
        <p className="st-muted">읽는 중…</p>
      ) : all.length === 0 && !error ? (
        <p className="st-muted">차단한 번호가 없습니다.</p>
      ) : (
        <ul className="st-nt-allow" aria-label="차단한 번호">
          {shown.map((r) => (
            <li key={r.id}>
              <span className="st-nt-num">{r.number_masked}</span>
              <span className="st-muted st-nt-why">{r.reason || '까닭 없음'}</span>
              <span className="st-muted">{`${r.created_by} · ${day(r.created_at)}`}</span>
              <span className="st-gap" />
              <Button disabled={busy || locked} onClick={() => unblock(r.id)}>
                풀기
              </Button>
            </li>
          ))}
        </ul>
      )}
      <p className="st-muted">차단은 연락처 창의 「모르는 번호」에서 합니다. 차단한 번호의 전화·문자는 받지 않고 기록만 남깁니다.</p>
      <ErrorLine error={error} />
    </div>
  );
}
