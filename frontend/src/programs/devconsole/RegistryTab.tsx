// 도구(Tools) & 베테랑 스킬(Skills) 등록부 탭.
import { useState } from 'react';
import Badge from '../../shared/ui/Badge';
import type { CatalogOut, SkillRegistryItem } from './devApi';

const CATS = ['전체', '하네스 점검', '승인 상신', '조회·계산·조작'] as const;

function SkillsTable({ skills }: { skills: SkillRegistryItem[] }) {
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
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function RegistryTab({ catalog }: { catalog: CatalogOut }) {
  const { tools, skills } = catalog.registry;
  const [cat, setCat] = useState<string>('전체');
  const [openTool, setOpenTool] = useState<string | null>(null);
  const shown = cat === '전체' ? tools : tools.filter((t) => t.category === cat);

  return (
    <div className="dc-scroll dc-cat-wrap">
      <div className="dc-cat-header">
        <h2 className="dc-cat-h2">{`저장된 베테랑 스킬 (${skills.length}개)`}</h2>
        <p className="dc-muted">
          워크플로우 실행을 스킬로 저장하면 다음 턴의 「스킬 찾기」 단계에서 사용자 요청과 트리거 키워드를 대조해 검증된 도구 순서를 자동 주입합니다.
        </p>
      </div>
      <SkillsTable skills={skills} />

      <div className="dc-cat-header">
        <h2 className="dc-cat-h2">{`에이전트 도구 등록부 (${tools.length}개)`}</h2>
        <p className="dc-muted">
          <code>app/tools/registry.py</code>에 등록되어 LLM에 전달되는 실제 도구 정의와 Pydantic JSON 스키마입니다.
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
            <th>구분</th>
            <th>연결 프로그램</th>
            <th>설명 · 입력 JSON 스키마</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((t) => {
            const expanded = openTool === t.name;
            const tone = t.category === '하네스 점검' ? 'warning' : t.category === '승인 상신' ? 'danger' : 'info';
            return (
              <tr key={t.name} className="dc-cat-row">
                <td><code><b>{t.name}</b></code></td>
                <td><Badge tone={tone}>{t.category}</Badge></td>
                <td>{t.program ? <code>{t.program}</code> : <span className="dc-muted">공통</span>}</td>
                <td>
                  <div>{t.description}</div>
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
