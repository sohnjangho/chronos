// 같은 차트: 액티비티마다 윗줄 기준 막대 · 아랫줄 비교 막대(당김 초록 · 밀림 빨강 · 같음 회색), 기한 세로선.
// 왼쪽 칸은 창 폭에 따라 줄인다(넓음: ID·이름·구분·시작 차이·종료 차이·OD / 보통: ID·이름·종료 차이 / 좁음: 이름).
// 차트는 남은 폭에 꼭 맞춘다 — 창이 가로로 밀리지 않는다. 날짜 → px 는 shared/gantt 눈금만 쓴다.
import Header from '../../shared/gantt/Header';
import { makeScale, type Scale } from '../../shared/gantt/scale';
import type { CompareOut, RowOut } from './compareApi';
import Bar, { dueX, extentOf, ROW_H } from './Bar';
import { CHANGE_LABEL, deadlinesOf, deltaText, odText, spanOf, toneOf } from './rows';
import { useWidth } from './useWidth';

type Mode = 'wide' | 'mid' | 'narrow';
const COLS: Record<Mode, number[]> = { wide: [72, 196, 52, 72, 72, 72], mid: [64, 150, 70], narrow: [132] };
const modeOf = (w: number): Mode => (w >= 1100 ? 'wide' : w >= 640 ? 'mid' : 'narrow');
const HEADS: Record<Mode, string[]> = {
  wide: ['ID', '이름', '구분', '시작 차이', '종료 차이', 'OD'],
  mid: ['ID', '이름', '종료 차이'],
  narrow: ['액티비티'],
};

/** 막대 옆 글: 당김·밀림은 종료 차이(같으면 시작 차이), 그 밖은 구분. */
function labelOf(r: RowOut): string {
  if (r.change === 'same') return '';
  if (r.change === 'pulled' || r.change === 'pushed') return r.finish_delta ? deltaText(r.finish_delta) : `시작 ${deltaText(r.start_delta)}`;
  if (r.change === 'duration') return `OD ${odText(r)}`;
  return CHANGE_LABEL[r.change];
}

function Cells({ r, mode }: { r: RowOut; mode: Mode }) {
  if (mode === 'narrow')
    return (
      <div className="cmp-cell" title={`${r.activity_id} ${r.name}`}>
        <b>{r.activity_id}</b> {r.name}
      </div>
    );
  const finish = <div className={`cmp-cell cmp-num ${toneOf(r.finish_delta)}`}>{deltaText(r.finish_delta)}</div>;
  return (
    <>
      <div className="cmp-cell">{r.activity_id}</div>
      <div className="cmp-cell" title={r.name}>
        {r.name}
      </div>
      {mode === 'wide' && (
        <div className="cmp-cell cmp-which">
          <span><i className="cmp-swatch is-base" />기준</span>
          <span><i className={`cmp-swatch is-${r.change}`} />비교</span>
        </div>
      )}
      {mode === 'wide' && <div className={`cmp-cell cmp-num ${toneOf(r.start_delta)}`}>{deltaText(r.start_delta)}</div>}
      {finish}
      {mode === 'wide' && <div className="cmp-cell cmp-num">{odText(r)}</div>}
    </>
  );
}

function Bars({ r, scale, chartW }: { r: RowOut; scale: Scale; chartW: number }) {
  const text = labelOf(r);
  const ext = extentOf(scale, [r.base, r.other]);
  const after = ext && ext.to + 6 + text.length * 7 <= chartW;
  return (
    <svg className="gantt-svg cmp-rowsvg" width={chartW} height={ROW_H}>
      <line className="cmp-mid" x1={0} x2={chartW} y1={ROW_H / 2} y2={ROW_H / 2} />
      {r.base && <Bar scale={scale} cell={r.base} y={7} h={8} className="is-base" testId={`bar-${r.activity_id}-base`} what={`${r.name} — 기준`} />}
      {r.other && <Bar scale={scale} cell={r.other} y={21} h={8} className={r.change} testId={`bar-${r.activity_id}-other`} what={`${r.name} — 비교`} />}
      {text && ext && (
        <text className={`cmp-delta is-${r.change}`} x={after ? ext.to + 6 : ext.from - 6} y={ROW_H / 2 + 4} textAnchor={after ? 'start' : 'end'}>
          {text}
        </text>
      )}
    </svg>
  );
}

export default function OverlayChart({ data, rows }: { data: CompareOut; rows: RowOut[] }) {
  const { ref, width } = useWidth<HTMLDivElement>(1200);
  const mode = modeOf(width);
  const leftW = COLS[mode].reduce((a, b) => a + b, 0);
  const chartW = Math.max(160, width - leftW);
  const lines = deadlinesOf([
    ['기준', data.base],
    ['비교', data.other],
  ]);
  const span = spanOf(data.rows, lines.map((l) => l.date));
  const grid = { gridTemplateColumns: COLS[mode].map((c) => `${c}px`).join(' ') };
  if (!span) return <p className="cmp-empty">액티비티가 없습니다.</p>;
  const scale = makeScale(span.start, span.end, chartW, 5);
  return (
    <div className="cmp-ov" ref={ref} role="region" aria-label="같은 차트">
      <div className="cmp-ov-head">
        <div className="cmp-cols" style={grid}>
          {HEADS[mode].map((h) => (
            <div key={h} className={`cmp-cell${h.includes('차이') || h === 'OD' ? ' cmp-num' : ''}`}>
              {h}
            </div>
          ))}
        </div>
        <Header scale={scale} marks={lines.map((l) => ({ key: l.label, x: dueX(scale, l.date), label: l.label, tone: 'deadline' }))} />
      </div>
      {rows.length === 0 && <p className="cmp-empty">달라진 액티비티가 없습니다.</p>}
      <div className="cmp-ov-body" style={{ height: rows.length * ROW_H }}>
        {rows.map((r) => (
          <div key={r.activity_id} className="cmp-ov-row" data-testid={`row-${r.activity_id}`}>
            <div className="cmp-cols" style={grid}>
              <Cells r={r} mode={mode} />
            </div>
            <Bars r={r} scale={scale} chartW={chartW} />
          </div>
        ))}
        {rows.length > 0 && (
          <svg className="cmp-lines" style={{ left: leftW }} width={chartW} height={rows.length * ROW_H} aria-hidden="true">
            {lines.map((l) => (
              <line key={l.label} data-testid={`deadline-${l.date}`} className="gantt-vline is-deadline" x1={dueX(scale, l.date)} x2={dueX(scale, l.date)} y1={0} y2={rows.length * ROW_H} />
            ))}
          </svg>
        )}
      </div>
    </div>
  );
}
