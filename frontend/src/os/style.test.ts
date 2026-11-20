import { expect, test } from 'vitest';
import html from '../../index.html?raw';
import uiCss from '../shared/ui/ui.css?raw';
import osCss from './os.css?raw';
import tokens from './tokens.css?raw';

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
  for (const css of [osCss, uiCss]) {
    expect(css.length).toBeGreaterThan(0);
    expect(css).not.toMatch(/#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(/);
    expect(css).not.toMatch(/font-size:\s*[0-9]/);
    expect(css).not.toMatch(/font-family:(?!\s*var\()/);
  }
});
