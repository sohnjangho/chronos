import { expect, test } from 'vitest';
import html from '../../index.html?raw';
import { registerPrograms } from '../programs';
import uiCss from '../shared/ui/ui.css?raw';
import { programs } from './registry';
import tokens from './tokens.css?raw';

const shellCss = import.meta.glob<string>('./*.css', { query: '?raw', import: 'default', eager: true });

/** `선택자 { … }` 블록 안의 --이름: 값 들. */
function tokenBlock(selector: string): Map<string, string> {
  const start = tokens.indexOf(`${selector} {`);
  expect(start, `${selector} 블록`).toBeGreaterThanOrEqual(0);
  const body = tokens.slice(start, tokens.indexOf('\n}', start));
  return new Map([...body.matchAll(/(--[\w-]+):\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]));
}

// 값이 색 글자(hex)를 품은 토큰. var() 만 섞은 토큰은 어두운 테마에서 저절로 따라간다.
const isColor = (v: string) => /#[0-9a-fA-F]{3,8}\b/.test(v);

test('Noto Sans KR is loaded from Google Fonts and is the font token', () => {
  expect(html).toContain('<link rel="preconnect" href="https://fonts.googleapis.com" />');
  expect(html).toContain('<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />');
  expect(html).toContain(
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700&display=swap" />',
  );
  expect(tokens).toContain('--font-sans: "Noto Sans KR", system-ui, sans-serif;');
  expect(tokens).not.toContain('Pretendard');
});

test('shell styles take colors, font sizes and fonts only from tokens', () => {
  const files = Object.entries(shellCss).filter(([f]) => !f.endsWith('tokens.css'));
  expect(files.map(([f]) => f).sort()).toEqual(['./dock.css', './menubar.css', './os.css', './overlays.css']);
  for (const [file, css] of [...files, ['ui.css', uiCss] as const]) {
    expect(css.length, file).toBeGreaterThan(0);
    expect(css, file).not.toMatch(/#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(/);
    expect(css, file).not.toMatch(/font-size:\s*[0-9]/);
    expect(css, file).not.toMatch(/font-family:(?!\s*var\()/);
  }
});

test('every color token has a dark theme value', () => {
  const light = tokenBlock(':root');
  const dark = tokenBlock(':root[data-theme="dark"]');
  const colors = [...light].filter(([, v]) => isColor(v)).map(([k]) => k);
  expect(colors.length).toBeGreaterThan(30);
  expect(colors.filter((k) => !dark.has(k))).toEqual([]);
});

test('menubar and Dock role tokens exist and the menubar is 48px', () => {
  const light = tokenBlock(':root');
  for (const k of ['--on-topbar-fg', '--on-topbar-muted', '--on-topbar-hover', '--on-topbar-fill', '--on-topbar-line', '--on-accent', '--menu-hover-bg', '--menu-shadow', '--dock-surface', '--dock-shadow', '--dock-tile'])
    expect(light.has(k), k).toBe(true);
  expect(light.get('--topbar-h')).toBe('48px');
});

test('every program has its own icon tone with gradient tokens in both themes', () => {
  registerPrograms();
  // tone 이 없으면 기본 slate(설정 프로그램).
  const tones = programs('admin').map((p) => p.tone ?? 'slate');
  expect(new Set(tones).size).toBe(tones.length);
  const light = tokenBlock(':root');
  const dark = tokenBlock(':root[data-theme="dark"]');
  for (const t of [...tones, 'slate']) {
    for (const end of ['from', 'to']) {
      expect(light.has(`--tile-${t}-${end}`), `${t} ${end}`).toBe(true);
      expect(dark.has(`--tile-${t}-${end}`), `${t} ${end} dark`).toBe(true);
    }
  }
});

test('reduced motion turns off Dock magnification transitions and the launch bounce', () => {
  const dock = shellCss['./dock.css'];
  const reduced = dock.slice(dock.indexOf('@media (prefers-reduced-motion: reduce)'));
  expect(reduced).toContain('animation: none');
  expect(reduced).toContain('transition: none');
  expect(dock).toMatch(/@keyframes os-dock-bounce/);
});
