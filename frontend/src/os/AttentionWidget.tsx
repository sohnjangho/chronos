import type { CSSProperties } from 'react';
import { useApprovals } from './approvals';
import { reasonText, useAttention } from './attention';
import { useCurrentSchedule } from './currentSchedule';
import { useWindows } from './windowStore';

const BADGE = { danger: '위험', warning: '주의' } as const;

// 색·글꼴은 tokens.css 변수만 쓴다. 바탕은 .os-widget(승인 대기 위젯과 같은 모양)을 그대로 쓰고 위치만 오른쪽 옆으로 옮긴다.
const S: Record<string, CSSProperties> = {
  note: { margin: '8px 0 0', color: 'var(--fg-muted)', fontSize: 'var(--fs-13)' },
  list: { maxHeight: 264, overflowY: 'auto' },
  item: { flexDirection: 'column', gap: 2, minWidth: 0 },
  head: { display: 'flex', gap: 8, alignItems: 'center', minWidth: 0 },
  badge: { flex: 'none', padding: '0 8px', borderRadius: 999, fontSize: 'var(--fs-12)', fontWeight: 700, lineHeight: '20px' },
  reason: { color: 'var(--fg-muted)', fontSize: 'var(--fs-12)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
};
// 승인 대기 위젯(.os-widget: left 24, 폭 250) 오른쪽 옆. 승인 대기가 없어 그 위젯이 숨으면 왼쪽 끝으로 간다.
const LEFT = 24;
const APPROVAL_WIDTH = 250;
const GAP = 16;

const TONE = {
  danger: { background: 'var(--tone-danger-bg)', color: 'var(--danger-text)' },
  warning: { background: 'var(--tone-warning-bg)', color: 'var(--warning-text)' },
  info: { background: 'var(--tone-info-bg)', color: 'var(--tone-info-fg)' },
} as const;

/**
 * 바탕화면 「주의할 일정」 위젯(승인 대기 위젯 옆). ok 가 아닌 일정과 관리 포인트가 바뀐 일정(계획 5 — 「포인트 바뀜 n」 배지,
 * 등급은 그대로)과 사진 사람 판독 대기가 있는 일정(「사람 판독 n」 배지, PM 11-24)을 줄로 보이고, 누르면 그 일정의 일정판을
 * (사람 판독 대기가 있으면 공정률 창의 사람 판독 목록을) 연다.
 * 목록이 길면 위젯 안에서 세로로 스크롤한다.
 */
export default function AttentionWidget() {
  const state = useAttention();
  const open = useWindows((s) => s.open);
  const approvalShown = useApprovals((s) => s.pending > 0);
  const items = Array.isArray(state)
    ? state.filter((i) => i.level !== 'ok' || (i.points_changed ?? 0) > 0 || (i.human_read_wait ?? 0) > 0)
    : [];
  return (
    <section className="os-widget" style={{ left: approvalShown ? LEFT + APPROVAL_WIDTH + GAP : LEFT }} aria-label="주의할 일정">
      <div className="os-widget-title">{Array.isArray(state) ? `주의할 일정 ${items.length}` : '주의할 일정'}</div>
      {state === null && <p style={S.note}>불러오는 중…</p>}
      {state === 'error' && <p style={S.note}>불러오지 못했습니다</p>}
      {Array.isArray(state) && items.length === 0 && <p style={S.note}>주의할 일정이 없습니다</p>}
      <ul className="os-widget-list" style={S.list}>
        {items.map((i) => {
          const level = i.level === 'ok' ? null : i.level;
          const changed = i.points_changed ?? 0;
          const humanWait = i.human_read_wait ?? 0;
          return (
            <li key={i.id}>
              <button
                type="button"
                className="os-widget-item"
                style={S.item}
                onClick={() => {
                  useCurrentSchedule.getState().setCurrent({ id: i.id, name: i.name });
                  // 사람 판독 대기가 있으면 그 일정의 현장 허브 → 사진 → 사람 판독 목록을 연다(PM 11-24)
                  if (humanWait > 0) open('progress', { id: String(i.id), view: 'field', tab: 'human-read' });
                  else open('schedule-table', { id: String(i.id) });
                }}
              >
                <span style={S.head}>
                  <span className="os-widget-name">{i.name}</span>
                  {level && <span style={{ ...S.badge, ...TONE[level] }}>{BADGE[level]}</span>}
                  {changed > 0 && <span style={{ ...S.badge, ...TONE.info }}>{`포인트 바뀜 ${changed}`}</span>}
                  {humanWait > 0 && <span style={{ ...S.badge, ...TONE.info }}>{`사람 판독 ${humanWait}`}</span>}
                </span>
                <span style={S.reason}>{reasonText(i)}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
