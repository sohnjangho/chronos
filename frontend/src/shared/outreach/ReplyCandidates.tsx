// 현장 항목의 회신 후보(Task 104 — 설계 「그 요청에 이어 붙이고, 현장 항목의 회신 후보로 올린다(사람 확인)」). 그 항목에 이어진 받은
// 문자(GET …/outreach/replies?field_item_id= — 서버가 그 일정·그 항목 것만, 번호를 가린 글로 준다)를 카드 안에 보이고,
// [회신 칸에 넣기]는 메모 칸의 새 글(쓴 메모가 있으면 새 줄로 뒤에 붙임 — 덮지 않는다)을 onUse 로 넘길 뿐이다 — 저장·진행률·선택은
// 사람이 고르고 누른다(자동으로 반영하지 않는다). 줄마다 어느 요청의 답인지(요청 시각·묶음 번호)를 보인다.
// 현장 관리자에게는 그리지 않는다(그 길은 403). 후보가 없거나 읽지 못하면 아무것도 그리지 않는다. 셋이 넘으면 접고, 긴 글은 줄에서만 줄인다.
import { useEffect, useState } from 'react';
import { api } from '../api';
import Button from '../ui/Button';
import { useCanContact } from './contactKit';
import './contact.css';

export interface Reply {
  message_id: number; contact: { name: string; role_title: string }; text: string; at: string; answers: unknown[];
  /** 이어진 우리 요청(없으면 null). */
  request: { message_id: number; at: string; batch_id: number | null } | null;
}
interface Props {
  scheduleId: number;
  fieldItemId: number;
  /** 메모 칸의 지금 글. */
  current: string;
  /** 메모 칸의 새 글(저장하지 않는다). */
  onUse(memo: string): void;
  disabled?: boolean;
}
const SHOWN = 3;
const CUT = 120; // 줄에 보일 글 길이(누가·언제가 늘 보이게). [회신 칸에 넣기]는 전문을 넘긴다.
const KST_MS = 9 * 3_600_000;
/** 현장 항목 메모 칸 한도(서버 progress/field.py response_note max_length 와 같다). */
export const MEMO_MAX = 1000;

/** 비었으면 글로 채우고, 아니면 쓴 메모 뒤에 새 줄로 붙인다. max 를 넘으면 붙이는 글을 「…」로 줄인다(쓴 글은 그대로, 자리가 없으면 그대로). */
export function addToMemo(current: string, text: string, max = MEMO_MAX): string {
  const base = current.trim() ? `${current.replace(/\s+$/, '')}\n` : '';
  const room = max - base.length;
  if (room <= 1) return current;
  return base + (text.length > room ? `${text.slice(0, room - 1)}…` : text);
}

/** 「08:40」, 오늘(KST)이 아니면 「11월 25일 09:30」. */
function when(iso: string): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return '';
  const k = new Date(t + KST_MS);
  const today = new Date(Date.now() + KST_MS);
  const hm = `${String(k.getUTCHours()).padStart(2, '0')}:${String(k.getUTCMinutes()).padStart(2, '0')}`;
  const same = k.getUTCFullYear() === today.getUTCFullYear() && k.getUTCMonth() === today.getUTCMonth() && k.getUTCDate() === today.getUTCDate();
  return same ? hm : `${k.getUTCMonth() + 1}월 ${k.getUTCDate()}일 ${hm}`;
}

function useReplies(scheduleId: number, fieldItemId: number, on: boolean): Reply[] {
  const [rows, setRows] = useState<Reply[]>([]);
  useEffect(() => {
    if (!on) return;
    let live = true;
    api<Reply[]>(`/api/schedules/${scheduleId}/outreach/replies?field_item_id=${fieldItemId}`)
      .then((r) => live && setRows(Array.isArray(r) ? r : []))
      .catch(() => live && setRows([]));
    return () => {
      live = false;
    };
  }, [scheduleId, fieldItemId, on]);
  return rows;
}

/** 「 · 07:10 요청의 답」, 묶음이면 「 · 09:30 요청(묶음 #21)의 답」. 이어진 요청이 없으면 빈 글. */
function askedLine(r: Reply): string {
  if (!r.request) return '';
  return ` · ${when(r.request.at)} 요청${r.request.batch_id !== null ? `(묶음 #${r.request.batch_id})` : ''}의 답`;
}

export default function ReplyCandidates({ scheduleId, fieldItemId, current, onUse, disabled }: Props) {
  const can = useCanContact();
  const rows = useReplies(scheduleId, fieldItemId, can);
  const [all, setAll] = useState(false);
  if (!can || rows.length === 0) return null;
  const shown = all ? rows : rows.slice(0, SHOWN);
  return (
    <section className="rc-box" aria-label="문자 회신 후보">
      <ul className="rc-list">
        {shown.map((r) => (
          <li key={r.message_id} className="rc-line">
            <span className="rc-text">
              {'문자 회신 후보: '}
              <span className="rc-quote">{`"${r.text.length > CUT ? `${r.text.slice(0, CUT - 1)}…` : r.text}"`}</span>
              <span className="rc-who">{` — ${r.contact.name} ${when(r.at)}`}</span>
              {r.request && <span className="rc-asked">{askedLine(r)}</span>}
            </span>
            <Button className="rc-use" disabled={disabled} onClick={() => onUse(addToMemo(current, r.text))}>
              회신 칸에 넣기
            </Button>
          </li>
        ))}
      </ul>
      {rows.length > SHOWN && (
        <button type="button" className="rc-more" aria-expanded={all} onClick={() => setAll((a) => !a)}>
          {all ? '회신 후보 접기' : `회신 후보 ${rows.length}건 모두 보기`}
        </button>
      )}
    </section>
  );
}
