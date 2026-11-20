// 그림 내보내기: 모든 줄(접은 것은 접힌 채)을 한 장의 SVG 로 — 왼쪽 WBS/ID·이름 + 날짜 머리 + 차트.
// 화면 밖에 잠깐 그려 CSS 를 계산시킨 뒤 shared/gantt/exportImage 가 PNG(안 되면 SVG)로 내려받는다.
import { flushSync } from 'react-dom';
import { createRoot } from 'react-dom/client';
import { ROW_H } from '../../../shared/gantt/Bars';
import { downloadSvgImage } from '../../../shared/gantt/exportImage';
import Header, { HEADER_H } from '../../../shared/gantt/Header';
import ChartRows, { type ChartModel } from './ChartRows';
import { headerMarks } from './model';

const ID_W = 120;
const NAME_W = 240;
const LEFT = ID_W + NAME_W;

function Sheet({ m }: { m: ChartModel }) {
  const bodyH = m.rows.length * ROW_H;
  return (
    <svg className="gantt-svg" width={LEFT + m.total} height={HEADER_H + bodyH}>
      <clipPath id="gt-x-name">
        <rect x={ID_W} y={0} width={NAME_W - 8} height={HEADER_H + bodyH} />
      </clipPath>
      <rect className="gantt-head-bg" width={LEFT} height={HEADER_H} />
      <text className="gantt-month" x={8} y={52}>
        WBS / ID
      </text>
      <text className="gantt-month" x={ID_W + 8} y={52}>
        이름
      </text>
      {m.rows.map((r, i) => (
        <g key={r.key} transform={`translate(0 ${HEADER_H + i * ROW_H})`}>
          <rect className={`gantt-band${r.kind === 'group' ? ' is-group' : ''}`} width={LEFT} height={ROW_H} />
          <text className={r.kind === 'group' ? 'gantt-month' : 'gantt-label'} x={8 + r.depth * 14} y={19}>
            {r.kind === 'group' ? r.label : r.activity!.id}
          </text>
          {r.activity && (
            <text className="gantt-label" x={ID_W + 8} y={19} clipPath="url(#gt-x-name)">
              {r.activity.name}
            </text>
          )}
        </g>
      ))}
      <svg x={LEFT} y={0} width={m.total} height={HEADER_H} overflow="hidden">
        <Header scale={m.scale} marks={headerMarks(m.vmarks)} />
      </svg>
      <svg x={LEFT} y={HEADER_H} width={m.total} height={bodyH} overflow="hidden">
        <ChartRows m={m} first={0} last={m.rows.length - 1} />
      </svg>
    </svg>
  );
}

/** 지금 보이는 층·묶음·눈금 그대로 모든 줄을 그림 파일로. */
export async function exportImage(m: ChartModel, fileBase: string): Promise<void> {
  const host = document.createElement('div');
  host.style.cssText = 'position:fixed;left:-100000px;top:0;';
  document.body.appendChild(host);
  const root = createRoot(host);
  try {
    flushSync(() => root.render(<Sheet m={{ ...m, editable: false, drag: null, onBar: undefined, onEdit: undefined, onPick: undefined }} />));
    const bg = getComputedStyle(document.documentElement).getPropertyValue('--bg-panel').trim() || '#ffffff';
    await downloadSvgImage(host.querySelector('svg')!, fileBase, bg);
  } finally {
    root.unmount();
    host.remove();
  }
}
