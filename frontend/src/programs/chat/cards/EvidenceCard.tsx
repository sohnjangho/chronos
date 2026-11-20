import Badge from '../../../shared/ui/Badge';
import { dotDate } from '../labels';
import { asList, asNum, asObj, asText, Card, type CardProps } from './Card';
import './cards2.css';

const MODES: Record<string, string> = { web: '웹', scholar: '학술', legal: '법령', business: '기업', weather: '날씨' };
const linkable = (url: string) => /^https?:\/\//i.test(url);

/**
 * 근거 검색(evidence.search 의 evidence 카드, Task 27·27b): 찾은 말·모드 배지, 결과마다 [근거 n](n = evidence_id)·제목 링크(새 탭)·사이트·날짜.
 * 분야 검색이 실패해 웹으로 대신 찾았으면 note 를 작은 줄로 보인다. 결과의 날짜는 근거의 날짜일 뿐이다.
 */
export default function EvidenceCard({ data }: CardProps) {
  const mode = asText(data.mode);
  const note = asText(data.note);
  const results = asList(data.results).map(asObj);
  return (
    <Card title="근거" extra={mode && <Badge tone="info">{MODES[mode] ?? mode}</Badge>}>
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
                {meta && <span className="ch-meta ch-wrap">{meta}</span>}
              </li>
            );
          })}
        </ol>
      )}
    </Card>
  );
}
