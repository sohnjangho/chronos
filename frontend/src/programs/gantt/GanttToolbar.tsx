// 간트 도구줄(설계 8-2): 층 · 확대·축소 · 맞춤 · 선택 맞춤 · Data Date · 오늘 · 앞뒤 이동 · 묶는 기준 · 모두 펼치기·접기 ·
// 열 · 범례 · 되돌리기·다시 하기 · CSV·그림 내보내기. 꺼진 단추는 title 로 까닭을 말한다. 좁으면 줄을 바꾼다.
import Button from '../../shared/ui/Button';
import History from '../../shared/schedule/History';
import { COLUMNS, type ColKey } from '../../shared/schedule/columns';
import Popover from '../../shared/schedule/Popover';
import type { GroupBy } from './grouping';
import type { Layers } from './model';

export interface ToolbarProps {
  layers: Layers;
  onLayer(key: keyof Layers): void;
  groupBy: GroupBy;
  onGroupBy(by: GroupBy): void;
  visible: ColKey[];
  onVisible(keys: ColKey[]): void;
  hasSelection: boolean;
  hasDataDate: boolean;
  onZoom(f: number): void;
  onFit(): void;
  onFitSelected(): void;
  onDataDate(): void;
  onToday(): void;
  onPage(dir: 1 | -1): void;
  onExpandAll(): void;
  onCollapseAll(): void;
  onCsv(): void;
  onImage(): void;
}

const LAYERS: { key: keyof Layers; label: string; swatch: string }[] = [
  { key: 'plan', label: 'Plan', swatch: 'is-plan' },
  { key: 'actual', label: 'Actual', swatch: 'is-actual' },
  { key: 'cpm', label: 'CPM', swatch: 'is-cpm' },
];

function LayerChips({ layers, onLayer }: Pick<ToolbarProps, 'layers' | 'onLayer'>) {
  return (
    <>
      {LAYERS.map((l) => {
        const off = l.key === 'cpm' && !layers.plan;
        return (
          <button
            key={l.key}
            type="button"
            className="gt-chip"
            aria-pressed={layers[l.key]}
            disabled={off}
            title={off ? 'CPM 층은 Plan 막대 위에 그립니다. Plan 을 켜세요.' : undefined}
            onClick={() => onLayer(l.key)}
          >
            <span className={`gt-swatch ${l.swatch}`} aria-hidden="true" />
            {l.label}
          </button>
        );
      })}
    </>
  );
}

function ColumnPanel({ visible, onVisible }: Pick<ToolbarProps, 'visible' | 'onVisible'>) {
  const flip = (k: ColKey) => onVisible(visible.includes(k) ? visible.filter((v) => v !== k) : [...visible, k]);
  return (
    <div className="sch-pop-body gt-cols">
      {COLUMNS.filter((c) => c.key !== 'id' && c.key !== 'name').map((c) => (
        <label key={c.key} className="sch-check">
          <input type="checkbox" checked={visible.includes(c.key)} onChange={() => flip(c.key)} />
          {c.header}
        </label>
      ))}
    </div>
  );
}

const LEGEND: [string, string][] = [
  ['is-plan', 'Plan 막대 — 지금 일정을 실적 없이 계산한 날짜(Plan 시작~종료). 고치거나 승인하면 바뀐다. 앞쪽 진한 부분이 진도'],
  ['is-cpm', '크리티컬(CPM 층) — 여유 0 이하. 관계선도 CPM 층에서 그리며, 두 끝이 모두 크리티컬이면 빨강'],
  ['is-float', '여유 꼬리(CPM 층) — Plan 막대 끝에서 LF(늦은 종료)까지 막대 아래 회색 줄'],
  ['is-actual', 'Actual — 막대 아래 초록 줄(시작~종료, 끝나지 않았으면 Data Date 까지)'],
  ['is-ms', '마일스톤 ◆ · 기한 ◇(마일스톤 기한 조건) · 준공 기한 빨간 점선(finish_by 조건)'],
  ['is-data', 'Data Date 주황 세로선 · 오늘 파란 세로선'],
  ['is-weekend', '쉬는 날 — 근무 달력(주 5일 토·일, 주 6일 일요일) 음영. 공휴일은 일정 자료에 없어 그리지 않는다'],
  ['is-blocked', '작업 금지 기간 — 옅은 빨간 음영(조건의 금지 기간)'],
  ['is-ghost', '미리 보기 점선 — 조건·규칙 미리 보기 전 자리, 끄는 중의 새 자리'],
  ['is-lane', '자원 줄 — 그 자원을 쓰는 액티비티 기간(겹치면 진함). 날마다 필요량·용량 넘침은 서버가 계산해 주면 그린다(다음 묶음)'],
];

function Legend() {
  return (
    <ul className="sch-pop-body gt-legend">
      {LEGEND.map(([cls, text]) => (
        <li key={cls}>
          <span className={`gt-swatch ${cls}`} aria-hidden="true" />
          {text}
        </li>
      ))}
    </ul>
  );
}

const Sep = () => <span className="sch-sep" aria-hidden="true" />;

export default function GanttToolbar(p: ToolbarProps) {
  return (
    <div role="toolbar" aria-label="간트 도구" className="sch-toolbar gt-toolbar">
      <LayerChips layers={p.layers} onLayer={p.onLayer} />
      <Sep />
      <Button aria-label="축소" onClick={() => p.onZoom(1 / 1.25)}>−</Button>
      <Button aria-label="확대" onClick={() => p.onZoom(1.25)}>+</Button>
      <Button onClick={p.onFit}>맞춤</Button>
      <Button disabled={!p.hasSelection} title={p.hasSelection ? undefined : '액티비티를 먼저 고르세요'} onClick={p.onFitSelected}>
        선택 맞춤
      </Button>
      <Button disabled={!p.hasDataDate} title={p.hasDataDate ? undefined : '이 일정에는 Data Date 가 없습니다'} onClick={p.onDataDate}>
        Data Date
      </Button>
      <Button onClick={p.onToday}>오늘</Button>
      <Button aria-label="이전 기간" onClick={() => p.onPage(-1)}>‹</Button>
      <Button aria-label="다음 기간" onClick={() => p.onPage(1)}>›</Button>
      <Sep />
      <span className="sch-muted">묶는 기준</span>
      {(['wbs', 'resource'] as const).map((by) => (
        <button key={by} type="button" className="gt-chip" aria-pressed={p.groupBy === by} onClick={() => p.onGroupBy(by)}>
          {by === 'wbs' ? 'WBS' : '자원'}
        </button>
      ))}
      <Button onClick={p.onExpandAll}>모두 펼치기</Button>
      <Button onClick={p.onCollapseAll}>모두 접기</Button>
      <span className="sch-gap" />
      <Popover button="열" label="열" align="right">
        {() => <ColumnPanel visible={p.visible} onVisible={p.onVisible} />}
      </Popover>
      <Popover button="범례" label="범례" align="right">
        {() => <Legend />}
      </Popover>
      <History />
      <Button onClick={p.onCsv}>CSV 내보내기</Button>
      <Button onClick={p.onImage}>그림 내보내기</Button>
    </div>
  );
}
