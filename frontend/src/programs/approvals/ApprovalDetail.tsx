// 승인 건 하나: 제목·요청·승인이 필요한 이유(전후 값)·숫자·바뀌는 것 표. 결정 상자는 부르는 쪽이 붙인다.
import { useCurrentSchedule } from '../../os/currentSchedule';
import { useWindows } from '../../os/windowStore';
import { domainLabel } from '../../shared/domainLabels';
import ContactButton from '../../shared/outreach/ContactButton';
import { approvalText, useCanContact } from '../../shared/outreach/contactKit';
import Badge from '../../shared/ui/Badge';
import Button from '../../shared/ui/Button';
import { STATUS, type ApprovalDetail as Detail, type Json } from './apvApi';
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

/** 서버가 요약에 남긴 알릴 것(summary.notes) — 예: 현장 회신의 실제 시작이 선행이 허락하는 날보다 이르다. */
function Notes({ item }: { item: Detail }) {
  const notes = asList(asObj(item.summary).notes).map(asText).filter(Boolean);
  if (notes.length === 0) return null;
  return (
    <section className="apv-why" aria-label="알릴 것">
      <b>알릴 것</b>
      {notes.map((n, i) => (
        <p key={i} className="apv-muted apv-wrap">
          {n}
        </p>
      ))}
    </section>
  );
}

function Numbers({ item, scheduleName }: { item: Detail; scheduleName: string | null }) {
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
        <Button
          onClick={() => {
            useCurrentSchedule.getState().setCurrent({ id: item.schedule_id!, name: scheduleName ?? item.title });
            useWindows.getState().open('gantt', { id: String(item.schedule_id) });
          }}
        >
          간트에서 보기
        </Button>
      )}
    </div>
  );
}

const md = (v: unknown) => asList(v).map(asText).join('.');

/** 내 규칙의 종류와 값 한 줄(서버 자료라 칸이 빠져 있어도 던지지 않는다). */
function ruleValue(kind: string, p: Json): string {
  switch (kind) {
    case 'max_duration':
      return `기간 상한 · ${asText(p.days)}일`;
    case 'min_gap':
      return `간격 · '${asText(p.after_tag)}' 뒤 ${p.unit === 'calendar_days' ? '달력일' : '근무일'} ${asText(p.days)}일`;
    case 'blocked_period':
      return `금지 기간 · ${md(p.start_md)}~${md(p.end_md)} '${asText(p.tag)}'`;
    case 'calendar':
      return `달력 · 주 ${asText(p.days_per_week)}일 근무${p.holidays === 'KR' ? ' · 한국 공휴일 쉼' : ''}`;
    case 'duration_per_unit':
      return '단위당 기간 (자동 점검 안 됨)';
    case 'text_only':
      return '말로 된 규칙 (자동 점검 안 됨)';
    default:
      return kind;
  }
}

/** kind 'rule': 무엇을 내 규칙으로 저장하는가(글·범위·종류와 값). 일정이 바뀌지 않아 전후 표·간트는 없다. */
function RuleBlock({ item }: { item: Detail }) {
  const r = asObj(asObj(item.summary).rule);
  const domain = asText(r.domain);
  const scope = r.scope === 'schedule' ? '이 일정' : `분야 전체 · ${domainLabel(domain)}`;
  return (
    <section className="apv-rule" aria-label="내 규칙 저장">
      <b>내 규칙 저장</b>
      <p className="apv-rule-text apv-wrap">{asText(r.text)}</p>
      <dl className="apv-rule-facts">
        <dt>범위</dt>
        <dd>{scope}</dd>
        <dt>종류와 값</dt>
        <dd className="apv-wrap">{ruleValue(asText(r.kind), asObj(r.params))}</dd>
      </dl>
    </section>
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

/** 대기 건의 [승인권자에게 알림](Task 104) — 문안 「승인 대기 알림」(지금은 같은 뜻의 문자 글), 받는 사람은 창이 이 프로젝트 주소록에서
 * 고른다. 일정에 묶인 대기 건만(주소록이 일정마다라서). 현장 관리자·알림 연결 없음은 ContactButton 이 다룬다. */
function NotifyApprover({ item }: { item: Detail }) {
  const can = useCanContact();
  if (!can || item.status !== 'pending' || item.schedule_id === null) return null;
  return (
    <div className="apv-decided">
      <ContactButton
        scheduleId={item.schedule_id}
        label="승인권자에게 알림"
        title={`승인권자에게 알림 — ${item.title}`}
        preset={{ approvalId: item.id, templateUse: '승인 대기 알림', body: approvalText(item) }}
      />
    </div>
  );
}

function metaOf(item: Detail, scheduleName: string | null): string[] {
  const request = item.request ? `요청: "${item.request}"` : '';
  if (item.kind === 'rule') return [request, '일정은 바뀌지 않습니다'];
  const target = scheduleName ?? (item.kind === 'first_save' ? '새 일정' : `일정 #${item.schedule_id}`);
  return [request, target, item.kind === 'first_save' ? '첫 저장' : `기준 버전 ${item.base_version}`];
}

export default function ApprovalDetail({ item, scheduleName }: Props) {
  const meta = metaOf(item, scheduleName);
  const rule = item.kind === 'rule';
  return (
    <article className="apv-detail" aria-label={item.title}>
      <header className="apv-head">
        <h2 className="apv-title apv-wrap">{item.title}</h2>
        <p className="apv-meta apv-wrap">{meta.filter(Boolean).join(' · ')}</p>
        <DecidedLine item={item} />
        <NotifyApprover item={item} />
        {!rule && <Why item={item} />}
        {!rule && <Notes item={item} />}
      </header>
      <div className="apv-body">
        {rule ? (
          <RuleBlock item={item} />
        ) : (
          <>
            <Numbers item={item} scheduleName={scheduleName} />
            <DiffTable item={item} />
          </>
        )}
      </div>
    </article>
  );
}
