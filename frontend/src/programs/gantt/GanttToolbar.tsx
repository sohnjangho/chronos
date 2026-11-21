// 간트 도구줄(설계 8-2): 층 · 확대·축소 · 맞춤 · 선택 맞춤 · Data Date · 오늘 · 앞뒤 이동 · 묶는 기준 · 모두 펼치기·접기 ·
// 열 · 범례 · 되돌리기·다시 하기 · CSV·그림 내보내기. 꺼진 단추는 title 로 까닭을 말한다. 좁으면 줄을 바꾼다.
import Button from '../../shared/ui/Button';
import History from '../../shared/schedule/History';
import type { ColKey } from '../../shared/schedule/columns';
import { ColumnPanel } from '../../shared/schedule/FilterPanel';
import Popover from '../../shared/schedule/Popover';
import { GANTT_PALETTE, type GanttColors } from './ganttColors';
import type { GroupBy } from './grouping';
import type { Layers } from './model';

export interface ToolbarProps {
  layers: Layers;
  onLayer(key: keyof Layers): void;
  colors: GanttColors;
  onColor(key: 'plan' | 'actual' | 'cpm', hex: string): void;
  onLinkOpacity(opacity: number): void;
  onResetColors(): void;
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
  /** 기한 세로선 이름(분야 표시 설정, 예: 납기·준공 기한). 범례가 같은 말을 쓴다. */
  deadlineLabel: string;
}

const LAYERS: { key: keyof Layers; label: string; swatch: string }[] = [
  { key: 'plan', label: 'Plan', swatch: 'is-plan' },
  { key: 'actual', label: 'Actual·예측', swatch: 'is-actual' },
  { key: 'cpm', label: 'CPM', swatch: 'is-cpm' },
];

function LayerChips({ layers, onLayer }: Pick<ToolbarProps, 'layers' | 'onLayer'>) {
  return (
    <>
      {LAYERS.map((l) => {
        const off = l.key === 'cpm' && !layers.actual;
        return (
          <button
            key={l.key}
            type="button"
            className="gt-chip"
            aria-pressed={off ? false : layers[l.key]}
            disabled={off}
            title={off ? 'CPM 층은 Actual·예측 막대 위에 그립니다. Actual·예측을 켜세요.' : undefined}
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

const LEGEND: [string, string][] = [
  ['is-plan', 'Plan(위 칸) — 지금 일정을 실적 없이 계산한 날짜(Plan 시작~종료). 고치거나 승인하면 바뀝니다'],
  ['is-actual', 'Actual·예측(아래 칸) — 진한 초록은 실적: 실제 시작~실제 종료, 진행 중이면 Data Date 까지'],
  ['is-forecast', '예측 — 옅은 점선 막대: 실적이 끝난 곳(시작 전이면 시작)부터 지금 계산의 종료(EF)까지. 지연은 예측 막대가 Plan 막대보다 길어져 보입니다'],
  ['is-cpm', '크리티컬(CPM 층) — 예측 막대를 빨강으로(지금 계산에서 여유 0 이하). 관계선도 아래 칸을 이으며 두 끝이 모두 크리티컬이면 빨강'],
  ['is-float', '여유 꼬리(CPM 층) — 예측 막대 끝(EF)에서 LF(늦은 종료)까지 아래 칸 밑의 회색 줄'],
  ['is-ms', '마일스톤 ◆(위 칸 Plan · 아래 칸 실적이나 예측) · 기한 ◇(마일스톤 기한 조건) · {deadline} 빨간 점선(finish_by 조건)'],
  ['is-data', 'Data Date 주황 세로선 · 오늘 파란 세로선'],
  ['is-weekend', '쉬는 날 — 근무 달력(주 5일 토·일, 주 6일 일요일) 음영. 공휴일은 일정 자료에 없어 그리지 않는다'],
  ['is-blocked', '작업 금지 기간 — 빨간 빗금 띠와 위 이름표 「<꼬리표> 작업 금지」(조건의 금지 기간). 그 꼬리표를 단 줄은 더 진하게'],
  ['is-ghost', '미리 보기 점선 — 미리 보기 전(저장된) 자리, 바뀐 칸에만(Plan 칸·아래 칸 따로). 끄는 중의 새 자리'],
  ['is-lane', '자원 줄 — 그 자원을 쓰는 액티비티 기간(겹치면 진함). 날마다 필요량·용량 넘침은 서버가 계산해 주면 그린다(다음 묶음)'],
];

function Legend({ deadline }: { deadline: string }) {
  return (
    <ul className="sch-pop-body gt-legend">
      {LEGEND.map(([cls, text]) => (
        <li key={cls}>
          <span className={`gt-swatch ${cls}`} aria-hidden="true" />
          {text.replace('{deadline}', deadline)}
        </li>
      ))}
    </ul>
  );
}

const COLOR_ROWS: { key: 'plan' | 'actual' | 'cpm'; label: string }[] = [
  { key: 'plan', label: 'Plan' },
  { key: 'actual', label: 'Actual·예측' },
  { key: 'cpm', label: 'CPM (크리티컬)' },
];

function ColorPanel({
  colors,
  onColor,
  onLinkOpacity,
  onReset,
}: {
  colors: GanttColors;
  onColor(k: 'plan' | 'actual' | 'cpm', hex: string): void;
  onLinkOpacity(op: number): void;
  onReset(): void;
}) {
  return (
    <div className="sch-pop-body gt-color-panel">
      {COLOR_ROWS.map((row) => (
        <div key={row.key} className="gt-color-row">
          <span className="gt-color-label">{row.label}</span>
          <div className="gt-color-dots">
            {GANTT_PALETTE.map((c) => {
              const active = colors[row.key] === c.hex;
              return (
                <button
                  key={c.hex}
                  type="button"
                  className={`gt-color-dot${active ? ' is-on' : ''}`}
                  style={{ background: c.hex }}
                  aria-label={`${row.label} ${c.name}`}
                  aria-pressed={active}
                  title={c.name}
                  onClick={() => onColor(row.key, c.hex)}
                />
              );
            })}
          </div>
        </div>
      ))}
      <label className="gt-color-row">
        <span className="gt-color-label">{`크리티컬 연결선 투명도 (${Math.round(colors.linkOpacity * 100)}%)`}</span>
        <input
          type="range"
          min={10}
          max={100}
          step={5}
          value={Math.round(colors.linkOpacity * 100)}
          aria-label="크리티컬 연결선 투명도"
          onChange={(e) => onLinkOpacity(Number(e.target.value) / 100)}
        />
      </label>
      <Button onClick={onReset}>기본색 복원</Button>
    </div>
  );
}

export default function GanttToolbar(p: ToolbarProps) {
  return (
    <div role="toolbar" aria-label="간트 도구" className="sch-toolbar gt-toolbar">
      <div className="sch-rib-group">
        <div className="sch-rib-items">
          <LayerChips layers={p.layers} onLayer={p.onLayer} />
          <Popover button="색상" label="색상">
            {() => <ColorPanel colors={p.colors} onColor={p.onColor} onLinkOpacity={p.onLinkOpacity} onReset={p.onResetColors} />}
          </Popover>
        </div>
        <span className="sch-rib-label">층·색상</span>
      </div>
      <div className="sch-rib-group">
        <div className="sch-rib-items">
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
        </div>
        <span className="sch-rib-label">화면·이동</span>
      </div>
      <div className="sch-rib-group">
        <div className="sch-rib-items">
          {(['wbs', 'resource'] as const).map((by) => (
            <button key={by} type="button" className="gt-chip" aria-pressed={p.groupBy === by} onClick={() => p.onGroupBy(by)}>
              {by === 'wbs' ? 'WBS' : '자원'}
            </button>
          ))}
          <Button onClick={p.onExpandAll}>모두 펼치기</Button>
          <Button onClick={p.onCollapseAll}>모두 접기</Button>
        </div>
        <span className="sch-rib-label">묶는 기준</span>
      </div>
      <span className="sch-gap" />
      <div className="sch-rib-group">
        <div className="sch-rib-items">
          <Popover button="열" label="열" align="right">
            {() => <ColumnPanel visible={p.visible} onVisible={p.onVisible} />}
          </Popover>
          <Popover button="범례" label="범례" align="right">
            {() => <Legend deadline={p.deadlineLabel} />}
          </Popover>
          <History />
          <Button onClick={p.onCsv}>CSV 내보내기</Button>
          <Button onClick={p.onImage}>그림 내보내기</Button>
        </div>
        <span className="sch-rib-label">보기·이력·내보내기</span>
      </div>
    </div>
  );
}
