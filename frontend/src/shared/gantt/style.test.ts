// 간트 그림의 색 규칙(fix 2): Plan 막대 테두리 대비(WCAG 1.4.11, 3:1)와 이름 바탕(점선이 이름을 지나가지 않게).
import { expect, test } from 'vitest';
import tokens from '../../os/tokens.css?raw';
import css from './gantt.css?raw';

/** 한 블록의 --이름: 값. */
function block(selector: string): Map<string, string> {
  const start = tokens.indexOf(`${selector} {`);
  const body = tokens.slice(start, tokens.indexOf('}', start));
  return new Map([...body.matchAll(/(--[\w-]+):\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]));
}

function contrast(a: string, b: string): number {
  const lum = (hex: string) => {
    const n = hex.replace('#', '');
    const full = n.length === 3 ? [...n].map((c) => c + c).join('') : n;
    const [r, g, b2] = [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
    return 0.2126 * r + 0.7152 * g + 0.0722 * b2;
  };
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const rule = (sel: string) => {
  const i = css.indexOf(`${sel} {`);
  return i < 0 ? '' : css.slice(i, css.indexOf('}', i));
};

test('the Plan bar outline reaches 3:1 against every row background in both themes', () => {
  // 간트 탭은 사용자가 고른 층 색(--gt-plan)을 덮어쓴다. 그 밖(내보내기 등)에서는 뒤의 토큰이 테두리다.
  const stroke = /stroke:\s*(?:var\(--gt-plan,\s*)?var\((--[\w-]+)\)/.exec(rule('.gantt-bar'))?.[1];
  expect(stroke).toBeTruthy();
  const light = block(':root');
  const dark = block(':root[data-theme="dark"]');
  for (const theme of [light, dark]) {
    const line = theme.get(stroke!) ?? light.get(stroke!)!;
    for (const bg of ['--bg-panel', '--bg-panel-alt', '--bg-selected', '--bg-app']) {
      expect(contrast(line, theme.get(bg) ?? light.get(bg)!), `${stroke} on ${bg}`).toBeGreaterThanOrEqual(3);
    }
  }
});

test('bar names have a panel-coloured halo so dotted outlines do not strike through them', () => {
  const label = rule('.gantt-svg .gantt-label');
  expect(label).toMatch(/paint-order:\s*stroke/);
  expect(label).toMatch(/stroke:\s*var\(--bg-panel\)/);
  expect(label).toMatch(/stroke-width:\s*3px/);
});
