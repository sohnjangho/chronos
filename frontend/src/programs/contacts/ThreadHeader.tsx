// 대화 칸 머리 줄(이름·담당·협력사·가린 번호·되는 채널·탭은 바로 위 PersonHead 가 그린다): 근무시간 줄(hours_label)·언어·
// 여러 프로젝트에 등록된 사람이면 그 프로젝트들(11-24)·
// 「번호 눌러서 보기」. 전체 번호는 누른 뒤 이 줄의 상태에만 있고(주소록 API 의 reveal — 10분에 30번), 사람이나 프로젝트가 바뀌면
// 이 줄이 새로 그려져 사라진다. 저장·URL·로그에 두지 않는다.
import { useEffect, useState } from 'react';
import { getPerson, LANGUAGES, revealPhone, type PersonBrief, type PersonDetail } from './contactsApi';

export default function ThreadHeader({ scheduleId, person }: { scheduleId: number; person: PersonBrief }) {
  const [detail, setDetail] = useState<PersonDetail | null>(null);
  const [phone, setPhone] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    getPerson(scheduleId, person.id).then(
      (d) => live && setDetail(d),
      () => undefined, // 근무시간 줄 없이 둔다(대화는 그대로 볼 수 있다)
    );
    return () => {
      live = false;
    };
  }, [scheduleId, person.id]);

  const reveal = async () => {
    setBusy(true);
    setError(null);
    try {
      setPhone((await revealPhone(scheduleId, person.id)).phone);
    } catch (e) {
      setError(e instanceof Error ? e.message : '번호를 볼 수 없습니다.');
    }
    setBusy(false);
  };

  return (
    <div className="th-head">
      {detail && <span className="th-head-item">{detail.hours_label}</span>}
      {detail && <span className="th-head-item">{LANGUAGES.find((l) => l.key === detail.language)?.label ?? detail.language}</span>}
      {detail && detail.project_links.length > 1 && (
        <span className="th-head-item ct-ellipsis" title={detail.project_links.map((p) => p.name).join(' · ')}>
          {`참여 프로젝트: ${detail.project_links.map((p) => p.name).join(' · ')}`}
        </span>
      )}
      {person.has_phone &&
        (phone ? (
          <>
            <span className="th-head-item th-head-num ct-num">{phone}</span>
            <button type="button" className="ct-link" onClick={() => setPhone(null)}>번호 가리기</button>
          </>
        ) : (
          <button type="button" className="ct-link" disabled={busy} onClick={() => void reveal()}>번호 눌러서 보기</button>
        ))}
      {error && <span className="ct-error" role="alert">{error}</span>}
    </div>
  );
}
