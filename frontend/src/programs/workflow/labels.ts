// 서버 이름(도구·프로그램·상태)을 화면 글로, 시간·토큰을 짧은 글로. 모르는 이름은 받은 그대로 보인다.
import { getProgram, resolveProgram } from '../../os/registry';

const TOOLS: Record<string, string> = {
  'generate.extract_conditions': '조건 뽑기',
  'generate.run': '일정 만들기',
  'ask.questionnaire': '질문 만들기',
  'ask.fill_answers': '질문지 답 채우기',
  'out.submit_change': '저장 요청',
  'schedule.read': '일정 읽기',
  'calc.cpm': '경로 계산',
  'harness.check': '조건 점검',
  'ui.open_window': '창 열기',
};
export const toolLabel = (tool: string) => TOOLS[tool] ?? tool;

/** 도구가 속한 프로그램 이름(없으면 뒷단 도구). 옛 단계의 없어진 id(일정판 schedule)는 지금 프로그램 이름으로. */
export const programLabel = (program: string | null) =>
  program === null ? '뒷단 도구' : (getProgram(resolveProgram(program).id)?.name ?? program);

export const STEP_STATUS: Record<string, string> = { running: '실행 중', done: '완료', failed: '실패', stopped: '멈춤', pending: '대기' };
export const stepStatus = (s: string) => STEP_STATUS[s] ?? s;

const CIRCLED = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳';
export const circled = (n: number) => (n >= 1 && n <= CIRCLED.length ? CIRCLED[n - 1] : `${n}.`);

/** 200 → "0.2초", 41000 → "41초", 125000 → "2분 5초". */
export function seconds(ms: number): string {
  const s = ms / 1000;
  if (s < 10) return `${Math.round(s * 10) / 10}초`;
  if (s < 60) return `${Math.round(s)}초`;
  const m = Math.floor(s / 60);
  const rest = Math.round(s - m * 60);
  return rest ? `${m}분 ${rest}초` : `${m}분`;
}

/** 950 → "950", 21400 → "21.4K", 480000 → "480K". */
export function tokens(n: number): string {
  if (n < 1000) return String(n);
  const k = n / 1000;
  return `${k < 100 ? Math.round(k * 10) / 10 : Math.round(k)}K`;
}

export const cost = (c: number | null) => (c === null ? '—' : `$${c.toFixed(2)}`);

/** 오늘이면 "오늘 21:40", 어제면 "어제 21:40", 아니면 "11.18". */
export function when(iso: string, now = new Date()): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const two = (n: number) => String(n).padStart(2, '0');
  const hm = `${two(d.getHours())}:${two(d.getMinutes())}`;
  const day = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((day(now) - day(d)) / 86_400_000);
  if (diff === 0) return `오늘 ${hm}`;
  if (diff === 1) return `어제 ${hm}`;
  return `${two(d.getMonth() + 1)}.${two(d.getDate())}`;
}
