// 하루 LLM 비용 상한 카드(11-25, 관리자만 — 개발 콘솔 자체가 관리자만): 비우면 상한 없음.
// 환경 변수 CHRONOS_LLM_DAILY_USD(또는 chronos --llm-daily-usd)로 정했으면 읽기만 한다(서버도 409 로 막는다).
import { useEffect, useState } from 'react';
import { ApiError } from '../../shared/api';
import { devApi, type LlmCap } from './devApi';

const usd = (n: number) => `$${n.toFixed(2)}`;

/** 「오늘 $a / 상한 $b」, 상한이 없으면 「오늘 $a / 상한 없음」. 사용량 탭도 쓴다. */
export const capLine = (c: LlmCap) => `오늘 ${usd(c.spent_today_usd)} / ${c.cap_usd === null ? '상한 없음' : `상한 ${usd(c.cap_usd)}`}`;

const asText = (c: LlmCap) => (c.cap_usd === null ? '' : String(c.cap_usd));

export default function LlmCapPanel() {
  const [cap, setCap] = useState<LlmCap | null>(null);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    devApi.getLlmCap().then(
      (c) => {
        if (!live) return;
        setCap(c);
        setDraft(asText(c));
      },
      () => live && setError('하루 LLM 비용 상한을 읽지 못했습니다.'),
    );
    return () => {
      live = false;
    };
  }, []);

  const value = draft.trim() === '' ? null : Number(draft);
  const wrong = value !== null && !(Number.isFinite(value) && value > 0) ? '0보다 큰 금액(USD)을 넣거나, 비워서 상한을 없애세요.' : null;
  const dirty = cap !== null && draft !== asText(cap);

  async function save() {
    setBusy(true);
    setNotice(null);
    setError(null);
    try {
      const next = await devApi.saveLlmCap(value);
      setCap(next);
      setDraft(asText(next));
      setNotice('상한을 저장했습니다.');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '상한을 저장하지 못했습니다.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="dc-cfg-card" aria-label="하루 LLM 비용 상한">
      <div className="dc-cfg-head">
        <div>
          <h3>하루 LLM 비용 상한</h3>
          <p className="dc-muted">
            오늘(서울 날짜, 자정에 다시 셉니다) Liner 호출에 기록된 비용(가격표 추정 포함)이 상한에 닿으면 내일까지 채팅·임베딩·검색·그림
            호출을 보내지 않습니다. 비워 두면 상한 없음. 이미 떠난 호출은 막지 않아 마지막 한 번은 상한을 조금 넘을 수 있습니다.
          </p>
        </div>
        {cap && !cap.fixed_by_env && (
          <div className="dc-cfg-actions">
            <button type="button" className="dc-btn dc-btn-primary" disabled={busy || !dirty || wrong !== null} onClick={() => void save()}>
              {busy ? '저장 중…' : '상한 저장'}
            </button>
          </div>
        )}
      </div>
      <div className="dc-cfg-grid">
        <label className="dc-cfg-field">
          <span>하루 LLM 비용 상한(USD)</span>
          <input type="number" min={0} step={0.5} inputMode="decimal" aria-label="하루 LLM 비용 상한(USD)" placeholder="상한 없음"
            value={draft} disabled={!cap || busy || cap.fixed_by_env}
            onChange={(e) => {
              setDraft(e.target.value);
              setNotice(null);
              setError(null);
            }} />
        </label>
      </div>
      {cap && <p className="dc-u-search">{capLine(cap)}</p>}
      {cap?.fixed_by_env && <p className="dc-muted">환경 변수 CHRONOS_LLM_DAILY_USD 로 정해져 있어 여기서 바꿀 수 없습니다.</p>}
      {(wrong || notice || error) && (
        <div className="dc-cfg-toggles">
          {wrong && <span className="dc-error" role="alert">{wrong}</span>}
          {notice && <span className="dc-ok" role="status">{notice}</span>}
          {error && <span className="dc-error" role="alert">{error}</span>}
        </div>
      )}
    </section>
  );
}
