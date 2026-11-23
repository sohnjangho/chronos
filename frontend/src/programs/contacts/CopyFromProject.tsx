// 다른 프로젝트에서 복사(Task 77, 시안 ⑤ — 관리자만). 프로젝트 고르기 → 그 주소록의 사람 고르기(협력사별·찾기) → [n명 복사해 오기].
// 이미 이 프로젝트에 있는 사람(already_here)은 고를 수 없다. 번호는 서버가 준 가린 꼴뿐. 결과는 서버의 셈(복사·건너뜀·거절)을 보인다.
import { useEffect, useRef, useState } from 'react';
import Button from '../../shared/ui/Button';
import { getCopySource, getCopySources, KIND_LABEL, postCopy, type CopyOut, type CopyPerson, type CopySource, type CopySourceDetail } from './contactsApi';
import XferDialog from './XferDialog';

const MAX = 500;
const message = (e: unknown) => (e instanceof Error ? e.message : '요청을 처리할 수 없습니다.');
type Company = CopySourceDetail['companies'][number];

const matches = (p: CopyPerson, c: Company, q: string) =>
  !q || p.name.toLowerCase().includes(q) || p.role_title.toLowerCase().includes(q) || c.name.toLowerCase().includes(q);

function Person({ p, on, onChange }: { p: CopyPerson; on: boolean; onChange: (on: boolean) => void }) {
  return (
    <li>
      <label className={`ct-xfer-person${p.already_here ? ' is-off' : ''}`}>
        <input type="checkbox" checked={on} disabled={p.already_here} onChange={(e) => onChange(e.target.checked)} />
        <span className="ct-xfer-who">
          <span className="ct-name ct-ellipsis" title={p.name}>{p.name}</span>
          <span className="ct-role ct-ellipsis" title={p.role_title}>{p.role_title || '담당 없음'}</span>
        </span>
        <span className="ct-xfer-tags">
          <span className="ct-num ct-muted">{p.phone_masked}</span>
          {p.phone_kind && p.phone_kind !== 'mobile' && <span className="ct-tag">{KIND_LABEL[p.phone_kind]}</span>}
          {p.do_not_contact && <span className="ct-tag is-bad">수신 거부</span>}
          {p.already_here && <span className="ct-tag">이미 있음</span>}
        </span>
      </label>
    </li>
  );
}

function Group({ c, people, chosen, setMany }: { c: Company; people: CopyPerson[]; chosen: Set<number>; setMany: (ids: number[], on: boolean) => void }) {
  const ids = people.filter((p) => !p.already_here).map((p) => p.id);
  const count = ids.filter((id) => chosen.has(id)).length;
  const all = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (all.current) all.current.indeterminate = count > 0 && count < ids.length;
  }, [count, ids.length]);
  return (
    <section role="group" aria-label={c.name} className="ct-group">
      <div className="ct-co ct-xfer-co">
        <label className="ct-check ct-xfer-all">
          <input ref={all} type="checkbox" aria-label={`${c.name} 모두 고르기`} checked={ids.length > 0 && count === ids.length} disabled={ids.length === 0} onChange={(e) => setMany(ids, e.target.checked)} />
          <span className="ct-co-name ct-ellipsis" title={c.name}>{c.name}</span>
          {c.trade && <span className="ct-co-trade ct-ellipsis">{c.trade}</span>}
        </label>
        <span className="ct-co-count ct-muted">{`${people.length}명`}</span>
      </div>
      <ul className="ct-people">
        {people.map((p) => (
          <Person key={p.id} p={p} on={chosen.has(p.id)} onChange={(on) => setMany([p.id], on)} />
        ))}
      </ul>
    </section>
  );
}

function useCopy(scheduleId: number, onDone: () => void) {
  const [sources, setSources] = useState<CopySource[] | null>(null);
  const [detail, setDetail] = useState<CopySourceDetail | null>(null);
  const [picked, setPicked] = useState<number | null>(null);
  const [chosen, setChosen] = useState<Set<number>>(() => new Set());
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<CopyOut | null>(null);
  const seq = useRef(0);
  useEffect(() => {
    const my = ++seq.current;
    getCopySources(scheduleId).then(
      (s) => my === seq.current && setSources(s),
      (e: unknown) => my === seq.current && setError(message(e)),
    );
    return () => void (seq.current += 1);
  }, [scheduleId]);
  return {
    sources, detail, picked, chosen, error, busy, result,
    pick(id: number | null) {
      const my = ++seq.current;
      setPicked(id);
      setDetail(null);
      setChosen(new Set());
      setError(null);
      if (id !== null)
        getCopySource(scheduleId, id).then(
          (d) => my === seq.current && setDetail(d),
          (e: unknown) => my === seq.current && setError(message(e)),
        );
    },
    setMany(ids: number[], on: boolean) {
      setChosen((s) => {
        const n = new Set(s);
        ids.forEach((id) => (on ? n.add(id) : n.delete(id)));
        return n;
      });
    },
    async copy() {
      if (picked === null) return;
      const my = ++seq.current;
      setBusy(true);
      setError(null);
      try {
        const out = await postCopy(scheduleId, picked, [...chosen]);
        if (my !== seq.current) return;
        setResult(out);
        onDone();
      } catch (e) {
        if (my === seq.current) setError(message(e));
      } finally {
        if (my === seq.current) setBusy(false);
      }
    },
  };
}

function resultText(r: CopyOut) {
  return `${r.copied}명 복사함 · ${r.skipped}명 건너뜀(이미 있음) · ${r.refused}명 거절`;
}

export default function CopyFromProject({ scheduleId, onClose, onDone }: { scheduleId: number; onClose: () => void; onDone: () => void }) {
  const cp = useCopy(scheduleId, onDone);
  const [query, setQuery] = useState('');
  const q = query.trim().toLowerCase();
  const groups = (cp.detail?.companies ?? []).map((c) => ({ c, people: c.people.filter((p) => matches(p, c, q)) })).filter((g) => g.people.length > 0);
  const n = cp.chosen.size;
  const hasDnc = cp.detail?.companies.some((c) => c.people.some((p) => p.do_not_contact)) ?? false;
  const foot = (
    <>
      <span className="ct-xfer-sum" aria-live="polite">
        {cp.result ? resultText(cp.result) : cp.busy ? '복사하는 중…' : cp.detail ? `${n}명 고름${n > MAX ? ` · 한 번에 ${MAX}명까지 복사할 수 있습니다` : ''}` : ''}
      </span>
      {cp.result ? (
        <Button variant="primary" onClick={onClose}>닫기</Button>
      ) : (
        <>
          <Button onClick={onClose} disabled={cp.busy}>취소</Button>
          <Button variant="primary" onClick={() => void cp.copy()} disabled={n === 0 || n > MAX || cp.busy}>{`${n}명 복사해 오기`}</Button>
        </>
      )}
    </>
  );
  return (
    <XferDialog title="다른 프로젝트에서 복사" busy={cp.busy} onClose={onClose} foot={foot}>
      <div className="ct-xfer-top">
        <label className="ct-fld-label">
          <span className="ct-label">복사해 올 프로젝트</span>
          <select className="ct-input" value={cp.picked ?? ''} disabled={cp.busy || cp.result !== null} onChange={(e) => cp.pick(e.target.value ? Number(e.target.value) : null)}>
            <option value="">{cp.sources && cp.sources.length === 0 ? '복사해 올 다른 프로젝트가 없습니다' : '프로젝트를 고르세요'}</option>
            {(cp.sources ?? []).map((s) => (
              <option key={s.schedule_id} value={s.schedule_id} disabled={s.people === 0}>{`${s.name} · ${s.people}명`}</option>
            ))}
          </select>
        </label>
        {cp.detail && (
          <input type="search" className="ct-input" disabled={cp.result !== null} aria-label="이름·담당·협력사 찾기" placeholder="이름·담당·협력사 찾기" value={query} onChange={(e) => setQuery(e.target.value)} />
        )}
        <p className="ct-hint">복사한 뒤에는 서로 따로 고칩니다.</p>
        {hasDnc && <p className="ct-hint is-warn">수신 거부인 사람은 복사한 뒤에도 연락할 수 없습니다.</p>}
        {cp.result && cp.result.refused > 0 && <p className="ct-hint is-warn">거절한 사람은 예전 자료가 지금의 주소록 입력 규칙에 맞지 않아 복사하지 않았습니다. 손으로 넣어 주세요.</p>}
        {cp.error && <p className="ct-error" role="alert">{cp.error}</p>}
      </div>
      <div className="ct-xfer-scroll">
        {cp.picked === null ? (
          <p className="ct-muted ct-pad">다른 프로젝트의 주소록은 여기서만 보입니다. 고른 사람만 이 프로젝트로 복사합니다.</p>
        ) : !cp.detail ? (
          !cp.error && <p className="ct-muted ct-pad">주소록을 읽는 중…</p>
        ) : groups.length === 0 ? (
          <p className="ct-muted ct-pad">{q ? '찾는 사람이 없습니다.' : '이 프로젝트에는 복사할 사람이 없습니다.'}</p>
        ) : (
          <fieldset className="ct-xfer-set" disabled={cp.busy || cp.result !== null} aria-label="사람 고르기">
            {groups.map(({ c, people }) => (
              <Group key={c.id} c={c} people={people} chosen={cp.chosen} setMany={cp.setMany} />
            ))}
          </fieldset>
        )}
      </div>
    </XferDialog>
  );
}
