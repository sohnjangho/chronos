// 승인 건 하나: 제목·요청·승인이 필요한 이유(전후 값)·숫자·바뀌는 것 표. 결정 상자는 부르는 쪽이 붙인다.
import { useWindows } from '../../os/windowStore';
import Badge from '../../shared/ui/Badge';
import Button from '../../shared/ui/Button';
import { STATUS, type ApprovalDetail as Detail } from './apvApi';
import { asList, asNum, asObj, asText, checkText, floatText, noReasonText, range, reasonTone, ro, signedDays, stamp, whyLines } from './format';

interface Props {
  item: Detail;
  /** 대상 일정 이름(첫 저장 대기는 null). */
  scheduleName: string | null;
}

function DecidedLine({ item }: { item: Detail }) {
  if (item.status === 'pending') return null;
  const parts =
    item.status === 'auto'
      ? [item.version === null ? '' : `버전 ${ro(item.version)} 반영`, stamp(item.created_at)]
      : [item.decided_by ?? '', stamp(item.decided_at), item.retry ? '다시 짜게 함' : ''];
  return (
    <p className="apv-decided">
      <span className={`apv-status is-${item.status}`}>{STATUS[item.status]}</span>
      <span className="apv-wrap">{parts.filter(Boolean).join(' · ')}</span>
      {item.note && <span className="apv-wrap apv-note">의견: {item.note}</span>}
    </p>
  );
}

function Why({ item }: { item: Detail }) {
  const auto = item.status === 'auto';
  const title = auto ? '자동 적용한 변경' : '승인이 필요한 이유';
  const lines = whyLines(item);
  return (
    <section className="apv-why" aria-label={title}>
      <b>{title}</b>
      {lines.length === 0 && <p className="apv-muted">{noReasonText(item.mode, auto)}</p>}
      {lines.map((w) => (
        <div key={w.reason} className="apv-why-row">
          <Badge tone={reasonTone(w.reason)}>{w.label}</Badge>
          <div className="apv-why-text">
            {w.lines.map((l, i) => (
              <span key={i} className="apv-wrap">
                {l}
              </span>
            ))}
          </div>
        </div>
      ))}
    </section>
  );
}

function Numbers({ item }: { item: Detail }) {
  const s = asObj(item.summary);
  const count = asNum(s.changed_count);
  const check = checkText(s);
  const float = floatText(s);
  return (
    <div className="apv-nums">
      <div>
        <span>바뀌는 액티비티</span>
        <b>{count === null ? '—' : `${count}개`}</b>
      </div>
      <div>
        <span>조건 점검</span>
        <b className={check ? `is-${check.tone}` : undefined}>{check?.text ?? '—'}</b>
      </div>
      <div>
        <span>기한 여유 (근무일)</span>
        <b>{float ?? '기한 조건 없음'}</b>
      </div>
      <span className="apv-gap" />
      {item.schedule_id !== null && (
        <Button onClick={() => useWindows.getState().open('schedule', { id: String(item.schedule_id), tab: 'gantt' })}>간트에서 보기</Button>
      )}
    </div>
  );
}

function deltaCell(before: unknown, after: unknown, delta: number | null) {
  if (before === null) return <td className="apv-delta">새로 생김</td>;
  if (after === null) return <td className="apv-delta">없어짐</td>;
  const tone = delta === null || delta === 0 ? '' : delta < 0 ? ' is-ok' : ' is-bad';
  return <td className={`apv-delta${tone}`}>{delta === null ? '—' : signedDays(delta)}</td>;
}

function DiffTable({ item }: { item: Detail }) {
  const changed = asList(asObj(item.summary).conditions_changed).map(asObj);
  return (
    <table className="apv-table" aria-label="바뀌는 것">
      <colgroup>
        <col className="apv-c-id" />
        <col />
        <col className="apv-c-date" />
        <col className="apv-c-date" />
        <col className="apv-c-delta" />
      </colgroup>
      <thead>
        <tr>
          <th>ID</th>
          <th>이름</th>
          <th>지금 (시작 ~ 종료)</th>
          <th>바꾼 뒤</th>
          <th className="apv-delta">종료 차이</th>
        </tr>
      </thead>
      <tbody>
        {item.diff.length === 0 && changed.length === 0 && (
          <tr>
            <td colSpan={5} className="apv-muted">
              바뀌는 액티비티가 없습니다.
            </td>
          </tr>
        )}
        {item.diff.map((r) => (
          <tr key={r.activity_id}>
            <td title={r.activity_id}>{r.activity_id}</td>
            <td title={r.name}>{r.name}</td>
            <td className="apv-before">{range(r.before)}</td>
            <td className="apv-after">{range(r.after)}</td>
            {deltaCell(r.before, r.after, r.finish_delta)}
          </tr>
        ))}
        {changed.map((c, i) => (
          <tr key={`c${i}`} className="apv-cond">
            <td>조건</td>
            <td title={asText(c.name) || asText(c.id)}>{asText(c.name) || asText(c.id)}</td>
            <td className="apv-before">{asText(c.before) || '없음'}</td>
            <td className="apv-after">{asText(c.after) || '없음'}</td>
            <td />
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function ApprovalDetail({ item, scheduleName }: Props) {
  const target = scheduleName ?? (item.kind === 'first_save' ? '새 일정' : `일정 #${item.schedule_id}`);
  const meta = [item.request ? `요청: "${item.request}"` : '', target, item.kind === 'first_save' ? '첫 저장' : `기준 버전 ${item.base_version}`];
  return (
    <article className="apv-detail" aria-label={item.title}>
      <header className="apv-head">
        <h2 className="apv-title apv-wrap">{item.title}</h2>
        <p className="apv-meta apv-wrap">{meta.filter(Boolean).join(' · ')}</p>
        <DecidedLine item={item} />
        <Why item={item} />
      </header>
      <div className="apv-body">
        <Numbers item={item} />
        <DiffTable item={item} />
      </div>
    </article>
  );
}
