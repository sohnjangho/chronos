// 공정률 화면 글: 서버 값(퍼센트·일수·날짜)을 글로 바꾸기만 한다(계산 없음). 빼기 부호는 U+2212.

const MINUS = '−';

/** 소수 digits 자리, 양수는 +, 음수는 −, 0 은 부호 없이. */
export function signed(v: number, digits = 1): string {
  const text = Math.abs(v).toFixed(digits);
  if (Number(text) === 0) return text;
  return `${v > 0 ? '+' : MINUS}${text}`;
}

/** 퍼센트 글(소수 1자리, 빼기 부호). */
export const pct = (v: number) => (v < 0 ? `${MINUS}${Math.abs(v).toFixed(1)}` : v.toFixed(1));

/** 2027-03-03 → 03.03. 없으면 —. */
export const md = (iso: string | null | undefined) => (iso ? iso.slice(5).replace('-', '.') : '—');

/** 근무일 차이 → "+1일" / "−2일" / "0일". */
export const days = (n: number) => `${signed(n, 0)}일`;

const WEIGHT_MODES: Record<string, string> = { duration: '기간 비례', manual: '직접 입력' };

/** 사람이 읽는 가중치 방식. 모르는 값은 그대로. */
export const weightModeLabel = (mode: string) => WEIGHT_MODES[mode] ?? mode;
