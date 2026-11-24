// 사람 양식의 두 칸(11-24 PM): 관리자 등급과 참여 프로젝트.
// - 관리자 등급: 협력사 담당(기본 — 자기 협력사·공종 일정만) / 관리자 등급(등록된 프로젝트의 모든 협력사 일정). 관리자만 바꾼다 —
//   다른 사용자에게는 잠긴 채 보인다(서버도 403 admin_only_level). 관리자 등급으로 올릴 때 양식이 확인을 묻는다(PersonForm).
// - 참여 프로젝트: 관리할 수 있는 프로젝트마다 체크. 켜면 그 프로젝트의 협력사를 골라(없으면 새로 만들어) [등록], 끄면 그 프로젝트의
//   연락처를 숨긴다(연락 기록은 남음). 등록·빼기는 바로 저장된다. 이름·번호·성별·언어·음성·채널·수신 거부·등급은 모든 프로젝트에
//   함께 저장되고, 협력사·담당·근무시간·메모는 프로젝트마다 따로다. 그 프로젝트에 같은 번호가 이미 있으면 「같은 사람으로 연결」.
import { useEffect, useState } from 'react';
import { ApiError } from '../../shared/api';
import Button from '../../shared/ui/Button';
import {
  addProject, getBook, getProjects, postCompany, removeProject,
  type AccessLevel, type Company, type PersonDetail, type ProjectChoice,
} from './contactsApi';

/** 관리자 등급으로 올릴 때의 확인 — 등급은 참여 프로젝트 모두에 함께 저장되므로 그 수를 말한다. */
export const levelConfirm = (projects: number) =>
  `관리자 등급은 이 사람이 등록된 프로젝트의 모든 협력사 일정을 전화·문자로 들을 수 있게 합니다. 참여 프로젝트 ${projects}곳 모두에 적용됩니다. 계속할까요?`;
const SEARCH_FROM = 7; // 프로젝트가 이보다 많으면 찾기 칸
const NEW_COMPANY = 'new';

export function LevelField({ value, onChange, isAdmin }: { value: AccessLevel; onChange: (v: AccessLevel) => void; isAdmin: boolean }) {
  const options = [
    ['trade', '협력사 담당'],
    ['manager', '관리자 등급'],
  ] as const;
  return (
    <fieldset className="ct-fieldset ct-field is-wide" aria-label="관리자 등급">
      <legend className="ct-label">관리자 등급</legend>
      <div className="ct-checks">
        {options.map(([key, label]) => (
          <label key={key} className="ct-check">
            <input type="radio" name="ct-level" checked={value === key} disabled={!isAdmin} onChange={() => onChange(key)} />
            {label}
          </label>
        ))}
      </div>
      <p className="ct-hint">
        {value === 'manager'
          ? '원청 현장소장·감리처럼 여러 협력사를 관리하는 사람 — 등록된 프로젝트의 모든 협력사 일정을 전화·문자로 들을 수 있습니다(다른 프로젝트는 아님).'
          : '자기 협력사·공종의 일정만 전화·문자로 들을 수 있습니다.'}
      </p>
      {!isAdmin && <p className="ct-hint">관리자 등급은 관리자만 바꿀 수 있습니다.</p>}
    </fieldset>
  );
}

interface Pick {
  company: string;
  newName: string;
  companies: Company[] | null;
  error: string | null;
  /** 그 프로젝트에 같은 번호가 이미 있음 → 「같은 사람으로 연결」할 연락처 */
  sameAs: number | null;
}

const message = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback);

/** 참여 프로젝트. 새 사람이면(아직 줄이 없음) 저장한 뒤에 쓸 수 있다는 한 줄만. */
export function ProjectsField({ scheduleId, detail, onChanged }: { scheduleId: number; detail: PersonDetail | null; onChanged: (d: PersonDetail) => void }) {
  if (!detail)
    return (
      <div className="ct-field is-wide">
        <span className="ct-label">참여 프로젝트</span>
        <p className="ct-hint">저장한 뒤 다른 프로젝트에도 같은 사람으로 등록할 수 있습니다.</p>
      </div>
    );
  return <Projects scheduleId={scheduleId} detail={detail} onChanged={onChanged} />;
}

/** 참여 프로젝트의 상태와 동작(목록 읽기·켜고 끄기·등록·같은 사람으로 연결·빼기). */
function useProjects(scheduleId: number, detail: PersonDetail, onChanged: (d: PersonDetail) => void) {
  const [choices, setChoices] = useState<ProjectChoice[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [picks, setPicks] = useState<Record<number, Pick>>({});
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState('');

  useEffect(() => {
    let live = true;
    getProjects(scheduleId, detail.id).then(
      (c) => live && setChoices(c),
      (e: unknown) => live && setError(message(e, '참여 프로젝트를 읽을 수 없습니다.')),
    );
    return () => {
      live = false;
    };
  }, [scheduleId, detail.id]);

  const setPick = (sid: number, over: Partial<Pick>) => setPicks((p) => ({ ...p, [sid]: { ...p[sid], ...over } }));
  const done = (d: PersonDetail, sid: number) => {
    setPicks((p) => {
      const n = { ...p };
      delete n[sid];
      return n;
    });
    onChanged(d);
    return getProjects(scheduleId, detail.id).then(setChoices, () => undefined);
  };

  const open = (sid: number) => {
    setPicks((p) => ({ ...p, [sid]: { company: '', newName: '', companies: null, error: null, sameAs: null } }));
    getBook(sid, false).then(
      (b) => {
        const shown = b.companies.filter((c) => !c.hidden);
        setPick(sid, { companies: shown, company: shown[0] ? String(shown[0].id) : NEW_COMPANY });
      },
      (e: unknown) => setPick(sid, { companies: [], company: NEW_COMPANY, error: message(e, '그 프로젝트의 협력사를 읽을 수 없습니다.') }),
    );
  };
  const close = (sid: number) =>
    setPicks((p) => {
      const n = { ...p };
      delete n[sid];
      return n;
    });

  const run = async (sid: number, work: () => Promise<PersonDetail>) => {
    setBusy(true);
    setError(null);
    try {
      await done(await work(), sid);
    } catch (e) {
      if (e instanceof ApiError && e.code === 'same_number_there') {
        setPick(sid, { error: e.message, sameAs: (e.detail as { contact_id?: number } | null)?.contact_id ?? null });
      } else if (picks[sid]) setPick(sid, { error: message(e, '등록할 수 없습니다.') });
      else setError(message(e, '바꿀 수 없습니다.'));
    }
    setBusy(false);
  };

  const register = (sid: number) => {
    const p = picks[sid];
    if (!p) return;
    if (p.company === NEW_COMPANY && !p.newName.trim()) return setPick(sid, { error: '새 협력사 이름을 넣어 주세요.' });
    void run(sid, async () => {
      const company = p.company === NEW_COMPANY ? (await postCompany(sid, { name: p.newName.trim() })).id : Number(p.company);
      return addProject(scheduleId, detail.id, { schedule_id: sid, company_id: company });
    });
  };
  const linkSame = (sid: number, contactId: number) =>
    void run(sid, () => addProject(scheduleId, detail.id, { schedule_id: sid, link_contact_id: contactId }));
  const remove = (sid: number) => void run(sid, () => removeProject(scheduleId, detail.id, sid));
  return { choices, error, picks, busy, query, setQuery, setPick, open, close, register, linkSame, remove };
}

function Projects({ scheduleId, detail, onChanged }: { scheduleId: number; detail: PersonDetail; onChanged: (d: PersonDetail) => void }) {
  const { choices, error, picks, busy, query, setQuery, setPick, open, close, register, linkSame, remove } = useProjects(scheduleId, detail, onChanged);
  const q = query.trim().toLowerCase();
  const list = (choices ?? []).filter((c) => !q || c.current || c.linked || c.name.toLowerCase().includes(q));
  const linked = (choices ?? []).filter((c) => c.linked).length;

  return (
    <fieldset className="ct-fieldset ct-field is-wide ct-projects" aria-label="참여 프로젝트">
      <legend className="ct-label">{`참여 프로젝트${choices ? ` · ${linked}곳` : ''}`}</legend>
      {choices && choices.length >= SEARCH_FROM && (
        <input type="search" className="ct-input" aria-label="프로젝트 찾기" placeholder="프로젝트 찾기" value={query} onChange={(e) => setQuery(e.target.value)} />
      )}
      {!choices && !error && <p className="ct-muted">읽는 중…</p>}
      <ul className="ct-proj-list">
        {list.map((c) => (
          <li key={c.schedule_id} className="ct-proj">
            <label className="ct-check ct-proj-row">
              <input
                type="checkbox"
                checked={c.linked || picks[c.schedule_id] !== undefined}
                disabled={c.current || busy}
                onChange={(e) => (e.target.checked ? open(c.schedule_id) : c.linked ? remove(c.schedule_id) : close(c.schedule_id))}
              />
              <span className="ct-ellipsis ct-proj-name">{c.name}</span>
              {c.current && <span className="ct-tag">지금 프로젝트</span>}
              {c.linked && c.company_name && <span className="ct-proj-co ct-ellipsis">{c.company_name}</span>}
            </label>
            {picks[c.schedule_id] && (
              <PickCompany pick={picks[c.schedule_id]} busy={busy} onChange={(over) => setPick(c.schedule_id, over)} onRegister={() => register(c.schedule_id)} onLink={(id) => linkSame(c.schedule_id, id)} onCancel={() => close(c.schedule_id)} />
            )}
          </li>
        ))}
      </ul>
      <p className="ct-hint">등록·빼기는 바로 저장됩니다. 빼면 그 프로젝트의 연락처를 숨깁니다(연락 기록은 남습니다).</p>
      <p className="ct-hint">이름·번호·성별·언어·음성·받을 수 있는 것·수신 거부·관리자 등급은 모든 참여 프로젝트에 함께 저장되고, 협력사·담당·근무시간·메모는 프로젝트마다 따로입니다.</p>
      {error && (
        <p className="ct-error" role="alert">
          {error}
        </p>
      )}
    </fieldset>
  );
}

interface PickProps {
  pick: Pick;
  busy: boolean;
  onChange: (over: Partial<Pick>) => void;
  onRegister: () => void;
  onLink: (contactId: number) => void;
  onCancel: () => void;
}

/** 그 프로젝트의 협력사 고르기(없으면 새 협력사 이름) + [등록]. 같은 번호가 있으면 [같은 사람으로 연결]. */
function PickCompany({ pick, busy, onChange, onRegister, onLink, onCancel }: PickProps) {
  if (!pick.companies) return <p className="ct-muted ct-proj-pick">협력사를 읽는 중…</p>;
  return (
    <div className="ct-proj-pick">
      <label className="ct-fld-label">
        <span className="ct-label">그 프로젝트의 협력사</span>
        <select className="ct-input" value={pick.company} onChange={(e) => onChange({ company: e.target.value, error: null, sameAs: null })}>
          {pick.companies.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
          <option value={NEW_COMPANY}>+ 새 협력사</option>
        </select>
      </label>
      {pick.company === NEW_COMPANY && (
        <label className="ct-fld-label">
          <span className="ct-label">새 협력사 이름</span>
          <input className="ct-input" value={pick.newName} maxLength={100} onChange={(e) => onChange({ newName: e.target.value, error: null })} />
        </label>
      )}
      {pick.error && (
        <p className="ct-error" role="alert">
          {pick.error}
        </p>
      )}
      <div className="ct-actions">
        {pick.sameAs !== null ? (
          <Button variant="primary" onClick={() => onLink(pick.sameAs as number)} disabled={busy}>
            같은 사람으로 연결
          </Button>
        ) : (
          <Button variant="primary" onClick={onRegister} disabled={busy}>
            등록
          </Button>
        )}
        <Button onClick={onCancel} disabled={busy}>
          취소
        </Button>
      </div>
    </div>
  );
}
