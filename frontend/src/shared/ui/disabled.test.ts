// 꺼진 주 단추·위험 단추: 강조색 면 위 흐린 글은 읽히지 않는다 → 옅은 바탕 + 흐린 글, 두 테마에서 글 대비 3:1 이상.
// 한 곳(ui.css)에서만 정한다 — 프로그램 CSS 가 따로 덮지 않는다.
import { expect, test } from 'vitest';
import tokens from '../../os/tokens.css?raw';
import css from './ui.css?raw';

const programCss = import.meta.glob<string>('../../programs/**/*.css', { query: '?raw', import: 'default', eager: true });

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

/** 선택자 목록에 sel 이 든 규칙 블록. */
function ruleWith(sel: string): string {
  const plain = css.replace(/\/\*[\s\S]*?\*\//g, ''); // 설명글 빼고
  const m = [...plain.matchAll(/([^{}]+)\{([^{}]*)\}/g)].find(([, sels]) => sels.split(',').map((x) => x.trim()).includes(sel));
  return m?.[2] ?? '';
}

test.each(['.ui-btn-primary:disabled', '.ui-btn-danger:disabled'])('%s keeps its text readable (3:1) in both themes without fading', (sel) => {
  const body = ruleWith(sel);
  const fg = /(?<![-\w])color:\s*var\((--[\w-]+)\)/.exec(body)?.[1];
  const bg = /background:\s*var\((--[\w-]+)\)/.exec(body)?.[1];
  expect(fg, `${sel} color`).toBeTruthy();
  expect(bg, `${sel} background`).toBeTruthy();
  expect(body).toMatch(/opacity:\s*1\s*;/);
  const light = block(':root');
  const dark = block(':root[data-theme="dark"]');
  for (const theme of [light, dark]) {
    expect(contrast(theme.get(fg!) ?? light.get(fg!)!, theme.get(bg!) ?? light.get(bg!)!), sel).toBeGreaterThanOrEqual(3);
  }
});

test('no program overrides the shared disabled look of primary buttons', () => {
  for (const [file, text] of Object.entries(programCss)) expect(text, file).not.toMatch(/\.ui-btn-(primary|danger):disabled/);
});
