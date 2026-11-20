// 왼쪽: [대기 n][결정됨][자동 적용 n] · 승인 수준 · 목록. 자동 적용 줄에는 [되돌리기](R4).
import { ageText } from '../../os/ApprovalWidget';
import Badge from '../../shared/ui/Badge';
import Button from '../../shared/ui/Button';
import Tabs from '../../shared/ui/Tabs';
import { MODES, STATUS, reasonLabel, type ApprovalItem, type Group, type Mode } from './apvApi';
import { reasonTone } from './format';

/** 자동 적용 줄을 되돌릴 수 있는가. 못 하면 까닭(불러오는 중이면 빈 글). */
export type Revert = { ok: true } | { ok: false; why: string };

interface Props {
  tab: Group;
  onTab(tab: Group): void;
  counts: { pending: number | null; auto: number | null };
  mode: Mode | null;
  items: ApprovalItem[] | null;
  selected: number | null;
  onSelect(id: number): void;
  revertOf(item: ApprovalItem): Revert;
  onRevert(item: ApprovalItem): void;
}

const MODE_HINT: Record<Mode, string> = {
  all: '에이전트가 일정을 바꿀 때마다 승인을 받습니다.',
  important: '준공·주요 날짜·크리티컬 패스·조건·구조가 바뀌거나 조건을 어길 때만 승인을 받습니다. 나머지는 자동 적용되고 「자동 적용」에서 되돌릴 수 있습니다.',
  auto: '조건을 어길 때만 승인을 받습니다. 나머지는 자동 적용되고 「자동 적용」에서 되돌릴 수 있습니다.',
};

const EMPTY: Record<Group, string> = { pending: '승인을 기다리는 건이 없습니다.', decided: '결정한 건이 없습니다.', auto: '자동 적용한 건이 없습니다.' };

function subLine(it: ApprovalItem): string {
  if (it.status === 'pending') return `${it.requested_by} 요청 · ${ageText(it.created_at)}`;
  if (it.status === 'auto') return [it.version === null ? '' : `버전 ${it.version}`, ageText(it.created_at)].filter(Boolean).join(' · ');
  return [STATUS[it.status], it.decided_by ?? '', it.decided_at ? ageText(it.decided_at) : ''].filter(Boolean).join(' · ');
}

function Row({ it, selected, onSelect, revert, onRevert }: { it: ApprovalItem; selected: boolean; onSelect(): void; revert: Revert | null; onRevert(): void }) {
  const first = it.reasons[0];
  return (
    <li className={`apv-li${selected ? ' is-on' : ''}`}>
      <button type="button" className="apv-li-main" aria-current={selected ? 'true' : undefined} onClick={onSelect}>
        {first && <Badge tone={reasonTone(first)}>{reasonLabel(first)}</Badge>}
        <b className="apv-li-title" title={it.title}>
          {it.title}
        </b>
        <small className="apv-ellipsis">{subLine(it)}</small>
      </button>
      {revert && (
        <div className="apv-revert">
          <Button disabled={!revert.ok} onClick={onRevert}>
            되돌리기
          </Button>
          {!revert.ok && revert.why && <small className="apv-wrap">{revert.why}</small>}
        </div>
      )}
    </li>
  );
}

export default function ApprovalList({ tab, onTab, counts, mode, items, selected, onSelect, revertOf, onRevert }: Props) {
  const label = (name: string, n: number | null) => (n === null ? name : `${name} ${n}`);
  return (
    <aside className="apv-side">
      <div className="apv-seg">
        <Tabs
          label="승인 건 묶음"
          value={tab}
          onChange={(t) => onTab(t as Group)}
          items={[
            { id: 'pending', label: label('대기', counts.pending) },
            { id: 'decided', label: '결정됨' },
            { id: 'auto', label: label('자동 적용', counts.auto) },
          ]}
        />
      </div>
      {mode && (
        <p className="apv-mode">
          승인 수준: <b>{MODES[mode]}</b> (관리자 설정)
        </p>
      )}
      {items === null && <p className="apv-empty">불러오는 중…</p>}
      {items?.length === 0 && <p className="apv-empty">{EMPTY[tab]}</p>}
      {items && items.length > 0 && (
        <ul className="apv-list" aria-label="승인 건 목록">
          {items.map((it) => (
            <Row
              key={it.id}
              it={it}
              selected={it.id === selected}
              onSelect={() => onSelect(it.id)}
              revert={tab === 'auto' ? revertOf(it) : null}
              onRevert={() => onRevert(it)}
            />
          ))}
        </ul>
      )}
      {mode && <p className="apv-foot">{MODE_HINT[mode]}</p>}
    </aside>
  );
}
