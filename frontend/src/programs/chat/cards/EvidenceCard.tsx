import { useState } from 'react';
import { api, ApiError } from '../../../shared/api';
import Badge from '../../../shared/ui/Badge';
import Button from '../../../shared/ui/Button';
import { dotDate } from '../labels';
import type { Json } from '../thread';
import { asList, asNum, asObj, asText, Card, type CardProps } from './Card';
import './cards2.css';

const MODES: Record<string, string> = { web: '웹', scholar: '학술', legal: '법령', business: '기업', weather: '날씨', info: '정보 API' };
const linkable = (url: string) => /^https?:\/\//i.test(url);
const monthDay = (iso: string) => iso.replace(/^\d{4}-(\d{2})-(\d{2})$/, '$1-$2');

/** 다시 쓴 결과의 머리 줄. 찾은 날(searched_at)이 여러 날이면 가장 이른 날~늦은 날. */
function savedLine(results: Json[]): string {
  const days = results.map((r) => asText(r.searched_at)).filter(Boolean).sort();
  if (days.length === 0) return '저장된 근거';
  const [first, last] = [monthDay(days[0]), monthDay(days[days.length - 1])];
  return `저장된 근거 · ${first === last ? first : `${first}~${last}`} 검색`;
}

/** 줄마다 [다시 쓰지 않기](POST /api/evidence/{id}/retire) → 「다시 쓰지 않음 · [되돌리기]」(restore). */
function RetireControl({ id }: { id: number }) {
  const [retired, setRetired] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const label = retired ? '되돌리기' : '다시 쓰지 않기';
  async function toggle() {
    setBusy(true);
    setError('');
    try {
      await api(`/api/evidence/${id}/${retired ? 'restore' : 'retire'}`, { method: 'POST' });
      setRetired(!retired);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '요청을 처리할 수 없습니다.');
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      {' '}
      {retired && (
        <>
          <span>다시 쓰지 않음</span>
          {' · '}
        </>
      )}
      <Button disabled={busy} aria-label={`근거 ${id} ${label}`} onClick={toggle}>
        {label}
      </Button>
      {error && <span className="ch-error">{` ${error}`}</span>}
    </>
  );
}

/**
 * 근거 검색(evidence.search 의 evidence 카드, Task 27·27b): 찾은 말·모드 배지, 결과마다 [근거 n](n = evidence_id)·제목 링크(새 탭)·사이트·날짜.
 * 분야 검색이 실패해 웹으로 대신 찾았으면 note 를 작은 줄로 보인다. 결과의 날짜는 근거의 날짜일 뿐이다.
 * 저장된 근거를 다시 쓴 결과(reused, 설계 2026-11-23)는 머리에 「저장된 근거 · MM-DD 검색」, 줄마다 [다시 쓰지 않기].
 */
export default function EvidenceCard({ data }: CardProps) {
  const mode = asText(data.mode);
  const note = asText(data.note);
  const results = asList(data.results).map(asObj);
  const reused = data.reused === true;
  return (
    <Card title="근거" extra={mode && <Badge tone="info">{MODES[mode] ?? mode}</Badge>}>
      {reused && <p className="ch-note ch-wrap">{savedLine(results)}</p>}
      {asText(data.query) && <p className="ch-wrap">{`찾은 말: ${asText(data.query)}`}</p>}
      {note && <p className="ch-note ch-wrap">{note}</p>}
      {results.length === 0 ? (
        <p className="ch-note">맞는 결과가 없습니다.</p>
      ) : (
        <ol className="ch-plain ch-evidence">
          {results.map((r, i) => {
            const id = asNum(r.evidence_id);
            const url = asText(r.url);
            const title = asText(r.title) || url || '제목 없음';
            const meta = [asText(r.hostname), dotDate(r.date)].filter(Boolean).join(' · ');
            return (
              <li key={id ?? `i${i}`}>
                {id !== null && <span className="ch-cite">{`[근거 ${id}]`}</span>}
                {linkable(url) ? (
                  <a className="ch-wrap" href={url} target="_blank" rel="noopener noreferrer" aria-label={`${title} (새 탭)`}>
                    {title}
                  </a>
                ) : (
                  <span className="ch-wrap">{title}</span>
                )}
                {(meta || (reused && id !== null)) && (
                  <span className="ch-meta ch-wrap">
                    {meta}
                    {reused && id !== null && <RetireControl id={id} />}
                  </span>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </Card>
  );
}
