// AX 인재전쟁(약속선) 스타일 하네스 카탈로그, 실시간 에이전트 실행 설정 및 [차단 시험] 탭.
import { useState } from 'react';
import { ApiError } from '../../shared/api';
import { devApi, type AgentConfig, type ApprovalMode, type CatalogOut } from './devApi';
import HarnessRules from './HarnessRules';

const DEFAULT_AGENT_CONFIG: AgentConfig = {
  approval_mode: 'important',
  max_steps: 12,
  max_check_retries: 5,
  tool_output_limit: 4000,
  history_limit: 30,
  enable_skill_match: true,
  enable_self_reflection: true,
};

function AgentConfigPanel({ initial, onSaved }: { initial?: AgentConfig; onSaved(): void }) {
  const [saved, setSaved] = useState<AgentConfig>(initial ?? DEFAULT_AGENT_CONFIG);
  const [draft, setDraft] = useState<AgentConfig>(initial ?? DEFAULT_AGENT_CONFIG);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const dirty = JSON.stringify(draft) !== JSON.stringify(saved);
  const isDefault = JSON.stringify(draft) === JSON.stringify(DEFAULT_AGENT_CONFIG);

  const clampNum = (v: string, min: number, max: number, fallback: number) => {
    const n = Number(v);
    if (!Number.isFinite(n)) return fallback;
    return Math.max(min, Math.min(max, Math.round(n)));
  };

  async function save() {
    setBusy(true);
    setNotice(null);
    setError(null);
    try {
      const next = await devApi.saveAgentConfig(draft);
      setSaved(next);
      setDraft(next);
      setNotice('에이전트 설정을 저장했습니다.');
      onSaved();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '설정을 저장하지 못했습니다.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="dc-cfg-card" aria-label="에이전트 · 하네스 실행 설정">
      <div className="dc-cfg-head">
        <div>
          <h3>에이전트 · 하네스 실행 설정</h3>
          <p className="dc-muted">
            저장 즉시 다음 대화 턴부터 에이전트 루프(<code>app/agent/loop.py</code>)와 개발 콘솔 추적 한도에 적용됩니다.
          </p>
        </div>
        <div className="dc-cfg-actions">
          <button
            type="button"
            className="dc-btn"
            disabled={busy || isDefault}
            onClick={() => {
              setDraft(DEFAULT_AGENT_CONFIG);
              setNotice(null);
              setError(null);
            }}
          >
            기본값으로
          </button>
          <button type="button" className="dc-btn dc-btn-primary" disabled={busy || !dirty} onClick={() => void save()}>
            {busy ? '저장 중…' : '에이전트 설정 저장'}
          </button>
        </div>
      </div>

      <div className="dc-cfg-grid">
        <label className="dc-cfg-field">
          <span>승인 수준</span>
          <select
            aria-label="승인 수준"
            value={draft.approval_mode}
            disabled={busy}
            onChange={(e) => {
              setDraft((d) => ({ ...d, approval_mode: e.target.value as ApprovalMode }));
              setNotice(null);
            }}
          >
            <option value="all">모두 승인 (변경마다)</option>
            <option value="important">중요한 것만 (권장)</option>
            <option value="auto">자동 (위반 없을 때)</option>
          </select>
        </label>

        <label className="dc-cfg-field">
          <span>ReAct 루프 단계 한도 (바퀴)</span>
          <input
            type="number"
            aria-label="ReAct 루프 단계 한도"
            min={4}
            max={24}
            value={draft.max_steps}
            disabled={busy}
            onChange={(e) => {
              setDraft((d) => ({ ...d, max_steps: clampNum(e.target.value, 4, 24, d.max_steps) }));
              setNotice(null);
            }}
          />
        </label>

        <label className="dc-cfg-field">
          <span>하네스 재시도 한도 (회)</span>
          <input
            type="number"
            aria-label="하네스 재시도 한도"
            min={1}
            max={10}
            value={draft.max_check_retries}
            disabled={busy}
            onChange={(e) => {
              setDraft((d) => ({ ...d, max_check_retries: clampNum(e.target.value, 1, 10, d.max_check_retries) }));
              setNotice(null);
            }}
          />
        </label>

        <label className="dc-cfg-field">
          <span>도구 결과 길이 상한 (자)</span>
          <input
            type="number"
            aria-label="도구 결과 길이 상한"
            min={1000}
            max={16000}
            step={500}
            value={draft.tool_output_limit}
            disabled={busy}
            onChange={(e) => {
              setDraft((d) => ({ ...d, tool_output_limit: clampNum(e.target.value, 1000, 16000, d.tool_output_limit) }));
              setNotice(null);
            }}
          />
        </label>

        <label className="dc-cfg-field">
          <span>대화 컨텍스트 유지 수 (개)</span>
          <input
            type="number"
            aria-label="대화 컨텍스트 유지 수"
            min={6}
            max={60}
            step={2}
            value={draft.history_limit}
            disabled={busy}
            onChange={(e) => {
              setDraft((d) => ({ ...d, history_limit: clampNum(e.target.value, 6, 60, d.history_limit) }));
              setNotice(null);
            }}
          />
        </label>
      </div>

      <div className="dc-cfg-toggles">
        <label className="dc-cfg-check">
          <input
            type="checkbox"
            checked={draft.enable_skill_match}
            disabled={busy}
            onChange={(e) => {
              setDraft((d) => ({ ...d, enable_skill_match: e.target.checked }));
              setNotice(null);
            }}
          />
          <span>베테랑 스킬 자동 매칭</span>
        </label>
        <label className="dc-cfg-check">
          <input
            type="checkbox"
            checked={draft.enable_self_reflection}
            disabled={busy}
            onChange={(e) => {
              setDraft((d) => ({ ...d, enable_self_reflection: e.target.checked }));
              setNotice(null);
            }}
          />
          <span>도구 실패 시 자가 점검(Reflection) 자동 주입</span>
        </label>
        {notice && <span className="dc-ok" role="status">{notice}</span>}
        {error && <span className="dc-error" role="alert">{error}</span>}
      </div>
    </section>
  );
}

export default function HarnessTab({ catalog, onSaved }: { catalog: CatalogOut; onSaved?: () => void }) {
  return (
    <div className="dc-scroll dc-cat-wrap">
      <div className="dc-cat-header">
        <h2 className="dc-cat-h2">하네스 · 에이전트 설정 (Harness Engineering)</h2>
        <p className="dc-muted">
          어기면 일정 무결성·자원 한도·권한이 틀어지는 규칙을 코드로 강제하는 지점과 실행 한도를 직접 조정합니다. 구현 {catalog.harness.length}개.
          「차단 시험」을 누르면 임시 상태에서 규칙을 일부러 어겨 보고 하네스가 모델에 돌려주는 차단·자가점검(reflection) JSON을 그대로 보여 줍니다.
        </p>
      </div>
      <AgentConfigPanel initial={catalog.agent_config} onSaved={() => onSaved?.()} />
      <div className="dc-note">
        <b>원천 연동</b> — 이 화면의 검사 위치·반려 문구·세션 통과/차단 수는 실제 실행 코드(<code>app/harness/checks.py</code>, <code>app/core/cpm.py</code>, <code>app/agent/loop.py</code>)와 워크플로우 실행 기록(DB)에서 직접 집계·실행합니다.
      </div>
      <div className="dc-principles-box">
        <b>원칙</b>
        <ul>
          {catalog.principles.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      </div>
      <HarnessRules rules={catalog.harness} outreach={catalog.outreach_grid} />
    </div>
  );
}
