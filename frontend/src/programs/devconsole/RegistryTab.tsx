// 도구(Tools) & 베테랑 스킬(Skills) 등록부 탭: 통계 · 활성 토글 · 스킬 삭제.
// 도구는 한글 이름(shared/toolLabels — 대화 칩·리본과 같은 표), 영역 묶음 + 찾기, 쓰기 여부, 부를 수 있는 역할.
// 연락(Task 109): 대화 에이전트 연락 도구(역할 설명) + 연락 하네스 도구 12개(등록부 밖 — 받는 등급·매체, 끄기 없음).
import { useState } from 'react';
import { ApiError } from '../../shared/api';
import { toolLabel } from '../../shared/toolLabels';
import Badge from '../../shared/ui/Badge';
import { classOf } from './outreachText';
import { devApi, type CatalogOut, type SkillRegistryItem, type ToolRegistryItem } from './devApi';

const CATS = ['전체', '하네스 점검', '승인 상신', '조회·계산·조작', '연락 하네스 도구', '비활성'] as const;
/** 도구 이름 앞부분(영역.동작 의 영역)으로 묶는다. 표에 없는 영역은 「기타」. */
const AREAS: [string, string[]][] = [
  ['일정·공정', ['schedule', 'calc', 'conditions', 'progress']],
  ['점검·생성', ['harness', 'generate']],
  ['지연·만회·시나리오', ['delay', 'shorten', 'scenario']],
  ['승인·규칙 상신', ['out', 'rules']],
  ['질문지', ['ask']],
  ['자료함', ['files']],
  ['근거·정보 API', ['evidence', 'info']],
  ['현장', ['field']],
  ['보고서·그림', ['report', 'visual']],
  ['화면', ['ui']],
  ['연락', ['contacts', 'notify']],
  ['연락 하네스', ['outreach']],
];
const areaOf = (name: string) => AREAS.find(([, prefixes]) => prefixes.includes(name.split('.')[0]))?.[0] ?? '기타';
const AREA_ORDER = [...AREAS.map(([a]) => a), '기타'];
const ROLE_NAMES: Record<string, string> = { admin: '관리자', user: '사용자', field: '현장 관리자' };

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

/** 읽기 전용 · 쓰기 · 상신. 예전 서버(mutates 없음)는 「—」. */
function WriteKind({ t }: { t: ToolRegistryItem }) {
  if (t.category === '승인 상신') return <Badge tone="danger">상신</Badge>;
  if (t.mutates === undefined) return <span className="dc-muted">—</span>;
  return t.mutates ? <Badge tone="warning">쓰기</Badge> : <Badge tone="neutral">읽기 전용</Badge>;
}

/** 연락 하네스 도구의 매체: 문자·통화 / 통화만. */
const mediaOf = (media: string[]) => (media.includes('sms') ? (media.includes('call') ? '문자·통화' : '문자만') : '통화만');

function Roles({ t }: { t: ToolRegistryItem }) {
  const { roles, role_note: note, classes, media } = t;
  if (note) {
    return (
      <>
        <span>{note}</span>
        {media && <span className="dc-tag is-info" title="이 도구를 받는 매체">{mediaOf(media)}</span>}
        {classes && (
          <span className="dc-tool-classes" title="이 도구를 받는 발신자 등급(toolsets.for_class)">
            {`등급: ${classes.map(classOf).join(' · ')}`}
          </span>
        )}
      </>
    );
  }
  const limited = t.field_limited === true;
  if (!roles) return <span className="dc-muted">—</span>;
  return (
    <>
      <span>{roles.map((r) => ROLE_NAMES[r] ?? r).join(' · ')}</span>
      {!roles.includes('field') && <span className="dc-tag is-warn" title="도구가 ctx.require_editor() 로 막습니다.">현장 관리자 거절</span>}
      {limited && (
        <span className="dc-tag is-warn" title="도구가 어떤 인자에서만 ctx.require_editor() 로 막습니다(예: 새 일정 질문지).">
          현장 관리자 일부 거절
        </span>
      )}
    </>
  );
}

interface ToolRowProps {
  t: ToolRegistryItem;
  expanded: boolean;
  busy: boolean;
  onToggle(name: string, enabled: boolean): void;
  onExpand(name: string | null): void;
}

function ToolRow({ t, expanded, busy, onToggle, onExpand }: ToolRowProps) {
  const enabled = t.enabled !== false;
  const tone = t.category === '하네스 점검' ? 'warning' : t.category === '승인 상신' ? 'danger' : t.category === '연락 하네스 도구' ? 'neutral' : 'info';
  return (
    <tr className="dc-cat-row">
      <td className="dc-tool-name">
        <b>{toolLabel(t.name)}</b>
        <code>{t.name}</code>
      </td>
      <td>
        {t.toggle === false ? (
          <span className="dc-muted dc-nowrap" title="등록부 도구가 아니라 여기서 끄지 않습니다 — 등급표(toolsets)가 정합니다.">끄기 없음</span>
        ) : (
          <button
            type="button"
            className={`dc-tool-toggle${enabled ? ' is-on' : ''}`}
            aria-pressed={enabled}
            aria-label={`${t.name} ${enabled ? '비활성화' : '활성화'}`}
            disabled={busy}
            onClick={() => onToggle(t.name, !enabled)}
          >
            {enabled ? '활성' : '비활성'}
          </button>
        )}
      </td>
      <td><Badge tone={tone}>{t.category}</Badge></td>
      <td><WriteKind t={t} /></td>
      <td className="dc-tool-roles"><Roles t={t} /></td>
      <td>{t.program ? <code>{t.program}</code> : <span className="dc-muted">{t.toggle === false ? '—' : '공통'}</span>}</td>
      <td>
        <div>{t.description}</div>
        <div className="dc-tool-meta">
          {t.toggle === false ? (
            <span>호출 기록은 실행 추적의 「연락」에서 봅니다</span>
          ) : (
            <>
              <span>{`호출 ${t.calls ?? 0}회 · 실패 ${t.failed ?? 0}건`}</span>
              {t.avg_ms !== null && t.avg_ms !== undefined && <span>{` · 평균 ${t.avg_ms}ms`}</span>}
            </>
          )}
        </div>
        <button type="button" className="dc-link" onClick={() => onExpand(expanded ? null : t.name)}>
          {`${expanded ? '▼' : '▶'} JSON 스키마 (${t.llm_name})`}
        </button>
        {expanded && <pre className="dc-code-block">{JSON.stringify(t.schema, null, 2)}</pre>}
      </td>
    </tr>
  );
}

const matches = (t: ToolRegistryItem, q: string) => !q || [t.name, toolLabel(t.name), t.description].some((s) => s.toLowerCase().includes(q));

function ToolsTable({ tools, busyTool, onToggle }: { tools: ToolRegistryItem[]; busyTool: string | null; onToggle(name: string, enabled: boolean): void }) {
  const [cat, setCat] = useState<string>('전체');
  const [query, setQuery] = useState('');
  const [openTool, setOpenTool] = useState<string | null>(null);
  const q = query.trim().toLowerCase();
  const inCat = (t: ToolRegistryItem) => cat === '전체' || (cat === '비활성' ? t.enabled === false : t.category === cat);
  const shown = tools.filter((t) => inCat(t) && matches(t, q));
  return (
    <>
      <div className="dc-harness-tools">
        <div className="dc-chip-bar" role="group" aria-label="도구 분류 필터">
          {CATS.map((c) => (
            <button key={c} type="button" className={`dc-mode-btn${cat === c ? ' is-on' : ''}`} onClick={() => setCat(c)}>
              {c}
            </button>
          ))}
        </div>
        <input type="search" className="dc-search" aria-label="도구 찾기" placeholder="한글 이름 · 도구 id · 설명으로 찾기" value={query} onChange={(e) => setQuery(e.target.value)} />
      </div>
      {shown.length === 0 ? (
        <p className="dc-empty">찾는 도구가 없습니다.</p>
      ) : (
        <table className="dc-cat-table" aria-label="등록된 도구 목록">
          <thead>
            <tr>
              <th>도구</th>
              <th>상태</th>
              <th>구분</th>
              <th>쓰기</th>
              <th>부를 수 있는 역할</th>
              <th>연결 프로그램</th>
              <th>설명 · 통계 · 입력 JSON 스키마</th>
            </tr>
          </thead>
          {AREA_ORDER.filter((a) => shown.some((t) => areaOf(t.name) === a)).map((a) => (
            <tbody key={a} aria-label={`${a} 도구`}>
              <tr className="dc-cat-group">
                <th colSpan={7} scope="rowgroup">{`${a} · ${shown.filter((t) => areaOf(t.name) === a).length}개`}</th>
              </tr>
              {shown
                .filter((t) => areaOf(t.name) === a)
                .map((t) => (
                  <ToolRow key={t.name} t={t} expanded={openTool === t.name} busy={busyTool === t.name} onToggle={onToggle} onExpand={setOpenTool} />
                ))}
            </tbody>
          ))}
        </table>
      )}
    </>
  );
}

export default function RegistryTab({ catalog, onChanged }: { catalog: CatalogOut; onChanged?: () => void }) {
  const { tools, skills } = catalog.registry;
  const [busyTool, setBusyTool] = useState<string | null>(null);
  const [busySkill, setBusySkill] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

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
          역할 칸은 서버가 막는 그 줄(도구의 <code>ctx.require_editor()</code>)로 정합니다.
        </p>
      </div>
      <ToolsTable tools={tools} busyTool={busyTool} onToggle={(name, on) => void toggleTool(name, on)} />
    </div>
  );
}
