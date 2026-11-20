// 칸에 적은 글 → 보낼 요청. 틀린 글은 보내지 않고 한국어 안내를 돌려준다. 스케줄 표와 간트차트 왼쪽 표가 같이 쓴다.
import type { Activity, ActivityFields, Kind, PredItem } from './scheduleApi';
import type { ColKey, ColumnDef } from './columns';
import { parse, ParseError } from './predecessors';
import type { ScheduleState } from './scheduleStore';

export type EditRequest = { patch: ActivityFields } | { preds: PredItem[] } | { error: string };

const DATE = /^(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})$/;

/** 2027.5.12 · 2027-05-12 · 2027/05/12 → 2027-05-12. 없는 날이면 null. */
export function isoDate(text: string): string | null {
  const m = DATE.exec(text);
  if (!m) return null;
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const probe = new Date(Date.UTC(y, mo - 1, d));
  if (probe.getUTCFullYear() !== y || probe.getUTCMonth() !== mo - 1 || probe.getUTCDate() !== d) return null;
  return `${m[1]}-${String(mo).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
}

const dateOrNull = (text: string, field: 'actual_start' | 'actual_finish'): EditRequest => {
  if (!text) return { patch: { [field]: null } };
  const iso = isoDate(text);
  return iso ? { patch: { [field]: iso } } : { error: `날짜 형식이 맞지 않습니다: ${text} (예 2027.05.12)` };
};

const DAYS = /^\d+$/;

function constraint(text: string): EditRequest {
  if (!text) return { patch: { constraint: null } };
  const m = /^(SNET|FNLT)\s+(\S+)$/i.exec(text);
  const date = m ? isoDate(m[2]) : null;
  if (!m || !date) return { error: `제약 형식이 맞지 않습니다: ${text} (예 SNET 2027.03.08)` };
  return { patch: { constraint: { type: m[1].toUpperCase() as 'SNET' | 'FNLT', date } } };
}

function progress(text: string): EditRequest {
  const n = Number(text);
  if (!text || !Number.isFinite(n) || n < 0 || n > 100) return { error: '진도는 0~100 사이 숫자로 넣어 주세요.' };
  return { patch: { progress: Math.round(n * 100) / 10000 } };
}

/** col 칸에 적은 text(앞뒤 공백 뺀 것)를 요청으로. */
export function toRequest(col: ColKey, raw: string): EditRequest {
  const text = raw.trim();
  switch (col) {
    case 'name':
      return text ? { patch: { name: text } } : { error: '이름을 넣어 주세요.' };
    case 'kind':
      return { patch: { kind: text as Kind } };
    case 'wbs':
      return { patch: { wbs: text } };
    case 'od':
      return DAYS.test(text) ? { patch: { od: Number(text) } } : { error: 'OD는 0 이상 정수로 넣어 주세요.' };
    case 'rd':
      if (!text) return { patch: { rd: null } };
      return DAYS.test(text) ? { patch: { rd: Number(text) } } : { error: 'RD는 0 이상 정수로 넣어 주세요.' };
    case 'actual_start':
    case 'actual_finish':
      return dateOrNull(text, col);
    case 'progress':
      return progress(text);
    case 'constraint':
      return constraint(text);
    case 'preds':
      try {
        return { preds: parse(text) };
      } catch (e) {
        if (e instanceof ParseError) return { error: e.message };
        throw e;
      }
    default:
      return { error: '이 칸은 고칠 수 없습니다.' };
  }
}

/** 적은 글을 요청으로 바꿔 일정 저장소로 보낸다. 틀린 글은 보내지 않고 알림. */
export async function commitCell(store: ScheduleState, a: Activity, col: ColumnDef, text: string): Promise<unknown> {
  const req = toRequest(col.key, text);
  if ('error' in req) return store.setNotice({ tone: 'error', text: req.error });
  return 'preds' in req ? store.setPredecessors(a.id, req.preds) : store.patchActivity(a.id, req.patch);
}
