// 비교판 위 줄: 기준 ▾ / 비교 ▾ · 보기 [같은 차트][좌우 비교][차이 표] · [+ 만약에 복사본] · [복사본 버리기] · [이 안을 반영 (승인함으로)].
// 복사본 단추는 비교가 열린(open) 복사본일 때만. 낡음 배지도 열린 복사본에만(반영된 복사본은 늘 낡고, 제출·버린 것은 낼 수 없다) —
// 꺼진 반영 단추는 aria-describedby 로 그 배지를 가리킨다. 제출된 것은 「승인 대기」, 버린 것은 「버린 복사본」.
import { useId, type RefObject } from 'react';
import Badge from '../../shared/ui/Badge';
import Button from '../../shared/ui/Button';
import type { SideOut } from './compareApi';
import PlanPicker, { type PlanGroup } from './PlanPicker';

export type View = 'overlay' | 'side' | 'diff';
const VIEWS: [View, string][] = [
  ['overlay', '같은 차트'],
  ['side', '좌우 비교'],
  ['diff', '차이 표'],
];

interface Props {
  /** 보내기·버리기 뒤 포커스를 받는 위 줄. */
  focusRef: RefObject<HTMLDivElement | null>;
  /** 다시 읽는 중 — 앞 값의 복사본 단추는 끈다. */
  busy: boolean;
  base: string;
  other: string | null;
  labelOf(ref: string): string;
  groups: PlanGroup[];
  onBase(ref: string): void;
  onOther(ref: string): void;
  view: View;
  onView(v: View): void;
  /** 비교가 복사본이면 그 안(비교를 읽은 뒤). */
  copy: SideOut | null;
  onWhatIf(): void;
  onDiscard(): void;
  onSubmit(): void;
}

function CopyActions({ copy, busy, onDiscard, onSubmit }: Pick<Props, 'copy' | 'busy' | 'onDiscard' | 'onSubmit'>) {
  const staleId = useId();
  if (!copy) return null;
  const open = copy.status === 'open';
  const stale = open && copy.stale;
  return (
    <>
      {stale && (
        <span id={staleId}>
          <Badge tone="warning">기준 일정이 바뀌었습니다</Badge>
        </span>
      )}
      {copy.status === 'submitted' && <Badge tone="info">승인 대기</Badge>}
      {copy.status === 'discarded' && <Badge>버린 복사본</Badge>}
      {open && (
        <Button disabled={busy} onClick={onDiscard}>
          복사본 버리기
        </Button>
      )}
      {open && (
        <Button variant="primary" disabled={stale || busy} aria-describedby={stale ? staleId : undefined} onClick={onSubmit}>
          이 안을 반영 (승인함으로)
        </Button>
      )}
    </>
  );
}

export default function Toolbar(p: Props) {
  return (
    <div className="cmp-tools" role="group" aria-label="비교판 도구" ref={p.focusRef} tabIndex={-1}>
      <div className="cmp-tools-picks">
        <span className="cmp-muted">기준</span>
        <PlanPicker title="기준" tone="base" value={p.base} label={p.labelOf(p.base)} groups={p.groups} onPick={p.onBase} />
        <span className="cmp-muted">비교</span>
        {p.other ? (
          <PlanPicker title="비교" tone="other" value={p.other} label={p.labelOf(p.other)} groups={p.groups} onPick={p.onOther} />
        ) : (
          <span className="cmp-muted">읽는 중…</span>
        )}
      </div>
      <div className="cmp-seg" role="group" aria-label="보기">
        {VIEWS.map(([v, name]) => (
          <button key={v} type="button" aria-pressed={p.view === v} onClick={() => p.onView(v)}>
            {name}
          </button>
        ))}
      </div>
      <div className="cmp-grow" />
      <div className="cmp-tools-acts">
        <Button onClick={p.onWhatIf}>+ 만약에 복사본</Button>
        <CopyActions copy={p.copy} busy={p.busy} onDiscard={p.onDiscard} onSubmit={p.onSubmit} />
      </div>
    </div>
  );
}
