// 「프로젝트 관리」(11-24, PM 이 고른 시안): 왼쪽 프로젝트 목록(찾기), 오른쪽 이름·AI 가 부를 이름·현장 주소·한 줄 소개·발주처·시공사 [취소][저장].
// 에이전트는 통화·문자에서 「AI 가 부를 이름」을 쓰고(비우면 서버가 날짜·판 표시를 뗀 이름), 소개·주소·발주처는 참고 자료로 받는다.
// 저장은 바뀐 칸만 보낸다. 서버 거절(번호·보이지 않는 글자·길이)은 그 칸 아래에. 이름을 바꾸면 메뉴바 일정 목록도 다시 읽는다.
// 칸 나누기는 연락처(useNarrow)와 같은 규칙: 폰·좁은 창(720 이하)은 목록 → 자세히 한 화면씩(위 「‹ 프로젝트 목록」), 그 밖은 두 칸.
import { useEffect, useMemo, useRef, useState, type FormEvent, type RefObject } from 'react';
import { useCurrentSchedule } from '../../os/currentSchedule';
import type { ProgramProps } from '../../os/registry';
import { useSession } from '../../os/session';
import { useActiveDevice } from '../../os/useIsMobile';
import { useUiContext } from '../../os/uiContext';
import { useWindows } from '../../os/windowStore';
import { ApiError } from '../../shared/api';
import Button from '../../shared/ui/Button';
import Field from '../../shared/ui/Field';
import { FIELD_KEYS, LIMITS, listProjects, patchProject, type Project, type ProjectFields } from './projectsApi';
import './projects.css';

const NAME = '프로젝트 관리';
const NARROW_MAX = 720; // 연락처와 같은 폭

/** 한 화면씩 보일까: 폰이거나 창 몸의 폭이 NARROW_MAX 이하(재지 못했으면 — 시험 환경 — 두 칸). */
function useSingle(ref: RefObject<HTMLElement | null>): boolean {
  const device = useActiveDevice();
  const [width, setWidth] = useState<number | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[entries.length - 1]?.contentRect.width;
      if (w) setWidth(w);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return device === 'phone' || (width !== null && width <= NARROW_MAX);
}

type Problem = { message: string; field: string | null };

function fieldsOf(p: Project): ProjectFields {
  return { name: p.name, spoken_name: p.spoken_name, site_address: p.site_address, summary: p.summary, client_builder: p.client_builder };
}

function problemOf(e: unknown): Problem {
  if (!(e instanceof ApiError)) return { message: '요청을 처리할 수 없습니다.', field: null };
  const field = (e.detail as { field?: unknown } | null)?.field;
  return { message: e.message, field: typeof field === 'string' ? field : null };
}

function matches(p: Project, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return [p.name, p.spoken_name, p.spoken, p.summary, p.site_address, p.client_builder].some((v) => v.toLowerCase().includes(q));
}

function stamp(p: Project): string | null {
  if (!p.updated_at) return null;
  const at = new Date(p.updated_at);
  const day = `${at.getFullYear()}-${String(at.getMonth() + 1).padStart(2, '0')}-${String(at.getDate()).padStart(2, '0')}`;
  return `마지막 고침 ${day}${p.updated_by ? ` · ${p.updated_by}` : ''}`;
}

function ProjectList({ items, query, setQuery, selectedId, onPick }: {
  items: Project[];
  query: string;
  setQuery(q: string): void;
  selectedId: number | null;
  onPick(id: number): void;
}) {
  const shown = items.filter((p) => matches(p, query));
  return (
    <nav className="pj-side" aria-label="프로젝트 목록">
      <div className="pj-find">
        <input
          type="search"
          className="pj-input"
          aria-label="프로젝트 찾기"
          placeholder="이름·부를 이름·소개로 찾기"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <span className="pj-count">{shown.length === items.length ? `${items.length}개` : `${shown.length} / ${items.length}개`}</span>
      </div>
      <ul className="pj-list">
        {shown.map((p) => (
          <li key={p.id}>
            <button type="button" className="pj-item" aria-current={p.id === selectedId ? 'true' : undefined} onClick={() => onPick(p.id)}>
              <span className="pj-item-name" title={p.name}>{p.name}</span>
              <span className="pj-item-sub">AI: {p.spoken}</span>
              {p.same_name && (
                <span className="pj-chip" title={`「${p.same_as ?? ''}」와 이름이 같습니다`}>이름이 같은 프로젝트 — 부를 이름을 적어 주세요</span>
              )}
            </button>
          </li>
        ))}
        {shown.length === 0 && <li className="pj-muted pj-pad">{items.length === 0 ? '프로젝트가 없습니다.' : '찾는 프로젝트가 없습니다.'}</li>}
      </ul>
    </nav>
  );
}

function ProjectForm({ project, readOnly, onSaved, onBack }: {
  project: Project;
  readOnly: boolean;
  onSaved(p: Project): void;
  onBack?: () => void;
}) {
  const [draft, setDraft] = useState<ProjectFields>(() => fieldsOf(project));
  const [problem, setProblem] = useState<Problem | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const base = fieldsOf(project);
  const changed = FIELD_KEYS.filter((k) => draft[k] !== base[k]);

  const set = (key: keyof ProjectFields) => (value: string) => {
    setDraft((d) => ({ ...d, [key]: value }));
    setSaved(false);
  };
  const errorFor = (key: keyof ProjectFields) => (problem?.field === key ? problem.message : undefined);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (readOnly || changed.length === 0 || saving) return;
    setSaving(true);
    setProblem(null);
    try {
      const body = Object.fromEntries(changed.map((k) => [k, draft[k].trim()])) as Partial<ProjectFields>;
      const next = await patchProject(project.id, body);
      setDraft(fieldsOf(next));
      setSaved(true);
      onSaved(next);
    } catch (err) {
      setProblem(problemOf(err));
    } finally {
      setSaving(false);
    }
  }

  function cancel() {
    setDraft(fieldsOf(project));
    setProblem(null);
    setSaved(false);
  }

  const input = (key: keyof ProjectFields, label: string, hint?: string, placeholder?: string) => (
    <Field label={label} hint={hint} error={errorFor(key)}>
      <input
        className="pj-input"
        value={draft[key]}
        maxLength={LIMITS[key]}
        placeholder={placeholder}
        readOnly={readOnly}
        onChange={(e) => set(key)(e.target.value)}
      />
    </Field>
  );
  const when = stamp(project);

  return (
    <form className="pj-form" aria-label="프로젝트 정보" onSubmit={submit}>
      {onBack && (
        <button type="button" className="pj-back" onClick={onBack}>
          ‹ 프로젝트 목록
        </button>
      )}
      <div className="pj-head">
        <h2 className="pj-title" title={project.name}>{project.name}</h2>
        <p className="pj-muted">통화·문자에서 AI 가 부르는 이름: 「{project.spoken}」{when ? ` · ${when}` : ''}</p>
      </div>
      {input('name', '프로젝트 이름')}
      {input('spoken_name', 'AI 가 부를 이름 (통화·문자)', '짧게 — 예: 가람 물류센터. 비우면 프로젝트 이름에서 날짜·판 표시를 뗀 이름으로 부릅니다.', project.spoken_name ? undefined : project.spoken)}
      {project.same_name && (
        <p className="pj-warn" role="note">
          통화에서 「{project.same_as}」와 구별할 수 없습니다 — 다른 부를 이름을 적어 주세요(다른 프로젝트의 부를 이름과도, 날짜·판 표시를 뗀 이름과도 달라야 합니다).
        </p>
      )}
      {!draft.spoken_name.trim() && project.spoken.length > LIMITS.spoken_name && (
        <p className="pj-warn" role="note">부를 이름을 적어 주세요 — AI 가 이 긴 이름을 그대로 부릅니다</p>
      )}
      {input('site_address', '현장 주소 (선택)')}
      {input('summary', '한 줄 소개 — AI 가 참고', `상대가 물을 때 AI 가 참고합니다. ${draft.summary.length} / ${LIMITS.summary}자`)}
      {input('client_builder', '발주처·시공사 (선택)')}
      <p className="pj-muted">전화번호는 적지 않습니다 — AI 가 통화·문자에서 읽는 글입니다.</p>
      {problem && problem.field === null && (
        <p className="pj-error" role="alert">{problem.message}</p>
      )}
      {readOnly ? (
        <p className="pj-muted">현장 관리자는 볼 수만 있습니다.</p>
      ) : (
        <div className="pj-actions">
          {saved && changed.length === 0 && <span className="pj-saved" role="status">저장했습니다.</span>}
          <span className="pj-gap" />
          <Button onClick={cancel} disabled={changed.length === 0 || saving}>취소</Button>
          <Button type="submit" variant="primary" disabled={changed.length === 0 || saving}>
            {saving ? '저장 중…' : '저장'}
          </Button>
        </div>
      )}
    </form>
  );
}

export default function Projects({ windowId }: ProgramProps) {
  const role = useSession((s) => s.session?.user.role);
  const currentId = useCurrentSchedule((s) => s.current?.id ?? null);
  const [items, setItems] = useState<Project[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [picked, setPicked] = useState<number | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const single = useSingle(rootRef);

  useEffect(() => {
    let live = true;
    listProjects()
      .then((rows) => live && setItems(rows))
      .catch((e: unknown) => live && setError(problemOf(e).message));
    return () => {
      live = false;
    };
  }, []);

  // 두 칸이면 고른 것이 없을 때 지금 일정(없으면 첫 프로젝트)을 연다. 한 화면씩이면 목록부터.
  const fallback = useMemo(() => {
    if (single || !items || items.length === 0) return null;
    return items.some((p) => p.id === currentId) ? currentId : items[0].id;
  }, [single, items, currentId]);
  const selectedId = picked ?? fallback;
  const selected = items?.find((p) => p.id === selectedId) ?? null;

  useEffect(() => {
    useWindows.getState().setTitle(windowId, NAME);
  }, [windowId]);
  useEffect(() => {
    useUiContext.getState().publish(windowId, { program: 'projects', schedule_id: selectedId });
  }, [windowId, selectedId]);

  function onSaved(next: Project) {
    setItems((rows) => rows?.map((p) => (p.id === next.id ? next : p)) ?? rows);
    // 다른 프로젝트의 같은 이름 표시도 바뀌었을 수 있다 — 목록을 다시 읽는다(실패하면 지금 목록 그대로)
    listProjects().then(setItems).catch(() => undefined);
    const schedules = useCurrentSchedule.getState();
    if (schedules.current?.id === next.id && schedules.current.name !== next.name) schedules.setCurrent({ id: next.id, name: next.name });
    schedules.bumpReload(); // 메뉴바 일정 목록이 새 이름을 읽게
  }

  const showList = !single || selected === null;
  const showForm = selected !== null && (!single || picked !== null);
  return (
    <div ref={rootRef} className={`pj-root${single ? ' is-single' : ''}`}>
      {error && (
        <p className="pj-error pj-pad" role="alert">{error}</p>
      )}
      {!error && items === null && <p className="pj-muted pj-pad">불러오는 중…</p>}
      {items !== null && (
        <div className="pj-main">
          {showList && <ProjectList items={items} query={query} setQuery={setQuery} selectedId={selectedId} onPick={setPicked} />}
          {showForm && selected && (
            <ProjectForm
              key={selected.id}
              project={selected}
              readOnly={role === 'field'}
              onSaved={onSaved}
              onBack={single ? () => setPicked(null) : undefined}
            />
          )}
          {!single && !selected && <p className="pj-muted pj-pad">왼쪽에서 프로젝트를 고르세요.</p>}
        </div>
      )}
    </div>
  );
}
