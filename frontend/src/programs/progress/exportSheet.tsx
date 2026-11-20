// 그림 내보내기: S-커브 한 장(제목 · 범례 · 곡선)을 화면 밖에 잠깐 그려 CSS 를 계산시킨 뒤
// shared/gantt/exportImage 가 PNG(안 되면 SVG)로 내려받는다(간트차트와 같은 방식, 프로그램끼리 import 없음).
import { flushSync } from 'react-dom';
import { createRoot } from 'react-dom/client';
import { downloadSvgImage } from '../../shared/gantt/exportImage';
import { dot } from '../../shared/schedule/format';
import type { ProgressData } from './progressApi';
import { CurveSvg, legend } from './SCurveCard';

const W = 1200;
const H = 600;
const HEAD = 70;
const LINES: Record<string, string> = { 'is-plan': 'pg-line-plan', 'is-actual': 'pg-line-actual', 'is-forecast': 'pg-line-forecast' };

function Swatch({ cls }: { cls: string }) {
  if (cls.startsWith('is-bar')) return <rect className={cls === 'is-bar-plan' ? 'pg-bar-plan' : 'pg-bar-actual'} x={0} y={2} width={10} height={10} />;
  return <line className={LINES[cls]} x1={0} x2={18} y1={7} y2={7} />;
}

function Sheet({ data, title }: { data: ProgressData; title: string }) {
  return (
    <svg className="pg-sheet" width={W} height={H}>
      <text className="pg-sheet-title" x={24} y={30}>{title}</text>
      {legend(data.unit).map(([text, cls], i) => (
        <g key={cls} transform={`translate(${24 + i * 130} 44)`}>
          <Swatch cls={cls} />
          <text className="pg-axis" x={24} y={11}>{text}</text>
        </g>
      ))}
      <CurveSvg data={data} width={W} height={H - HEAD} y={HEAD} />
    </svg>
  );
}

/** 지금 보는 단위(주/월)의 S-커브를 '<fileBase>.png' 로. */
export async function exportImage(data: ProgressData, name: string, fileBase: string): Promise<void> {
  const host = document.createElement('div');
  host.style.cssText = 'position:fixed;left:-100000px;top:0;';
  document.body.appendChild(host);
  const root = createRoot(host);
  const title = `${name} — 공정률 S-커브 · Data Date ${dot(data.data_date)}${data.data_date_assumed ? '(오늘로 가정)' : ''}`;
  try {
    flushSync(() => root.render(<Sheet data={data} title={title} />));
    const bg = getComputedStyle(document.documentElement).getPropertyValue('--bg-panel').trim() || '#ffffff';
    await downloadSvgImage(host.querySelector('svg')!, fileBase, bg);
  } finally {
    root.unmount();
    host.remove();
  }
}
