import { ApiError } from '../../shared/api';
import Badge, { type Tone } from '../../shared/ui/Badge';
import Field from '../../shared/ui/Field';
import type { LlmError } from './model';
import type { DiagnosisStep } from './notifyApi';

/** 잡은 오류를 서버 글과 코드로. ApiError 가 아니면 일반 글(오류 내용은 보이지도 기록하지도 않는다). */
export function toProblem(e: unknown): LlmError {
  return e instanceof ApiError
    ? { code: e.code, message: e.message }
    : { code: 'unknown', message: '요청을 처리할 수 없습니다.' };
}

/** 저장은 됐지만 저장할 때 한 서버의 연결 시험이 실패했을 때의 글(서버 글을 그대로 붙인다). */
export const savedButFailed = (error: LlmError): LlmError => ({
  code: error.code,
  message: `저장했지만 연결 시험에 실패했습니다: ${error.message}`,
});

/** 서버의 한국어 글을 그대로, 옆에 코드. */
export function ErrorLine({ error }: { error: LlmError | null | undefined }) {
  if (!error) return null;
  return (
    <p className="st-error" role="alert">
      <span>{error.message}</span>
      <span className="st-code">{error.code}</span>
    </p>
  );
}

/**
 * API 키 칸. 비밀번호 칸이고 브라우저가 저장된 비밀번호를 채우지 않게 한다.
 * 값은 부르는 화면의 상태에만 있고, 저장·취소·닫기 때 비운다.
 */
export function SecretField({
  label,
  value,
  onChange,
  disabled,
  autoFocus,
  hint,
}: {
  label: string;
  value: string;
  onChange(v: string): void;
  disabled?: boolean;
  /** 새로 나타난 칸이면 포커스를 옮긴다. */
  autoFocus?: boolean;
  /** 칸 아래 작은 안내 줄. */
  hint?: string;
}) {
  return (
    <Field label={label} hint={hint}>
      <input
        type="password"
        autoComplete="new-password"
        spellCheck={false}
        value={value}
        disabled={disabled}
        autoFocus={autoFocus}
        onChange={(e) => onChange(e.target.value)}
      />
    </Field>
  );
}

/** 보내기 요청이 200 으로 끝나지 않았는데 분명한 거절도 아닌 것(끊김·5xx·읽을 수 없는 응답) — 갔는지 모른다. */
export const uncertain = (e: unknown) => !(e instanceof ApiError) || e.status === 0 || e.status >= 500 || e.code === 'bad_response';

/** 걸음 줄 하나(알림 연결 P1~P4 · 음성 P5~P14 가 같은 꼴). */
export type StepRow = Omit<DiagnosisStep, 'id'> & { id: string };

/** 판정은 칸으로만: 건너뜀 → 확인 필요(보냈는지·걸렸는지 모름) → 확인 중(아직 접수) → OK / FAIL. */
function verdict(step: StepRow): { tone: Tone; text: string } {
  if (step.skipped) return { tone: 'neutral', text: '건너뜀' };
  if (step.maybe_sent) return { tone: 'warning', text: '확인 필요' };
  if (step.pending) return { tone: 'warning', text: '확인 중' };
  return step.ok ? { tone: 'success', text: 'OK' } : { tone: 'danger', text: 'FAIL' };
}

/** more = 접어 둘 기계 세부(코드·data). badge = 판정 대신 보일 것(아직 안 돌린 줄). */
export function StepLine({ s, more = [], badge }: { s: StepRow; more?: string[]; badge?: { tone: Tone; text: string } }) {
  const v = badge ?? verdict(s);
  const folded = [...s.notes, ...more];
  return (
    <li>
      <div className="st-nt-step">
        <b className="st-nt-step-id">{s.id}</b>
        <Badge tone={v.tone}>{v.text}</Badge>
        <span className="st-nt-step-text">
          <span className="st-muted">{s.label}</span>
          {` — ${s.detail}`}
        </span>
        {s.latency_ms !== null && <span className="st-count">{`${s.latency_ms}ms`}</span>}
      </div>
      {folded.length > 0 && (
        <details className="st-nt-notes">
          <summary>{`메모 ${folded.length}줄`}</summary>
          {folded.map((n, i) => (
            <div key={i}>{n}</div>
          ))}
        </details>
      )}
    </li>
  );
}
