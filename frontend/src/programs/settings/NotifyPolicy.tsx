import { useId, useState, type ReactNode } from 'react';
import { ApiError } from '../../shared/api';
import LimitsForm from '../../shared/outreach/LimitsForm';
import Button from '../../shared/ui/Button';
import Field from '../../shared/ui/Field';
import type { LlmError } from './model';
import { notifyApi, type NotifyConnection, type NotifyPatch, type Permission, type PhoneKind } from './notifyApi';
import { ErrorLine, toProblem } from './parts';

export const KAKAO_LOCKED = '카카오톡(알림톡)은 아직 쓸 수 없습니다 — 채널 연결과 문안 검수가 끝나면 켤 수 있습니다.';

export const KIND_LABEL: Record<PhoneKind, string> = {
  mobile: '휴대전화',
  landline: '유선',
  internet: '인터넷 전화',
  rep: '대표번호',
  safe: '안심번호',
  tollfree: '수신자 부담',
};

/** 화면 안에서 묻는 확인 칸(브라우저 확인 창은 쓰지 않는다). */
export function ConfirmPanel({ label, text, action, disabled, onConfirm, onCancel }: {
  label: string;
  text: ReactNode;
  action: string;
  disabled?: boolean;
  onConfirm(): void;
  onCancel(): void;
}) {
  return (
    <div className="st-confirm" role="group" aria-label={label}>
      <p className="st-wrap">{text}</p>
      <div className="st-actions">
        <span className="st-gap" />
        <Button onClick={onCancel}>취소</Button>
        <Button variant="danger" disabled={disabled} onClick={onConfirm}>
          {action}
        </Button>
      </div>
    </div>
  );
}

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="st-nt-group" aria-label={title}>
      <h4>{title}</h4>
      {children}
    </section>
  );
}

/** 승인 받기 | 위임 두 칸짜리 고르기. 잠긴 줄은 까닭을 아래에. */
function PermissionRow({ label, value, locked, disabled, onPick }: {
  label: string;
  value: Permission;
  locked?: string;
  disabled?: boolean;
  onPick(p: Permission): void;
}) {
  const name = useId();
  return (
    <div className="st-nt-perm">
      <span className="st-nt-perm-label">{label}</span>
      <div className="st-nt-seg" role="radiogroup" aria-label={`${label} 발송 권한`}>
        {(['approve', 'delegate'] as const).map((p) => (
          <label key={p} className="st-nt-seg-item">
            <input type="radio" name={name} value={p} checked={value === p} disabled={!!locked || disabled} onChange={() => onPick(p)} />
            {p === 'approve' ? '승인 받기' : '위임'}
          </label>
        ))}
      </div>
      {locked && <p className="st-muted st-nt-perm-why">{locked}</p>}
    </div>
  );
}

/** 허용 번호 목록 · 더하기. 지우기는 순번 + 목록 판. 7개부터 끝자리 찾기 칸. */
function AllowList({ conn, busy, addError, onPatch }: {
  conn: NotifyConnection;
  busy: boolean;
  /** 더하기 칸의 서버 까닭(422 detail.field = allow_numbers_add). */
  addError: LlmError | null;
  onPatch(body: NotifyPatch): Promise<boolean>;
}) {
  const [text, setText] = useState('');
  const [query, setQuery] = useState('');
  const filterable = conn.allow_numbers.length > 6;
  const digits = query.replace(/\D/g, '');
  const shown = filterable && digits ? conn.allow_numbers.filter((a) => a.number_masked.replace(/\D/g, '').endsWith(digits)) : conn.allow_numbers;
  const add = async () => {
    if (await onPatch({ allow_numbers_add: [text.trim()] })) setText('');
  };
  return (
    <>
      {filterable && (
        <div className="st-filter-row">
          <input type="search" className="st-search st-nt-filter" aria-label="허용 번호 끝자리 찾기" placeholder="끝자리 찾기" value={query} onChange={(e) => setQuery(e.target.value)} />
          <span className="st-count">{`${shown.length} / ${conn.allow_numbers.length}개`}</span>
        </div>
      )}
      {conn.allow_numbers.length === 0 ? (
        <p className="st-muted">허용 번호가 없습니다. 시험 모드에서는 아무에게도 실제로 나가지 않습니다.</p>
      ) : (
        <ul className="st-nt-allow" aria-label="허용 번호">
          {shown.map((a) => (
            <li key={a.index}>
              <span className="st-nt-num">{a.number_masked}</span>
              {a.kind && <span className="st-muted">{KIND_LABEL[a.kind] ?? a.kind}</span>}
              {a.index === conn.test_sms_index && <span className="st-muted">· 시험 문자가 가는 번호</span>}
              <span className="st-gap" />
              <Button disabled={busy} onClick={() => onPatch({ allow_numbers_remove: [a.index], allow_numbers_version: conn.allow_numbers_version })}>
                빼기
              </Button>
            </li>
          ))}
        </ul>
      )}
      <div className="st-nt-addrow">
        <div className="st-nt-add">
          <input
            type="tel"
            className="st-search"
            aria-label="허용 번호 더하기"
            aria-invalid={addError ? true : undefined}
            placeholder="010-0000-0000"
            autoComplete="off"
            value={text}
            disabled={busy}
            onChange={(e) => setText(e.target.value)}
          />
          <Button disabled={busy || text.trim() === ''} onClick={add}>
            더하기
          </Button>
        </div>
        <ErrorLine error={addError} />
      </div>
    </>
  );
}

/** 뒤 작업이 채울 자리: 카카오톡 채널과 문안(잠김) · 받는 범위·차단 · AI 전화. */
function LaterGroups({ conn }: { conn: NotifyConnection }) {
  return (
    <>
      <Group title="카카오톡 채널과 문안">
        <Field label="카카오톡 채널">
          <input value={conn.kakao_channel ?? ''} placeholder="연결 안 됨" disabled readOnly />
        </Field>
        <p className="st-muted">{KAKAO_LOCKED} 그때까지 카카오톡으로 고른 것은 문자로 나갑니다.</p>
      </Group>
      <Group title="받는 범위 · 차단">
        <p className="st-muted">준비 중 — 걸려 온 전화·문자를 누구에게서 받을지와 차단 목록이 이 자리에 들어옵니다.</p>
      </Group>
      <Group title="AI 전화">
        <p className="st-muted">준비 중 — 음성 모델 키·음성·최대 통화 시간·시험 전화가 이 자리에 들어옵니다.</p>
      </Group>
    </>
  );
}

/** 서버 오류 → 묶음(칸 오류면 그 칸)마다의 글. */
function problemOf(e: unknown, group: string): { group: string; error: LlmError } {
  const detail = e instanceof ApiError ? (e.detail as { field?: unknown } | null) : null;
  const field = detail && typeof detail === 'object' && typeof detail.field === 'string' ? detail.field : null;
  return { group: field === 'allow_numbers_add' ? 'add' : group, error: toProblem(e) };
}

const sayCount = (n: number | undefined, unit: string) => (n === undefined ? '—' : `${n}${unit}`);

type Confirm = { kind: 'test_off' } | { kind: 'delegate'; field: 'agent_sms' | 'agent_call'; label: string };

/** 카드 아래 칸: 발신번호 · 시험 모드와 허용 번호 · 에이전트 발송 권한 · 상한, 그리고 뒤 작업이 채울 자리. */
export default function NotifyPolicy({ conn, locked = false, onChanged }: {
  conn: NotifyConnection;
  /** 진단·시험 문자가 도는 동안 참 — 모든 칸을 잠근다. */
  locked?: boolean;
  onChanged(): void;
}) {
  const [problem, setProblem] = useState<{ group: string; error: LlmError } | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState<Confirm | null>(null);

  /** 한 번만 보낸다. 실패하면 그 묶음 아래에 서버 글. 성공·실패 모두 목록을 다시 읽는다(409 판 바뀜이면 새 목록에서 다시 고르게). */
  async function patch(group: string, body: NotifyPatch): Promise<boolean> {
    setBusy(true);
    setProblem(null);
    setConfirm(null);
    try {
      await notifyApi.update(conn.id, body);
      return true;
    } catch (e) {
      setProblem(problemOf(e, group));
      return false;
    } finally {
      setBusy(false);
      onChanged();
    }
  }
  const errorOf = (group: string) => <ErrorLine error={problem?.group === group ? problem.error : null} />;
  const pick = (field: 'agent_sms' | 'agent_call', label: string) => (p: Permission) =>
    p === 'delegate' ? setConfirm({ kind: 'delegate', field, label }) : void patch('perm', { [field]: p });
  const toggleTest = () => (conn.test_mode ? setConfirm({ kind: 'test_off' }) : void patch('test', { test_mode: true }));
  const l = conn.limits;
  const off = busy || locked;
  const used = conn.used_today;

  return (
    <div className="st-nt-policy">
      <Group title="발신번호">
        <div className="ui-field">
          <select
            aria-label="발신번호"
            value={conn.sender_index ?? ''}
            disabled={off || conn.senders.length === 0}
            onChange={(e) => e.target.value !== '' && void patch('sender', { sender_index: Number(e.target.value) })}
          >
            {conn.sender_index === null && <option value="">고르지 않음</option>}
            {conn.senders.map((s) => (
              <option key={s.index} value={s.index}>
                {[s.label, s.number_masked, s.kind ? (KIND_LABEL[s.kind] ?? s.kind) : ''].filter(Boolean).join(' · ')}
              </option>
            ))}
          </select>
          <span className="ui-field-hint">
            {conn.senders.length === 0 ? '연결 테스트를 통과하면 승인된 발신번호를 고를 수 있습니다.' : '문자·전화를 이 번호로 보냅니다.'}
          </span>
        </div>
        {errorOf('sender')}
      </Group>

      <Group title="시험 모드 · 허용 번호">
        <label className="st-nt-switch">
          <input type="checkbox" role="switch" aria-label="시험 모드" checked={conn.test_mode} disabled={off || confirm !== null} onChange={toggleTest} />
          <span>{conn.test_mode ? '켜짐 — 허용 번호로만 실제로 나갑니다' : '꺼짐 — 받는 사람 누구에게나 실제로 나갑니다'}</span>
        </label>
        {confirm?.kind === 'test_off' && (
          <ConfirmPanel
            label="시험 모드 끄기 확인"
            text="시험 모드를 끄면 허용 번호가 아닌 사람에게도 실제로 나갑니다. 끌까요?"
            action="시험 모드 끄기"
            disabled={off}
            onConfirm={() => patch('test', { test_mode: false })}
            onCancel={() => setConfirm(null)}
          />
        )}
        <AllowList conn={conn} busy={off} addError={problem?.group === 'add' ? problem.error : null} onPatch={(body) => patch('test', body)} />
        {errorOf('test')}
      </Group>

      <Group title="에이전트 발송 권한">
        <p className="st-muted">「승인 받기」면 에이전트는 초안만 만들고 사람이 보냅니다. 「위임」이어도 시험 모드·근무시간·상한 검사는 그대로 받습니다.</p>
        <PermissionRow label="문자" value={conn.agent_sms} disabled={off} onPick={pick('agent_sms', '문자')} />
        <PermissionRow label="카카오톡" value={conn.agent_kakao} locked={KAKAO_LOCKED} onPick={() => undefined} />
        <PermissionRow label="전화" value={conn.agent_call} disabled={off} onPick={pick('agent_call', '전화')} />
        {confirm?.kind === 'delegate' && (
          <ConfirmPanel
            label="위임 확인"
            text={`${confirm.label} 발송을 위임으로 바꾸면 에이전트가 사람 확인 없이 보냅니다. 바꿀까요?`}
            action="위임으로 바꾸기"
            disabled={off}
            onConfirm={() => patch('perm', { [confirm.field]: 'delegate' })}
            onCancel={() => setConfirm(null)}
          />
        )}
        {errorOf('perm')}
      </Group>

      <details className="st-nt-group st-nt-limits">
        <summary>{`상한 — 하루 문자 ${sayCount(l.daily_sms_total, '건')} · 전화 ${sayCount(l.daily_calls_total, '통')} · 오늘 문자 ${sayCount(used?.sms, '건')} · 전화 ${sayCount(used?.call, '통')}`}</summary>
        <LimitsForm connectionId={conn.id} disabled={locked} onSaved={onChanged} />
      </details>

      <LaterGroups conn={conn} />
    </div>
  );
}
