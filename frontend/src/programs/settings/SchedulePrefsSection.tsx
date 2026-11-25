import { useState } from 'react';
import { loadPref, savePref } from '../../os/prefs';
import { useSession } from '../../os/session';
import Button from '../../shared/ui/Button';
import { DEFAULT_GANTT_COLORS, GANTT_PALETTE, useGanttColors, type GanttColors } from '../../shared/schedule/ganttColors';

type ColorKey = 'plan' | 'actual' | 'cpm';

const COLOR_ROWS: { key: ColorKey; label: string }[] = [
  { key: 'plan', label: 'Plan (기준 계획)' },
  { key: 'actual', label: 'Actual · 예측' },
  { key: 'cpm', label: 'CPM (크리티컬 경로)' },
];

const LAYOUT_KEYS = [
  'schedule.table.widths',
  'schedule.table.rowHeight',
  'schedule.columns',
  'schedule.gantt.widths',
  'schedule.gantt.rowHeight',
  'schedule.gantt.leftWidth',
  'schedule.gantt.columns',
] as const;

/** 막대 종류(Plan · Actual · CPM)마다 색 점을 고르는 표. */
function SwatchTable({ colors, onPick }: { colors: GanttColors; onPick(key: ColorKey, hex: string): void }) {
  return (
    <div className="st-swatch-table">
      {COLOR_ROWS.map((row) => (
        <div key={row.key} className="st-swatch-row">
          <span className="st-swatch-label">{row.label}</span>
          <div className="st-swatch-dots" role="group" aria-label={`${row.label} 색상`}>
            {GANTT_PALETTE.map((c) => {
              const active = colors[row.key] === c.hex;
              return (
                <button
                  key={c.hex}
                  type="button"
                  className={`st-swatch-dot${active ? ' is-on' : ''}`}
                  style={{ backgroundColor: c.hex }}
                  aria-label={`${row.label} ${c.name}`}
                  aria-pressed={active}
                  title={c.name}
                  onClick={() => onPick(row.key, c.hex)}
                />
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

/** 「차트 · 표 기본값」: 간트 차트 막대 색상/투명도와 스케줄·간트 열 레이아웃 초기화. */
export default function SchedulePrefsSection() {
  const userId = useSession((s) => s.session?.user.id ?? null);
  const { colors, setColor, setLinkOpacity, resetColors } = useGanttColors();
  const [notice, setNotice] = useState<string | null>(null);
  const [customCount, setCustomCount] = useState<number>(
    () => LAYOUT_KEYS.filter((k) => loadPref(k, userId) !== null).length,
  );

  const isDefaultColors =
    colors.plan === DEFAULT_GANTT_COLORS.plan &&
    colors.actual === DEFAULT_GANTT_COLORS.actual &&
    colors.cpm === DEFAULT_GANTT_COLORS.cpm &&
    colors.linkOpacity === DEFAULT_GANTT_COLORS.linkOpacity;

  const resetLayout = () => {
    for (const k of LAYOUT_KEYS) savePref(k, userId, null);
    setCustomCount(0);
    setNotice('표 · 간트 열 너비와 레이아웃을 기본값으로 초기화했습니다. 열려 있는 창은 다시 열면 반영됩니다.');
  };

  return (
    <div className="st-pane">
      <div className="st-section-head">
        <h2>차트 · 표 기본값</h2>
        <p className="st-muted">간트 차트의 막대 색상·관계선 투명도와 스케줄 표·간트 열 레이아웃 기본값을 관리합니다.</p>
      </div>

      <section className="st-card" aria-label="간트 차트 색상 및 투명도">
        <div className="st-card-head">
          <b className="st-card-name">간트 차트 색상 · 크리티컬 연결선 투명도</b>
          <span className="st-gap" />
          <Button
            disabled={isDefaultColors}
            onClick={() => {
              resetColors();
              setNotice('간트 차트 색상을 기본값으로 복원했습니다.');
            }}
          >
            기본 색상으로 복원
          </Button>
        </div>

        <SwatchTable
          colors={colors}
          onPick={(key, hex) => {
            setColor(key, hex);
            setNotice(null);
          }}
        />

        <label className="st-slider-row">
          <span className="st-swatch-label">{`크리티컬 연결선 투명도 (${Math.round(colors.linkOpacity * 100)}%)`}</span>
          <input
            type="range"
            min={10}
            max={100}
            step={5}
            value={Math.round(colors.linkOpacity * 100)}
            aria-label="크리티컬 연결선 투명도"
            onChange={(e) => {
              setLinkOpacity(Number(e.target.value) / 100);
              setNotice(null);
            }}
          />
        </label>
      </section>

      <section className="st-card" aria-label="표 및 간트 레이아웃">
        <div className="st-card-head">
          <b className="st-card-name">스케줄 표 · 간트 열 레이아웃</b>
          <span className="st-gap" />
          <Button disabled={customCount === 0} onClick={resetLayout}>
            표·간트 레이아웃 초기화
          </Button>
        </div>
        <p className="st-muted">
          {customCount === 0
            ? '현재 기본 열 너비·표시 열·행 높이 설정을 사용 중입니다.'
            : `사용자 지정 레이아웃 항목 ${customCount}건이 저장되어 있습니다.`}
        </p>
      </section>

      {notice && (
        <p className="st-ok" role="status">
          {notice}
        </p>
      )}
    </div>
  );
}
