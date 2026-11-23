// 「전화 걸기」 창의 줄과 쓰기 칸(Task 92 — CallDialog 에서 나눔). 줄: 받는 사람 · 통화 목적 · 물어볼 것 · 말하지 않을 것 · 연결 · 언어 ·
// 음성(고른 까닭) · 근무시간. 쓰기: 목적 · 물어볼 것·말하지 않을 것(한 줄에 하나) · 언어 · 연결할 작업.
// 글은 서버가 준 그대로 그린다 — 번호는 서버가 가려 주고, 번호가 든 글은 서버가 저장하지 않는다(422 has_phone).
import ActivityPicker from './ActivityPicker';
import { LANGUAGES, type PersonBrief, type PersonDetail } from './contactsApi';
import { activityLabel } from './thread';
import type { Call } from '../../shared/outreach/outreachApi';

const PURPOSE_MAX = 500; // 서버(Task 91)와 같은 값
const LINE_MAX = 200;
const LINES_MAX = 10;
const CIRCLED = '①②③④⑤⑥⑦⑧⑨⑩';
export const HOURS_UNREAD = '근무시간을 읽지 못했습니다';

export interface Form {
  purpose: string;
  questions: string;
  avoid: string;
  language: string;
  activity: string | null;
}

export const lines = (text: string) => text.split('\n').map((l) => l.trim()).filter(Boolean);
const langLabel = (code: string) => LANGUAGES.find((l) => l.key === code)?.label ?? code;

export const formOf = (row: Call | null, language: string): Form =>
  row
    ? { purpose: row.purpose, questions: row.questions.join('\n'), avoid: row.avoid.join('\n'), language: row.language, activity: row.activity?.id ?? null }
    : { purpose: '', questions: '', avoid: '', language, activity: null };

/** 보내기 전에 알 수 있는 꼴 문제(줄 수·길이). 번호는 서버가 본다. */
export function formProblem(f: Form): string | null {
  if (lines(f.questions).length > LINES_MAX || lines(f.avoid).length > LINES_MAX) return `물어볼 것·말하지 않을 것은 ${LINES_MAX}줄까지 적을 수 있습니다.`;
  if ([...lines(f.questions), ...lines(f.avoid)].some((l) => l.length > LINE_MAX)) return `한 줄은 ${LINE_MAX}자까지 적을 수 있습니다.`;
  return null;
}

/** 음성 줄: 이 통화에 고른 음성 → 연락처에서 직접 고른 음성 → 설정의 성별 칸(일꾼이 voices.pick 으로 고르는 차례 그대로). */
function voiceLine(row: Call | null, d: PersonDetail | null): string {
  if (row?.voice_id) return `${row.voice_id} · 이 통화에 고른 음성`;
  if (d?.voice_mode === 'manual' && d.voice_id) return `${d.voice_id} · 연락처에서 직접 고른 음성`;
  if (!d) return '설정의 음성 칸에서 고릅니다';
  const slot = d.gender === 'male' ? '남성 연락처에게 걸 때' : d.gender === 'female' ? '여성 연락처에게 걸 때' : '성별 모름';
  return `설정의 「${slot}」 칸에서 고릅니다`;
}

interface RowsProps {
  row: Call | null;
  person: PersonBrief;
  detail: PersonDetail | null;
  /** 사람 자세히를 읽지 못했다 */
  detailFailed: boolean;
  /** 쓰는 중이면 쓰지 않는 줄(받는 사람·음성·근무시간)만 */
  editing?: boolean;
}

/** 시안 ③의 줄들. */
export function Rows({ row, person, detail, detailFailed, editing = false }: RowsProps) {
  const c = row?.contact;
  const who = (c ? `${c.name} ${c.role_title}${c.company ? ` (${c.company})` : ''}` : `${person.name} ${person.role_title}`).trim();
  const hours = detail?.hours_label ?? (detailFailed ? HOURS_UNREAD : '읽는 중…');
  const tail = (
    <>
      <dt>음성</dt>
      <dd>{voiceLine(row, detail)}</dd>
      <dt>근무시간</dt>
      <dd>{hours}</dd>
    </>
  );
  if (editing)
    return (
      <dl className="cl-kv">
        <dt>받는 사람</dt>
        <dd>{who}</dd>
        {tail}
      </dl>
    );
  return (
    <dl className="cl-kv">
      <dt>받는 사람</dt>
      <dd>{who}</dd>
      <dt>통화 목적</dt>
      <dd>{row?.purpose ?? ''}</dd>
      <dt>물어볼 것</dt>
      <dd>
        {row && row.questions.length > 0 ? (
          <ol>
            {row.questions.map((q, i) => (
              <li key={i}>{`${CIRCLED[i] ?? `${i + 1}.`} ${q}`}</li>
            ))}
          </ol>
        ) : (
          '없음'
        )}
      </dd>
      <dt>말하지 않을 것</dt>
      <dd>{row && row.avoid.length > 0 ? row.avoid.join(', ') : '없음'}</dd>
      <dt>연결</dt>
      <dd>{row?.activity ? activityLabel(row.activity) : '없음'}</dd>
      <dt>언어</dt>
      <dd>{langLabel(row?.language ?? detail?.language ?? 'ko')}</dd>
      {tail}
    </dl>
  );
}

export function EditForm({ scheduleId, form, setForm, locked }: { scheduleId: number; form: Form; setForm(f: Form): void; locked: boolean }) {
  const put = (k: keyof Form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  return (
    <div className="cl-form">
      <label>
        통화 목적
        <textarea className="ct-input ct-textarea" aria-label="통화 목적" maxLength={PURPOSE_MAX} value={form.purpose} readOnly={locked} onChange={put('purpose')} />
      </label>
      <label>
        <span>
          물어볼 것 <span className="cl-hint">— 한 줄에 하나, {LINES_MAX}개까지</span>
        </span>
        <textarea className="ct-input ct-textarea" aria-label="물어볼 것" value={form.questions} readOnly={locked} onChange={put('questions')} />
      </label>
      <label>
        <span>
          말하지 않을 것 <span className="cl-hint">— 한 줄에 하나</span>
        </span>
        <textarea className="ct-input ct-textarea" aria-label="말하지 않을 것" value={form.avoid} readOnly={locked} onChange={put('avoid')} />
      </label>
      <label>
        언어
        <select className="ct-input" value={form.language} disabled={locked} onChange={put('language')}>
          {LANGUAGES.map((l) => (
            <option key={l.key} value={l.key}>
              {l.label}
            </option>
          ))}
        </select>
      </label>
      <p className="cl-small">번호는 적지 않습니다 — 받는 번호는 연락처에서 앱이 붙입니다.</p>
      <ActivityPicker scheduleId={scheduleId} value={form.activity} onChange={(id) => setForm({ ...form, activity: id })} disabled={locked} />
    </div>
  );
}
