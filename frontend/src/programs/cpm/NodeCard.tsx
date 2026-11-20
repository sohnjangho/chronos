// CPM 카드(SVG): 머리(◇ 마일스톤·ID·상태) / 이름 / Plan 대비 칩 / 줄 / 진도 막대. 층을 끄면 그 층의 것만 빠진다.
// 자리(x, y)가 바뀐 카드만 다시 그린다(memo) — 200개에서 끌어도 끊기지 않게.
import { memo, type KeyboardEvent, type PointerEvent } from 'react';
import type { Activity } from '../../shared/schedule/scheduleApi';
import { cardRows, planChip, statusLabel, type Layers } from './cards';
import { CARD_H, CARD_W } from './layout';

const HEAD_H = 26;
const LEFT = 10;
const VALUE_X = 62;
const VALUE_GAP = 88;
/** cardRows 의 두 값 사이(「03.02 ~ 03.19」·「50일 / 32일」). */
const PAIR = / ~ | \/ /;

/** 글 폭 어림(한글·한자 1em, 나머지 0.6em). */
export function textWidth(text: string, fontPx: number): number {
  let w = 0;
  for (const ch of text) w += (ch.codePointAt(0) ?? 0) >= 0x2e80 ? fontPx : fontPx * 0.6;
  return w;
}

/** maxPx 안에 들어가게 자르고 … 를 붙인다. */
export function clip(text: string, maxPx: number, fontPx: number): string {
  if (textWidth(text, fontPx) <= maxPx) return text;
  let out = '';
  for (const ch of text) {
    if (textWidth(`${out}${ch}…`, fontPx) > maxPx) break;
    out += ch;
  }
  return `${out}…`;
}

/** 오른쪽 끝에 붙는 작은 알약(상태). */
function Pill({ text, right, y, cls }: { text: string; right: number; y: number; cls: string }) {
  const w = textWidth(text, 11) + 12;
  return (
    <g className={cls}>
      <rect x={right - w} y={y} width={w} height={16} rx={8} />
      <text x={right - w / 2} y={y + 12} textAnchor="middle">
        {text}
      </text>
    </g>
  );
}

interface CardProps {
  a: Activity;
  x: number;
  y: number;
  layers: Layers;
  selected: boolean;
  /** Tab 차례에 든 카드(그림 판에 하나 — 나머지는 화살표로 간다). */
  tabbable: boolean;
  onDown(id: string, e: PointerEvent<SVGGElement>): void;
  onKey(id: string, e: KeyboardEvent<SVGGElement>): void;
  onFocusCard(id: string): void;
}

/** 읽어 주는 이름: ID 이름, 크리티컬, 상태(층과 상관없이). */
const spoken = (a: Activity) => `${a.id} ${a.name}${a.critical ? ', 크리티컬' : ''}, ${statusLabel(a)}`;

function NodeCard({ a, x, y, layers, selected, tabbable, onDown, onKey, onFocusCard }: CardProps) {
  const critical = layers.cpm && a.critical ? ' critical' : '';
  const chip = planChip(a.status);
  const rows = cardRows(a, layers);
  const rowTop = layers.plan ? 92 : 70;
  const idText = `${a.kind === 'task' ? '' : '◇ '}${a.id}`;
  return (
    <g
      data-node={a.id}
      transform={`translate(${x} ${y})`}
      className={`cpm-card${selected ? ' is-selected' : ''}`}
      role="button"
      tabIndex={tabbable ? 0 : -1}
      aria-label={spoken(a)}
      aria-current={selected ? 'true' : undefined}
      onPointerDown={(e) => onDown(a.id, e)}
      onKeyDown={(e) => onKey(a.id, e)}
      onFocus={() => onFocusCard(a.id)}
    >
      <title>{`${a.id} ${a.name}`}</title>
      {selected && <rect className="cpm-card-halo" x={-4} y={-4} width={CARD_W + 8} height={CARD_H + 8} rx={11} />}
      <rect className="cpm-card-bg" width={CARD_W} height={CARD_H} rx={8} />
      <rect className={`cpm-card-head${critical}`} width={CARD_W} height={HEAD_H} rx={8} />
      <rect className={`cpm-card-head${critical}`} y={HEAD_H - 8} width={CARD_W} height={8} />
      <text className={`cpm-card-id${critical}`} x={LEFT} y={17}>
        {clip(idText, layers.actual ? 150 : 228, 12)}
      </text>
      {layers.actual && <Pill text={statusLabel(a)} right={CARD_W - 8} y={5} cls="cpm-pill" />}
      <text className="cpm-card-name" x={LEFT} y={46}>
        {clip(a.name, CARD_W - 2 * LEFT, 13)}
      </text>
      {layers.plan && (
        <g>
          <text className="cpm-k" x={LEFT} y={70}>
            Plan 대비
          </text>
          <g className={`cpm-chip is-${chip.tone}`}>
            <rect x={72} y={58} width={textWidth(chip.text, 11) + 14} height={16} rx={8} />
            <text x={79} y={70}>
              {chip.text}
            </text>
          </g>
        </g>
      )}
      {rows.map((row, i) => (
        <g key={row.label}>
          <text className="cpm-k" x={LEFT} y={rowTop + i * 17}>
            {row.label}
          </text>
          {/* 시안처럼 두 값(ES·EF 등)은 두 칸에 */}
          {row.value.split(PAIR).map((part, k) => (
            <text key={k} className="cpm-v" x={VALUE_X + k * VALUE_GAP} y={rowTop + i * 17}>
              {part}
            </text>
          ))}
        </g>
      ))}
      {layers.actual && a.progress > 0 && (
        <rect data-progress className="cpm-progress" x={1} y={CARD_H - 4} width={(CARD_W - 2) * Math.min(1, a.progress)} height={3} />
      )}
      <rect className={`cpm-card-frame${critical}`} width={CARD_W} height={CARD_H} rx={8} />
    </g>
  );
}

export default memo(NodeCard);
