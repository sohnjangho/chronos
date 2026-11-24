// [담당자에게 확인 연락]: 그 작업 담당 협력사 연락처(번호 없음)를 고르고 → 연락 방법 → 서버가 지은 글 미리 보기 → [초안 만들기].
// 초안은 서버가 기존 초안 길로 만들고 보내지 않는다 — 보내기는 연락처 창에서 사람이 확인한 뒤. 현장 관리자에게는 이 단추가 없다(서버도 403).
import { useEffect, useRef, useState } from 'react';
import { useWindows } from '../../os/windowStore';
import Button from '../../shared/ui/Button';
import { draftContact, errorText, getPeople, previewContact, type Channel, type Person, type Preview } from './pointsApi';

const CHANNELS: [Channel, string][] = [['sms', '문자'], ['call', '전화']];
const usable = (p: Person) => !p.do_not_contact && p.channels.length > 0;
const reach = (p: Person) =>
  p.do_not_contact ? '수신 거부' : p.channels.length ? p.channels.map((c) => CHANNELS.find(([k]) => k === c)?.[1]).join(' · ') : '연락 방법 없음';

function Made({ channel, onClose, onOpen }: { channel: Channel; onClose(): void; onOpen(): void }) {
  return (
    <div className="pt-contact" role="group" aria-label="담당자에게 확인 연락">
      <p className="pt-note" role="status">{`${channel === 'sms' ? '문자' : '전화'} 초안을 만들었습니다. 아직 보내지 않았습니다 — 연락처 창에서 확인한 뒤 보냅니다.`}</p>
      <div className="pt-actions">
        <Button onClick={onClose}>닫기</Button>
        <Button variant="primary" onClick={onOpen}>
          연락처에서 보기
        </Button>
      </div>
    </div>
  );
}

function People({ people, pick, onPick }: { people: Person[]; pick: Person | null; onPick(p: Person): void }) {
  return (
    <ul className="pt-people" role="radiogroup" aria-label="받는 사람">
      {people.map((p) => (
        <li key={p.contact_id}>
          <button type="button" role="radio" className="pt-person" aria-checked={pick?.contact_id === p.contact_id} disabled={!usable(p)} onClick={() => onPick(p)}>
            <span className="pt-person-name">
              <b>{p.name}</b>
              {[p.role_title, p.company].filter(Boolean).map((x) => ` · ${x}`).join('')}
            </span>
            <span className="pt-muted">{reach(p)}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function PreviewBox({ preview }: { preview: Preview }) {
  return (
    <div className="pt-preview">
      <span className="pt-muted">보낼 글 미리 보기</span>
      {preview.channel === 'sms' ? (
        <p>{preview.body}</p>
      ) : (
        <>
          <p>{preview.purpose}</p>
          <ul className="pt-plain">
            {preview.questions.map((q, i) => (
              <li key={i}>{q}</li>
            ))}
          </ul>
        </>
      )}
      <span className="pt-muted">바로 보내지 않습니다. [초안 만들기]를 누르면 초안만 생깁니다.</span>
    </div>
  );
}

export default function PointContact({ sid, aid, name, whatIf, onClose }: { sid: number; aid: string; name: string; whatIf: boolean; onClose(): void }) {
  const [people, setPeople] = useState<Person[] | null>(null);
  const [error, setError] = useState('');
  const [pick, setPick] = useState<Person | null>(null);
  const [channel, setChannel] = useState<Channel>('sms');
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [made, setMade] = useState<{ contact: number; channel: Channel } | null>(null);
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
      await draftContact(sid, aid, pick.contact_id, channel, whatIf);
      setMade({ contact: pick.contact_id, channel });
    } catch (e) {
      setError(errorText(e, '초안을 만들지 못했습니다.'));
    } finally {
      setBusy(false);
    }
  };

  const openContacts = (contact?: number, ch?: Channel) =>
    useWindows.getState().open('contacts', {
      id: String(sid),
      ...(contact !== undefined ? { contact: String(contact), tab: ch === 'call' ? 'calls' : 'messages' } : {}),
    });

  if (made)
    return <Made channel={made.channel} onClose={onClose} onOpen={() => openContacts(made.contact, made.channel)} />;

  return (
    <div className="pt-contact" role="group" aria-label="담당자에게 확인 연락">
      <div className="pt-contact-h">
        <b>누구에게 물을까요?</b>
        {people && <span className="pt-muted">{`${name} 담당 연락처 ${people.length}명 · 번호는 보이지 않습니다`}</span>}
      </div>
      {people === null && !error && <p className="pt-muted">연락처를 읽는 중…</p>}
      {people && people.length === 0 && <p className="pt-muted">이 작업의 담당 연락처가 없습니다.</p>}
      {people && people.length > 0 && (
        <People people={people} pick={pick} onPick={(p) => show(p, p.channels.includes(channel) ? channel : p.channels[0])} />
      )}
      <div className="pt-row">
        {pick && (
          <span className="pt-seg" role="radiogroup" aria-label="연락 방법">
            {CHANNELS.map(([c, label]) => (
              <button key={c} type="button" role="radio" aria-checked={channel === c} disabled={!pick.channels.includes(c)} onClick={() => show(pick, c)}>
                {label}
              </button>
            ))}
          </span>
        )}
        <button type="button" className="pt-link" onClick={() => openContacts()}>
          주소록에서 다른 사람 고르기
        </button>
      </div>
      {preview && <PreviewBox preview={preview} />}
      {error && <p className="pt-error" role="alert">{error}</p>}
      <div className="pt-actions">
        <Button onClick={onClose}>취소</Button>
        <Button variant="primary" disabled={preview === null || busy} onClick={() => void make()}>
          초안 만들기
        </Button>
      </div>
    </div>
  );
}
