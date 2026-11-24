// [담당자에게 확인 연락](계획 5 Task 6, 시안 contact.html): 그 작업 담당 협력사 연락처(번호 없음)를 고르고, 연락 방법을 고르면
// 서버가 지은 글을 미리 보이고, [초안 만들기] → 서버가 기존 초안 길로 초안을 만든다(보내지 않음). 초안 카드는 부르는 쪽이 그린다.
import { useEffect, useRef, useState } from 'react';
import { useSession } from '../../../os/session';
import { useWindows } from '../../../os/windowStore';
import Button from '../../../shared/ui/Button';
import type { Json } from '../thread';
import { STALE_HINT } from './PointRisks';
import { draftContact, errorText, getPeople, previewContact, type Channel, type Person, type Preview } from './pointsApi';

const CHANNELS: [Channel, string][] = [['sms', '문자'], ['call', '전화']];

const usable = (p: Person) => !p.do_not_contact && p.channels.length > 0;
const reach = (p: Person) =>
  p.do_not_contact ? '수신 거부' : p.channels.length ? p.channels.map((c) => CHANNELS.find(([k]) => k === c)?.[1]).join(' · ') : '연락 방법 없음';

function People({ people, pick, onPick }: { people: Person[]; pick: Person | null; onPick(p: Person): void }) {
  return (
    <ul className="pc-people" role="radiogroup" aria-label="받는 사람">
      {people.map((p) => (
        <li key={p.contact_id}>
          <button type="button" role="radio" className="pc-person" aria-checked={pick?.contact_id === p.contact_id} disabled={!usable(p)} onClick={() => onPick(p)}>
            <span className="pc-radio" aria-hidden="true" />
            <span className="pc-person-name ch-wrap">
              <b>{p.name}</b>
              {[p.role_title, p.company].filter(Boolean).map((x) => ` · ${x}`).join('')}
            </span>
            <span className="ch-meta">{reach(p)}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function PreviewBox({ preview }: { preview: Preview }) {
  return (
    <>
      <span className="ch-meta">보낼 글 미리 보기 — 포인트와 바깥 위험을 넣었습니다</span>
      <div className="oc-draft">
        {preview.channel === 'sms' ? (
          <p className="oc-body">{preview.body}</p>
        ) : (
          <>
            <p className="oc-body">{preview.purpose}</p>
            <ul className="oc-list">
              {preview.questions.map((q, i) => (
                <li key={i}>{q}</li>
              ))}
            </ul>
          </>
        )}
      </div>
      <p className="ch-meta ch-wrap">{`바로 보내지 않습니다. [초안 만들기]를 누르면 ${preview.channel === 'sms' ? '문자' : '전화'} 초안 카드가 생기고, 거기서 확인한 뒤 보냅니다.`}</p>
    </>
  );
}

export default function ContactPicker({ sid, aid, name, whatIf, stale, onClose, onDraft }: {
  sid: number;
  aid: string;
  name: string;
  whatIf: boolean;
  /** 지난 버전 카드 — 초안을 만들지 않는다(글이 지금 포인트와 다를 수 있음). */
  stale: boolean;
  onClose(): void;
  onDraft(card: Json): void;
}) {
  const field = useSession((s) => s.session?.user.role === 'field'); // 현장 관리자는 연락처를 쓰지 않는다(서버 403)
  const [people, setPeople] = useState<Person[] | null>(null);
  const [error, setError] = useState('');
  const [pick, setPick] = useState<Person | null>(null);
  const [channel, setChannel] = useState<Channel>('sms');
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const seq = useRef(0);

  useEffect(() => {
    let live = true;
    getPeople(sid, aid, whatIf)
      .then((r) => live && setPeople(r.people))
      .catch((e) => live && setError(errorText(e, '연락처를 읽지 못했습니다.')));
    return () => {
      live = false;
    };
  }, [sid, aid, whatIf]);

  const show = (who: Person, ch: Channel) => {
    setPick(who);
    setChannel(ch);
    setPreview(null);
    setError('');
    const at = ++seq.current;
    previewContact(sid, aid, who.contact_id, ch, whatIf)
      .then((p) => at === seq.current && setPreview(p))
      .catch((e) => at === seq.current && setError(errorText(e, '보낼 글을 만들지 못했습니다.')));
  };

  const make = async () => {
    if (pick === null || busy) return;
    setBusy(true);
    setError('');
    try {
      onDraft((await draftContact(sid, aid, pick.contact_id, channel, whatIf)).card);
    } catch (e) {
      setError(errorText(e, '초안을 만들지 못했습니다.'));
      setBusy(false);
    }
  };

  return (
    <div className="pc-contact" role="group" aria-label="담당자에게 확인 연락">
      <div className="pc-contact-h">
        <b>누구에게 물을까요?</b>
        {people && <span className="ch-meta">{`${name} 담당 연락처 ${people.length}명 · 번호는 보이지 않습니다`}</span>}
      </div>
      {people === null && !error && <p className="ch-meta">연락처를 읽는 중…</p>}
      {people && people.length === 0 && <p className="ch-meta">이 작업의 담당 연락처가 없습니다.</p>}
      {people && people.length > 0 && (
        <People people={people} pick={pick} onPick={(p) => show(p, p.channels.includes(channel) ? channel : p.channels[0])} />
      )}
      <div className="pc-row">
        {pick && (
          <>
            <span className="ch-meta">연락 방법</span>
            <span className="pc-seg" role="radiogroup" aria-label="연락 방법">
              {CHANNELS.map(([c, label]) => (
                <button key={c} type="button" role="radio" aria-checked={channel === c} disabled={!pick.channels.includes(c)} onClick={() => show(pick, c)}>
                  {label}
                </button>
              ))}
            </span>
          </>
        )}
        {!field && (
          <button type="button" className="pc-link" onClick={() => useWindows.getState().open('contacts', { id: String(sid) })}>
            주소록에서 다른 사람 고르기
          </button>
        )}
      </div>
      {preview && <PreviewBox preview={preview} />}
      {error && <p className="ch-error ch-wrap" role="alert">{error}</p>}
      <div className="ch-actions oc-acts">
        <Button onClick={onClose}>취소</Button>
        <Button variant="primary" disabled={preview === null || busy || stale} title={stale ? STALE_HINT : undefined} onClick={() => void make()}>
          초안 만들기
        </Button>
      </div>
    </div>
  );
}

