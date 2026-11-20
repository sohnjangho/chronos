import { expect, test } from 'vitest';
import settingsCss from './settings.css?raw';
import { checkedText, isRouter, PROVIDERS, resolveSection, STRATEGIES, statusView } from './model';

test('statusView', () => {
  expect(statusView({ status: 'ok', model_count: 512 })).toEqual({ tone: 'success', text: '연결됨 · 모델 512개' });
  expect(statusView({ status: 'failed', model_count: 3 })).toEqual({ tone: 'danger', text: '연결 실패' });
  expect(statusView({ status: 'unknown', model_count: null })).toEqual({ tone: 'neutral', text: '미확인' });
});

test('providers: Liner fills its url, the OpenAI-compatible one does not', () => {
  expect(PROVIDERS).toEqual([
    { value: 'liner', label: 'Liner', defaultBaseUrl: 'https://platform.liner.com/api/v1' },
    { value: 'openai_compatible', label: '직접 URL (OpenAI 호환)', defaultBaseUrl: null },
  ]);
});

test('only *-router models are routers', () => {
  expect(isRouter('liner-claude-router')).toBe(true);
  expect(isRouter('liner-mark')).toBe(false);
  expect(isRouter('router-x')).toBe(false);
});

test('resolveSection: known sections open, admin-only ones fall back to 내 정보 for users', () => {
  expect(resolveSection('assign', 'admin')).toBe('assign');
  expect(resolveSection('approval', 'admin')).toBe('approval');
  expect(resolveSection('llm', 'user')).toBe('me');
  expect(resolveSection('approval', 'user')).toBe('me');
  expect(resolveSection('me', 'admin')).toBe('me');
  // 없거나 모르는 구역이면 관리자는 LLM 연결(시안), 사용자는 내 정보.
  expect(resolveSection(undefined, 'admin')).toBe('llm');
  expect(resolveSection('nope', 'admin')).toBe('llm');
  expect(resolveSection(undefined, 'user')).toBe('me');
});

test('checkedText reads a server time without a zone as UTC and says today', () => {
  const at = new Date(2026, 10, 20, 21, 32);
  const now = new Date(2026, 10, 20, 23, 0);
  const naive = at.toISOString().replace('Z', '');
  expect(checkedText(naive, 412, now)).toBe('오늘 21:32 · 응답 412ms');
  expect(checkedText(at.toISOString().replace('Z', '+00:00'), null, now)).toBe('오늘 21:32');
  expect(checkedText(naive, 9, new Date(2026, 10, 21, 8, 0))).toBe('11월 20일 21:32 · 응답 9ms');
  expect(checkedText(null, null, now)).toBe('확인한 적 없음');
});

test('settings styles take colors, font sizes and fonts only from tokens', () => {
  expect(settingsCss.length).toBeGreaterThan(0);
  expect(settingsCss).not.toMatch(/#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(/);
  expect(settingsCss).not.toMatch(/font-size:\s*[0-9]/);
  expect(settingsCss).not.toMatch(/font-family:(?!\s*var\()/);
});

test('strategies have Korean labels over the stored values', () => {
  expect(STRATEGIES).toEqual([
    { value: 'cost', label: '비용 우선' },
    { value: 'balanced', label: '균형' },
    { value: 'quality', label: '품질 우선' },
  ]);
});

test('settings layout guards against horizontal overflow (checked on screen too)', () => {
  // 창이 좁아지면 두 칸을 한 칸으로 접는다(창 너비 기준 container query).
  expect(settingsCss).toMatch(/\.st-main\s*\{[^}]*container-type:\s*inline-size/);
  expect(settingsCss).toMatch(/@container[^{]*\(max-width:[^)]*\)\s*\{[^@]*\.st-llm\s*\{[^}]*flex-direction:\s*column/);
  // 입력 칸·고르기는 칸보다 넓어지지 않는다. 두 칸 격자는 minmax(0, 1fr).
  expect(settingsCss).toMatch(/\.st-root input,\s*\.st-root select\s*\{[^}]*min-width:\s*0;[^}]*max-width:\s*100%/);
  expect(settingsCss).toMatch(/\.st-grid2\s*\{[^}]*minmax\(0,\s*1fr\)/);
});

test('every place that shows user-supplied names, ids or URLs may break anywhere', () => {
  const rule = (selector: string) => {
    const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return new RegExp(`(^|[,}\\s])${escaped}\\s*(,[^{]*)?\\{[^}]*overflow-wrap:\\s*anywhere`, 'm');
  };
  for (const selector of ['.st-wrap', '.st-card-name', '.st-facts dd', '.st-error', '.st-vgroup-head', '.st-vendor-list .st-check']) {
    expect(settingsCss, selector).toMatch(rule(selector));
  }
});
