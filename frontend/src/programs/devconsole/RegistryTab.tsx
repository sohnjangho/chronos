// 도구(Tools) & 베테랑 스킬(Skills) 등록부 탭: 통계 · 활성 토글 · 스킬 삭제.
import { useState } from 'react';
import { ApiError } from '../../shared/api';
import Badge from '../../shared/ui/Badge';
import { devApi, type CatalogOut, type SkillRegistryItem } from './devApi';

const CATS = ['전체', '하네스 점검', '승인 상신', '조회·계산·조작', '비활성'] as const;

function SkillsTable({
  skills,
  busyId,
  onDelete,
}: {
  skills: SkillRegistryItem[];
  busyId: number | null;
  onDelete(id: number): void;
}) {
  if (skills.length === 0) {
    return <p className="dc-empty">저장된 스킬이 없습니다. 워크플로우 창에서 완료된 실행을 [스킬로 저장]해 보세요.</p>;
  }
  return (
    <table className="dc-cat-table" aria-label="저장된 스킬 목록">
      <thead>
        <tr>
          <th>스킬 이름</th>
          <th>설명</th>
          <th>트리거 키워드</th>
          <th>검증된 도구 순서</th>
          <th>적용 횟수</th>
          <th>관리</th>
        </tr>
      </thead>
      <tbody>
        {skills.map((s) => (
          <tr key={s.id} className="dc-cat-row">
            <td><b>{s.name}</b></td>
            <td>{s.description}</td>
            <td>{s.triggers.map((k) => <span key={k} className="dc-tag">{k}</span>)}</td>
            <td><code>{s.steps.map((st) => st.tool).join(' → ')}</code></td>
            <td><Badge tone="success">{`${s.use_count}회`}</Badge></td>
            <td>
              <button
                type="button"
                className="dc-btn dc-skill-del"
                aria-label={`${s.name} 스킬 삭제`}
                disabled={busyId === s.id}
                onClick={() => onDelete(s.id)}
              >
                {busyId === s.id ? '삭제 중…' : '삭제'}
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function RegistryTab({ catalog, onChanged }: { catalog: CatalogOut; onChanged?: () => void }) {
  const { tools, skills } = catalog.registry;
  const [cat, setCat] = useState<string>('전체');
  const [openTool, setOpenTool] = useState<string | null>(null);
  const [busyTool, setBusyTool] = useState<string | null>(null);
  const [busySkill, setBusySkill] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const shown =
    cat === '전체'
      ? tools
      : cat === '비활성'
        ? tools.filter((t) => t.enabled === false)
        : tools.filter((t) => t.category === cat);

  async function toggleTool(name: string, nextEnabled: boolean) {
    setBusyTool(name);
    setError(null);
    try {
      await devApi.setToolEnabled(name, nextEnabled);
      onChanged?.();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '도구 상태를 바꾸지 못했습니다.');
    } finally {
      setBusyTool(null);
    }
  }

  async function deleteSkill(skillId: number) {
    setBusySkill(skillId);
    setError(null);
    try {
      await devApi.deleteSkill(skillId);
      onChanged?.();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '스킬을 삭제하지 못했습니다.');
    } finally {
      setBusySkill(null);
    }
  }

  return (
    <div className="dc-scroll dc-cat-wrap">
      {error && (
        <p className="dc-error" role="alert">
          {error}
        </p>
      )}
      <div className="dc-cat-header">
        <h2 className="dc-cat-h2">{`저장된 베테랑 스킬 (${skills.length}개)`}</h2>
        <p className="dc-muted">
          워크플로우 실행을 스킬로 저장하면 다음 턴의 「스킬 찾기」 단계에서 사용자 요청과 트리거 키워드를 대조해 검증된 도구 순서를 자동 주입합니다.
        </p>
      </div>
      <SkillsTable skills={skills} busyId={busySkill} onDelete={(id) => void deleteSkill(id)} />

      <div className="dc-cat-header">
        <h2 className="dc-cat-h2">{`에이전트 도구 등록부 (${tools.length}개)`}</h2>
        <p className="dc-muted">
          <code>app/tools/registry.py</code>에 등록되어 LLM에 전달되는 실제 도구 정의, 누적 실행 통계, 활성 여부 및 Pydantic JSON 스키마입니다.
        </p>
      </div>
      <div className="dc-chip-bar" role="group" aria-label="도구 분류 필터">
        {CATS.map((c) => (
          <button key={c} type="button" className={`dc-mode-btn${cat === c ? ' is-on' : ''}`} onClick={() => setCat(c)}>
            {c}
          </button>
        ))}
      </div>
      <table className="dc-cat-table" aria-label="등록된 도구 목록">
        <thead>
          <tr>
            <th>도구 이름</th>
            <th>상태</th>
            <th>구분</th>
            <th>연결 프로그램</th>
            <th>설명 · 통계 · 입력 JSON 스키마</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((t) => {
            const expanded = openTool === t.name;
            const enabled = t.enabled !== false;
            const calls = t.calls ?? 0;
            const failed = t.failed ?? 0;
            const tone = t.category === '하네스 점검' ? 'warning' : t.category === '승인 상신' ? 'danger' : 'info';
            return (
              <tr key={t.name} className="dc-cat-row">
                <td><code><b>{t.name}</b></code></td>
                <td>
                  <button
                    type="button"
                    className={`dc-tool-toggle${enabled ? ' is-on' : ''}`}
                    aria-pressed={enabled}
                    aria-label={`${t.name} ${enabled ? '비활성화' : '활성화'}`}
                    disabled={busyTool === t.name}
                    onClick={() => void toggleTool(t.name, !enabled)}
                  >
                    {enabled ? '활성' : '비활성'}
                  </button>
                </td>
                <td><Badge tone={tone}>{t.category}</Badge></td>
                <td>{t.program ? <code>{t.program}</code> : <span className="dc-muted">공통</span>}</td>
                <td>
                  <div>{t.description}</div>
                  <div className="dc-tool-meta">
                    <span>{`호출 ${calls}회 · 실패 ${failed}건`}</span>
                    {t.avg_ms !== null && t.avg_ms !== undefined && <span>{` · 평균 ${t.avg_ms}ms`}</span>}
                  </div>
                  <button type="button" className="dc-link" onClick={() => setOpenTool(expanded ? null : t.name)}>
                    {`${expanded ? '▼' : '▶'} JSON 스키마 (${t.llm_name})`}
                  </button>
                  {expanded && <pre className="dc-code-block">{JSON.stringify(t.schema, null, 2)}</pre>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
