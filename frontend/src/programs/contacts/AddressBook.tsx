// 왼쪽 주소록: 찾기(이름·담당) · 협력사별 묶음(접기) · 사람 줄(이름·담당·새 회신·번호 없음·수신 거부·번호 오류·휴대전화가 아닌 번호 종류) ·
// 아래 [+ 사람 추가][협력사 추가][CSV 가져오기][다른 프로젝트에서 복사 — 관리자] · 숨긴 사람 보기. 번호는 여기 나오지 않는다.
import { useState } from 'react';
import Button from '../../shared/ui/Button';
import { KIND_LABEL, type AddressBook as Book, type CompanyGroup, type PersonBrief } from './contactsApi';

interface Props {
  book: Book | null;
  error: string | null;
  selectedId: number | null;
  onSelect: (p: PersonBrief) => void;
  onAddPerson: (companyId: number | null) => void;
  onAddCompany: () => void;
  onEditCompany: (c: CompanyGroup) => void;
  showHidden: boolean;
  onShowHidden: (on: boolean) => void;
  isAdmin: boolean;
  /** CSV 가져오기·다른 프로젝트에서 복사(Task 77). 없으면 단추가 꺼져 있다. */
  onImport?: () => void;
  onCopy?: () => void;
}

const matches = (p: PersonBrief, q: string) => p.name.toLowerCase().includes(q) || p.role_title.toLowerCase().includes(q);

function Row({ p, current, onSelect }: { p: PersonBrief; current: boolean; onSelect: () => void }) {
  const kind = p.phone_kind && p.phone_kind !== 'mobile' ? KIND_LABEL[p.phone_kind] : null;
  return (
    <li className="ct-li">
      <button type="button" className={`ct-row${p.hidden ? ' is-hidden' : ''}`} aria-current={current ? 'true' : undefined} onClick={onSelect}>
        <span className="ct-row-top">
          <span className="ct-name ct-ellipsis">{p.name}</span>
          {p.unread > 0 && (
            <>
              <span className="ct-unread" aria-hidden="true">
                {p.unread > 99 ? '99+' : p.unread}
              </span>
              <span className="ct-sr">{`새 회신 ${p.unread}`}</span>
            </>
          )}
        </span>
        <span className="ct-row-sub">
          <span className="ct-role ct-ellipsis">{p.role_title || '담당 없음'}</span>
          {!p.has_phone && <span className="ct-tag is-warn">번호 없음</span>}
          {p.do_not_contact && <span className="ct-tag is-bad">수신 거부</span>}
          {p.phone_invalid && <span className="ct-tag is-bad">번호 오류</span>}
          {kind && <span className="ct-tag">{kind}</span>}
          {p.hidden && <span className="ct-tag">숨김</span>}
        </span>
      </button>
    </li>
  );
}

export default function AddressBook(props: Props) {
  const { book, error, selectedId, onSelect, onAddPerson, onAddCompany, onEditCompany, showHidden, onShowHidden, isAdmin, onImport, onCopy } = props;
  const [query, setQuery] = useState('');
  const [closed, setClosed] = useState<Set<number>>(() => new Set());
  const q = query.trim().toLowerCase();
  const groups = (book?.companies ?? []).map((c) => ({ c, people: q ? c.people.filter((p) => matches(p, q)) : c.people })).filter((g) => !q || g.people.length > 0);
  const toggle = (id: number) =>
    setClosed((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  const empty = book !== null && book.companies.length === 0;

  return (
    <nav className="ct-book" aria-label="주소록">
      <div className="ct-find">
        <input
          type="search"
          className="ct-input"
          aria-label="이름·담당 찾기"
          placeholder="이름·담당 찾기"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      <div className="ct-book-list">
        {error ? (
          <p className="ct-error ct-pad" role="alert">
            {error}
          </p>
        ) : !book ? (
          <p className="ct-muted ct-pad">주소록을 읽는 중…</p>
        ) : empty ? (
          <p className="ct-muted ct-pad">아직 주소록이 비어 있습니다. 아래 [협력사 추가]로 협력사를 먼저 만들고 사람을 넣으세요.</p>
        ) : groups.length === 0 ? (
          <p className="ct-muted ct-pad">찾는 사람이 없습니다.</p>
        ) : (
          groups.map(({ c, people }) => {
            const open = q !== '' || !closed.has(c.id);
            return (
              <section key={c.id} role="group" aria-label={c.name} className="ct-group">
                <div className="ct-co">
                  <button type="button" className="ct-co-toggle" aria-expanded={open} aria-label={`${c.name} ${c.people.length}명`} onClick={() => toggle(c.id)}>
                    <span className="ct-caret" aria-hidden="true">{open ? '▾' : '▸'}</span>
                    <span className="ct-co-name ct-ellipsis">{c.name}</span>
                    {c.trade && <span className="ct-co-trade ct-ellipsis">{c.trade}</span>}
                    {c.hidden && <span className="ct-tag">숨김</span>}
                    <span className="ct-co-count">{`${c.people.length}명`}</span>
                  </button>
                  <button type="button" className="ct-co-edit" aria-label={`${c.name} 고치기`} title="협력사 고치기" onClick={() => onEditCompany(c)}>
                    고치기
                  </button>
                </div>
                {open && (
                  <ul className="ct-people">
                    {people.map((p) => (
                      <Row key={p.id} p={p} current={p.id === selectedId} onSelect={() => onSelect(p)} />
                    ))}
                    {people.length === 0 && <li className="ct-muted ct-none">사람이 없습니다.</li>}
                  </ul>
                )}
              </section>
            );
          })
        )}
      </div>
      <div className="ct-book-foot">
        <div className="ct-foot-btns">
          <Button variant="primary" onClick={() => onAddPerson(null)} disabled={!book || empty}>
            + 사람 추가
          </Button>
          <Button onClick={onAddCompany} disabled={!book}>
            협력사 추가
          </Button>
          <Button onClick={onImport} disabled={!onImport}>
            CSV 가져오기
          </Button>
          {isAdmin && (
            <Button onClick={onCopy} disabled={!onCopy}>
              다른 프로젝트에서 복사
            </Button>
          )}
        </div>
        <label className="ct-check ct-foot-check">
          <input type="checkbox" checked={showHidden} onChange={(e) => onShowHidden(e.target.checked)} />
          숨긴 사람 보기
        </label>
        <p className="ct-hint">{`이 프로젝트의 주소록입니다${!onImport ? ' · CSV 가져오기·복사는 준비 중입니다' : ''}`}</p>
        {book && (book.proposals_pending > 0 || book.reports_open > 0) && (
          <p className="ct-hint">{`확인할 연락처 제안 ${book.proposals_pending}건 · 확인하지 않은 보고 ${book.reports_open}건`}</p>
        )}
      </div>
    </nav>
  );
}
