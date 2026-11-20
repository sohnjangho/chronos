import { ApiError } from '../../shared/api';
import Field from '../../shared/ui/Field';
import type { LlmError } from './model';

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
}: {
  label: string;
  value: string;
  onChange(v: string): void;
  disabled?: boolean;
  /** 새로 나타난 칸이면 포커스를 옮긴다. */
  autoFocus?: boolean;
}) {
  return (
    <Field label={label}>
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
